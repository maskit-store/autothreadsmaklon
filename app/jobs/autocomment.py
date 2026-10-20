"""Auto comment: cari post orang lain di niche kita lalu beri komentar bernilai."""
import random

from .. import config, db, llm, threads_api
from .common import queue_or_publish, under_limit

MAX_PER_RUN = 3


def run():
    for acc in db.active_accounts():
        try:
            _run_account(acc)
        except Exception as e:
            db.log("error", f"autocomment @{acc['username']} gagal: {e}")


def _run_account(acc):
    keywords = list(config.NICHE_KEYWORDS)
    random.shuffle(keywords)
    done = 0
    for kw in keywords:
        try:
            posts = threads_api.keyword_search(acc["access_token"], kw, "RECENT", limit=15)
        except Exception as e:
            db.log("warn", f"autocomment search '{kw}' gagal: {e}")
            continue
        for p in posts:
            if done >= MAX_PER_RUN or not under_limit(acc["id"], "comment"):
                return
            if p.get("username") == acc["username"] or p.get("is_reply") or not p.get("text"):
                continue
            if db.is_seen(acc["id"], p["id"], "comment"):
                continue
            db.mark_seen(acc["id"], p["id"], "comment")
            text = llm.write_comment(p["text"], p.get("username") or "")
            if text:
                queue_or_publish(acc["id"], "comment", text, reply_to_id=p["id"],
                                 context=f"@{p.get('username')}: {p['text'][:300]} ({p.get('permalink', '')})")
                done += 1
