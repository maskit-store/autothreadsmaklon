"""Auto reply: balas komentar orang di post milik akun kita."""
from datetime import datetime

from .. import db, llm, threads_api
from .common import queue_or_publish, under_limit


def run():
    for acc in db.active_accounts():
        try:
            _run_account(acc)
        except Exception as e:
            db.log("error", f"autoreply @{acc['username']} gagal: {e}")


def _run_account(acc):
    token = acc["access_token"]
    for post in threads_api.my_threads(token, limit=10):
        if post.get("is_reply"):
            continue
        replies = threads_api.conversation(post["id"], token)
        by_id = {r["id"]: r for r in replies}
        for r in replies:
            if r.get("is_reply_owned_by_me") or r.get("username") == acc["username"]:
                continue
            if db.is_seen(acc["id"], r["id"], "reply"):
                continue
            if _older_than(r.get("timestamp"), acc["created_at"]):
                # komentar lama sebelum bot dipasang: jangan dibalas massal
                db.mark_seen(acc["id"], r["id"], "reply")
                continue
            if not under_limit(acc["id"], "reply"):
                db.log("info", f"autoreply @{acc['username']}: batas per jam tercapai")
                return
            db.mark_seen(acc["id"], r["id"], "reply")
            # kalau dia membalas balasan kita, sertakan konteks percakapannya
            parent = by_id.get((r.get("replied_to") or {}).get("id"))
            context = f"@{parent.get('username')}: {parent.get('text')}" if parent else ""
            out = llm.write_reply(post.get("text") or "", r.get("text") or "", r.get("username") or "", context)
            if out["action"] == "skip":
                db.log("info", f"lewati komentar @{r.get('username')}: {out['reason']}")
                continue
            ctx = f"@{r.get('username')}: {r.get('text')}"
            if out["action"] == "escalate":
                ctx += f"\n(alasan eskalasi: {out['reason']}) {r.get('permalink', '')}"
            queue_or_publish(acc["id"], "reply", out["text"], reply_to_id=r["id"], context=ctx,
                             escalated=out["action"] == "escalate")


def _older_than(threads_ts: str | None, iso: str) -> bool:
    if not threads_ts:
        return False
    try:
        return datetime.strptime(threads_ts, "%Y-%m-%dT%H:%M:%S%z") < datetime.fromisoformat(iso)
    except ValueError:
        return False
