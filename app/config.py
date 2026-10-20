import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_IDS = {int(x) for x in _list("TELEGRAM_ADMIN_IDS")}

THREADS_APP_ID = os.getenv("THREADS_APP_ID", "")
THREADS_APP_SECRET = os.getenv("THREADS_APP_SECRET", "")
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN", "")

CLAUDE_MODEL_WRITER = os.getenv("CLAUDE_MODEL_WRITER", "claude-sonnet-5-5")
CLAUDE_MODEL_REPLY = os.getenv("CLAUDE_MODEL_REPLY", "claude-haiku-5-5")
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "low")

TIMEZONE = os.getenv("TIMEZONE", "Asia/Jakarta")
DRY_RUN = _bool("DRY_RUN", True)
REQUIRE_APPROVAL_POSTS = _bool("REQUIRE_APPROVAL_POSTS", True)
REQUIRE_APPROVAL_REPLIES = _bool("REQUIRE_APPROVAL_REPLIES", True)
REQUIRE_APPROVAL_COMMENTS = _bool("REQUIRE_APPROVAL_COMMENTS", True)

POST_TIMES = _list("POST_TIMES", "08:00,12:30,19:30")
MAX_POSTS_PER_DAY = _int("MAX_POSTS_PER_DAY", 3)
MAX_REPLIES_PER_HOUR = _int("MAX_REPLIES_PER_HOUR", 20)
MAX_COMMENTS_PER_DAY = _int("MAX_COMMENTS_PER_DAY", 10)

REPLY_POLL_MINUTES = _int("REPLY_POLL_MINUTES", 10)
COMMENT_SCAN_MINUTES = _int("COMMENT_SCAN_MINUTES", 120)
RESEARCH_HOURS = _int("RESEARCH_HOURS", 6)

AUTO_POST_ENABLED = _bool("AUTO_POST_ENABLED", True)
AUTO_REPLY_ENABLED = _bool("AUTO_REPLY_ENABLED", True)
AUTO_COMMENT_ENABLED = _bool("AUTO_COMMENT_ENABLED", False)
AUTO_RESEARCH_ENABLED = _bool("AUTO_RESEARCH_ENABLED", True)

NICHE_KEYWORDS = _list("NICHE_KEYWORDS")
TRENDS_GEO = os.getenv("TRENDS_GEO", "ID")

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/autothreads.db")
PERSONA_FILE = BASE_DIR / os.getenv("PERSONA_FILE", "persona.md")
KNOWLEDGE_FILE = BASE_DIR / os.getenv("KNOWLEDGE_FILE", "knowledge.md")


def _read(path: Path, default: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def persona() -> str:
    return _read(PERSONA_FILE, "Tulis dengan bahasa Indonesia yang santai dan sopan.")


def knowledge() -> str:
    return _read(KNOWLEDGE_FILE, "(belum ada knowledge base)")
