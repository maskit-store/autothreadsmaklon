from datetime import datetime, timedelta, timezone

from .. import db, threads_api


def refresh_all():
    """Token long-lived berlaku 60 hari; perpanjang yang tinggal < 20 hari."""
    limit = datetime.now(timezone.utc) + timedelta(days=20)
    for acc in db.active_accounts():
        exp = acc["token_expires_at"]
        if exp and datetime.fromisoformat(exp) > limit:
            continue
        try:
            token, expires_at = threads_api.refresh_token(acc["access_token"])
            db.update_token(acc["id"], token, expires_at)
            db.log("info", f"token @{acc['username']} diperpanjang sampai {expires_at[:10]}")
        except Exception as e:
            db.log("error", f"refresh token @{acc['username']} gagal (login ulang di dashboard): {e}")
