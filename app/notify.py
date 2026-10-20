"""Kirim pesan ke admin Telegram (dipakai oleh job). Tidak menangani perintah; itu di bot.py."""
import html

import requests

from . import config, db

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
KIND_LABEL = {"post": "📝 Post baru", "reply": "💬 Balasan komentar", "comment": "🗨️ Komentar ke post orang"}


def call(method: str, **payload) -> dict:
    if not config.TELEGRAM_BOT_TOKEN:
        return {}
    try:
        r = requests.post(f"{API}/{method}", json=payload, timeout=40)
        data = r.json()
        if not data.get("ok"):
            print(f"[telegram] {method} gagal: {data.get('description')}", flush=True)
        return data
    except Exception as e:
        print(f"[telegram] {method} error: {e}", flush=True)
        return {}


def to_admins(text: str, buttons: list[list[dict]] | None = None):
    for chat_id in config.TELEGRAM_ADMIN_IDS:
        payload = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        call("sendMessage", **payload)


def esc(s) -> str:
    return html.escape(str(s or ""))


def item_text(item) -> str:
    acc = db.get_account(item["account_id"])
    head = KIND_LABEL.get(item["kind"], item["kind"])
    if item["escalated"]:
        head = "🚨 PERLU ADMIN · " + head
    parts = [f"<b>{head}</b> #{item['id']} · @{esc(acc['username'] if acc else '?')}"]
    if item["context"]:
        label = "Ide" if item["kind"] == "post" else "Membalas"
        parts.append(f"<i>{label}:</i> {esc(item['context'][:600])}")
    if item["topic_tag"]:
        parts.append(f"🏷️ Topik: <b>{esc(item['topic_tag'])}</b>")
    parts.append(f"\n{esc(item['text'])}")
    parts.append(f"\n<i>{len(item['text'])}/500 karakter</i>")
    return "\n".join(parts)


def approval_buttons(item_id: int) -> list[list[dict]]:
    return [[
        {"text": "✅ Posting", "callback_data": f"ok:{item_id}"},
        {"text": "✏️ Revisi", "callback_data": f"rev:{item_id}"},
        {"text": "❌ Buang", "callback_data": f"no:{item_id}"},
    ]]


def ask_approval(item_id: int):
    item = db.get_outbox(item_id)
    if item:
        to_admins(item_text(item), approval_buttons(item_id))
