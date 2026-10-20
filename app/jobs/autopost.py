from .. import db, llm
from .common import queue_or_publish, under_limit
from . import research


def from_idea(idea: str):
    """Post dari ide yang dikirim admin lewat Telegram (/post ...). Selalu minta persetujuan."""
    for acc in db.active_accounts():
        text = llm.write_post(idea, "", db.recent_post_texts(acc["id"]))
        queue_or_publish(acc["id"], "post", text, context=idea, force_approval=True)


def run(account_id: int | None = None):
    trend = db.next_unused_trend()
    if not trend:
        research.run()
        trend = db.next_unused_trend()
    if not trend:
        db.log("warn", "autopost: belum ada topik tren, lewati")
        return

    accounts = [db.get_account(account_id)] if account_id else db.active_accounts()
    for acc in accounts:
        if not under_limit(acc["id"], "post"):
            db.log("info", f"autopost @{acc['username']}: batas harian tercapai")
            continue
        try:
            text = llm.write_post(trend["title"], trend["angle"], db.recent_post_texts(acc["id"]))
            queue_or_publish(acc["id"], "post", text, context=trend["title"])
        except Exception as e:
            db.log("error", f"autopost @{acc['username']} gagal: {e}")
    db.mark_trend_used(trend["id"])
