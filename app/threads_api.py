"""Wrapper kecil untuk Threads API resmi (graph.threads.net)."""
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from . import config

GRAPH = "https://graph.threads.net"
API = f"{GRAPH}/v1.0"

SCOPES = [
    "threads_basic",
    "threads_content_publish",
    "threads_manage_replies",
    "threads_read_replies",
    "threads_manage_insights",
    "threads_keyword_search",
]


class ThreadsError(Exception):
    pass


def _check(r: requests.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        raise ThreadsError(f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", data)
        raise ThreadsError(f"HTTP {r.status_code}: {err.get('message', err) if isinstance(err, dict) else err}")
    return data


def _get(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    return _check(requests.get(f"{API}/{path}", params=params, timeout=30))


def _post(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    return _check(requests.post(f"{API}/{path}", data=params, timeout=30))


def _expiry(seconds: int | None) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds or 60 * 24 * 3600)).isoformat(timespec="seconds")


# ---------- OAuth ----------

def authorize_url(state: str) -> str:
    q = urlencode({
        "client_id": config.THREADS_APP_ID,
        "redirect_uri": config.THREADS_REDIRECT_URI,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "state": state,
    })
    return f"https://threads.net/oauth/authorize?{q}"


def exchange_code(code: str) -> tuple[str, str]:
    """Kode OAuth -> (short-lived token, user_id)."""
    data = _check(requests.post(f"{GRAPH}/oauth/access_token", data={
        "client_id": config.THREADS_APP_ID,
        "client_secret": config.THREADS_APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": config.THREADS_REDIRECT_URI,
        "code": code,
    }, timeout=30))
    return data["access_token"], str(data["user_id"])


def long_lived_token(short_token: str) -> tuple[str, str]:
    """Short-lived (1 jam) -> long-lived (60 hari). Return (token, expires_at)."""
    data = _check(requests.get(f"{GRAPH}/access_token", params={
        "grant_type": "th_exchange_token",
        "client_secret": config.THREADS_APP_SECRET,
        "access_token": short_token,
    }, timeout=30))
    return data["access_token"], _expiry(data.get("expires_in"))


def refresh_token(token: str) -> tuple[str, str]:
    data = _check(requests.get(f"{GRAPH}/refresh_access_token", params={
        "grant_type": "th_refresh_token",
        "access_token": token,
    }, timeout=30))
    return data["access_token"], _expiry(data.get("expires_in"))


def parse_signed_request(signed_request: str) -> dict | None:
    """Dipakai callback uninstall / data deletion dari Meta."""
    try:
        sig_b64, payload_b64 = signed_request.split(".", 1)
        pad = lambda s: s + "=" * (-len(s) % 4)
        sig = base64.urlsafe_b64decode(pad(sig_b64))
        payload = json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
        expected = hmac.new(config.THREADS_APP_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
        return payload if hmac.compare_digest(sig, expected) else None
    except Exception:
        return None


# ---------- Profil & konten ----------

def me(token: str) -> dict:
    return _get("me", token, fields="id,username,name,threads_profile_picture_url")


def my_threads(token: str, limit: int = 10) -> list[dict]:
    data = _get("me/threads", token, fields="id,text,timestamp,permalink,is_reply", limit=limit)
    return data.get("data", [])


def conversation(media_id: str, token: str) -> list[dict]:
    """Semua balasan (termasuk balasan bertingkat) di bawah sebuah post."""
    data = _get(
        f"{media_id}/conversation", token,
        fields="id,text,username,timestamp,permalink,replied_to,root_post,is_reply_owned_by_me",
        reverse="false",
    )
    return data.get("data", [])


def keyword_search(token: str, q: str, search_type: str = "RECENT", limit: int = 25) -> list[dict]:
    data = _get(
        "keyword_search", token, q=q, search_type=search_type, limit=limit,
        fields="id,text,media_type,permalink,timestamp,username,has_replies,is_reply",
    )
    return data.get("data", [])


def publishing_limit(user_id: str, token: str) -> dict:
    data = _get(f"{user_id}/threads_publishing_limit", token,
                fields="quota_usage,config,reply_quota_usage,reply_config")
    return (data.get("data") or [{}])[0]


def publish_text(user_id: str, token: str, text: str, reply_to_id: str | None = None,
                 topic_tag: str | None = None) -> str:
    """Buat container lalu publish. Return media id post yang terbit."""
    params = {"media_type": "TEXT", "text": text[:500]}
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    if topic_tag:
        params["topic_tag"] = topic_tag
    creation_id = _post(f"{user_id}/threads", token, **params)["id"]
    last_err = None
    for wait in (2, 5, 10, 20):
        time.sleep(wait)
        try:
            return _post(f"{user_id}/threads_publish", token, creation_id=creation_id)["id"]
        except ThreadsError as e:  # container kadang belum siap
            last_err = e
    raise last_err


def permalink(media_id: str, token: str) -> str | None:
    try:
        return _get(media_id, token, fields="permalink").get("permalink")
    except ThreadsError:
        return None
