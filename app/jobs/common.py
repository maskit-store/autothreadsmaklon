from .. import config, db, notify, threads_api


def publish_item(item_id: int) -> bool:
    """Terbitkan satu item outbox (post/reply/comment). Aman dipanggil berulang."""
    item = db.get_outbox(item_id)
    if not item or not db.claim_outbox(item_id):
        return False
    acc = db.get_account(item["account_id"])
    if not acc or not acc["active"]:
        db.update_outbox(item_id, status="failed", error="akun tidak aktif")
        return False

    if db.is_dry_run():
        db.update_outbox(item_id, status="published", published_at=db.now(), threads_media_id="DRY_RUN")
        db.log("info", f"[DRY_RUN] {item['kind']} @{acc['username']}: {item['text'][:80]}")
        notify.to_admins(f"🧪 [DRY_RUN] {item['kind']} #{item_id} dianggap terbit (tidak benar-benar diposting).")
        return True

    try:
        media_id = threads_api.publish_text(acc["threads_user_id"], acc["access_token"], item["text"], item["reply_to_id"])
        link = threads_api.permalink(media_id, acc["access_token"])
        db.update_outbox(item_id, status="published", threads_media_id=media_id, permalink=link,
                         published_at=db.now(), error=None)
        db.log("info", f"{item['kind']} terbit @{acc['username']}: {link or media_id}")
        notify.to_admins(f"✅ {item['kind']} #{item_id} terbit: {link or media_id}")
        return True
    except Exception as e:
        db.update_outbox(item_id, status="failed", error=str(e)[:500])
        db.log("error", f"gagal publish {item['kind']} #{item_id}: {e}")
        notify.to_admins(f"⚠️ Gagal posting {item['kind']} #{item_id}: {notify.esc(e)}",
                         [[{"text": "🔁 Coba lagi", "callback_data": f"ok:{item_id}"}]])
        return False


def under_limit(account_id: int, kind: str) -> bool:
    if kind == "post":
        return db.count_created(account_id, "post", db.ago(hours=24)) < config.MAX_POSTS_PER_DAY
    if kind == "reply":
        return db.count_created(account_id, "reply", db.ago(hours=1)) < config.MAX_REPLIES_PER_HOUR
    if kind == "comment":
        return db.count_created(account_id, "comment", db.ago(hours=24)) < config.MAX_COMMENTS_PER_DAY
    return False


def queue_or_publish(account_id: int, kind: str, text: str, reply_to_id=None, context=None,
                     escalated: bool = False, force_approval: bool = False) -> int:
    need_approval = force_approval or escalated or {
        "post": config.REQUIRE_APPROVAL_POSTS,
        "reply": config.REQUIRE_APPROVAL_REPLIES,
        "comment": config.REQUIRE_APPROVAL_COMMENTS,
    }[kind]
    item_id = db.add_outbox(account_id, kind, text, "pending" if need_approval else "approved", reply_to_id, context,
                            escalated)
    if need_approval:
        db.log("info", f"{kind} #{item_id} menunggu persetujuan di Telegram")
        notify.ask_approval(item_id)
    else:
        publish_item(item_id)
    return item_id


def publish_approved():
    """Jaring pengaman: terbitkan item 'approved' yang belum sempat terbit."""
    for item in db.outbox_by_status("approved"):
        publish_item(item["id"])
