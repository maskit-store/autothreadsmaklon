from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config, db
from .jobs import autocomment, autopost, autoreply, common, research, tokens


def _safe(name, fn, pausable=True):
    def wrapper():
        if pausable and db.is_paused():
            return
        try:
            fn()
        except Exception as e:
            db.log("error", f"job {name} error: {e}")
    return wrapper


def start() -> BackgroundScheduler:
    s = BackgroundScheduler(timezone=config.TIMEZONE, job_defaults={"coalesce": True, "max_instances": 1})

    if config.AUTO_RESEARCH_ENABLED:
        s.add_job(_safe("research", research.run), "interval", hours=config.RESEARCH_HOURS, id="research")
    if config.AUTO_POST_ENABLED:
        for i, t in enumerate(config.POST_TIMES):
            hh, mm = t.split(":")
            s.add_job(_safe("autopost", autopost.run), CronTrigger(hour=int(hh), minute=int(mm)), id=f"autopost_{i}")
    if config.AUTO_REPLY_ENABLED:
        s.add_job(_safe("autoreply", autoreply.run), "interval", minutes=config.REPLY_POLL_MINUTES, id="autoreply")
    if config.AUTO_COMMENT_ENABLED:
        s.add_job(_safe("autocomment", autocomment.run), "interval", minutes=config.COMMENT_SCAN_MINUTES, id="autocomment")

    s.add_job(_safe("publish_approved", common.publish_approved, pausable=False), "interval", minutes=2, id="publish_approved")
    s.add_job(_safe("refresh_tokens", tokens.refresh_all, pausable=False), CronTrigger(hour=3, minute=17), id="refresh_tokens")
    s.start()
    db.log("info", f"scheduler jalan: {[j.id for j in s.get_jobs()]} (DRY_RUN={db.is_dry_run()})")
    return s
