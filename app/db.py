import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    threads_user_id TEXT UNIQUE NOT NULL,
    username TEXT,
    access_token TEXT NOT NULL,
    token_expires_at TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- Semua tulisan bot: post baru, balasan ke komentar, komentar ke post orang lain
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    kind TEXT NOT NULL,              -- post | reply | comment
    text TEXT NOT NULL,
    reply_to_id TEXT,                -- media id yang dibalas (reply/comment)
    context TEXT,                    -- teks asli yang dibalas / topik
    status TEXT NOT NULL,            -- pending | approved | publishing | published | failed | rejected
    escalated INTEGER NOT NULL DEFAULT 0,
    threads_media_id TEXT,
    permalink TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT
);

-- Media (komentar / post orang) yang sudah diproses supaya tidak dibalas dua kali
CREATE TABLE IF NOT EXISTS seen (
    account_id INTEGER NOT NULL,
    media_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_id, media_id, kind)
);

CREATE TABLE IF NOT EXISTS trends (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    angle TEXT,
    reason TEXT,
    score INTEGER,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


@contextmanager
def conn():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        # item yang terputus saat proses publish (mis. server restart) jangan diterbitkan ulang otomatis
        c.execute("UPDATE outbox SET status='failed', error='terputus saat publish, cek manual' WHERE status='publishing'")


def log(level: str, message: str):
    print(f"[{level}] {message}", flush=True)
    with conn() as c:
        c.execute("INSERT INTO logs(level, message, created_at) VALUES (?,?,?)", (level, message, now()))
        c.execute("DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 1000)")


# ---------- accounts ----------

def upsert_account(user_id: str, username: str, token: str, expires_at: str):
    with conn() as c:
        c.execute(
            """INSERT INTO accounts(threads_user_id, username, access_token, token_expires_at, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(threads_user_id) DO UPDATE SET
                 username=excluded.username, access_token=excluded.access_token,
                 token_expires_at=excluded.token_expires_at, active=1""",
            (user_id, username, token, expires_at, now()),
        )


def active_accounts():
    with conn() as c:
        return c.execute("SELECT * FROM accounts WHERE active=1").fetchall()


def all_accounts():
    with conn() as c:
        return c.execute("SELECT * FROM accounts ORDER BY id").fetchall()


def get_account(account_id: int):
    with conn() as c:
        return c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()


def set_account_active(account_id: int, active: bool):
    with conn() as c:
        c.execute("UPDATE accounts SET active=? WHERE id=?", (1 if active else 0, account_id))


def update_token(account_id: int, token: str, expires_at: str):
    with conn() as c:
        c.execute("UPDATE accounts SET access_token=?, token_expires_at=? WHERE id=?", (token, expires_at, account_id))


def deactivate_by_threads_id(user_id: str):
    with conn() as c:
        c.execute("UPDATE accounts SET active=0 WHERE threads_user_id=?", (user_id,))


def delete_by_threads_id(user_id: str):
    with conn() as c:
        row = c.execute("SELECT id FROM accounts WHERE threads_user_id=?", (user_id,)).fetchone()
        if row:
            c.execute("DELETE FROM outbox WHERE account_id=?", (row["id"],))
            c.execute("DELETE FROM seen WHERE account_id=?", (row["id"],))
            c.execute("DELETE FROM accounts WHERE id=?", (row["id"],))


# ---------- outbox ----------

def add_outbox(account_id: int, kind: str, text: str, status: str, reply_to_id=None, context=None,
               escalated: bool = False) -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO outbox(account_id, kind, text, reply_to_id, context, status, escalated, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (account_id, kind, text, reply_to_id, context, status, int(escalated), now()),
        )
        return cur.lastrowid


def get_outbox(item_id: int):
    with conn() as c:
        return c.execute("SELECT * FROM outbox WHERE id=?", (item_id,)).fetchone()


def claim_outbox(item_id: int) -> bool:
    """Tandai item sedang diterbitkan; False kalau sudah diambil proses lain (cegah double post)."""
    with conn() as c:
        cur = c.execute(
            "UPDATE outbox SET status='publishing' WHERE id=? AND status IN ('pending','approved')", (item_id,)
        )
        return cur.rowcount == 1


def outbox_by_status(status: str, limit: int = 100):
    with conn() as c:
        return c.execute(
            """SELECT o.*, a.username FROM outbox o JOIN accounts a ON a.id=o.account_id
               WHERE o.status=? ORDER BY o.id DESC LIMIT ?""",
            (status, limit),
        ).fetchall()


def recent_outbox(limit: int = 50):
    with conn() as c:
        return c.execute(
            """SELECT o.*, a.username FROM outbox o JOIN accounts a ON a.id=o.account_id
               WHERE o.status IN ('published','failed') ORDER BY o.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()


def update_outbox(item_id: int, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE outbox SET {keys} WHERE id=?", (*fields.values(), item_id))


def count_published(account_id: int, kind: str, since: str) -> int:
    with conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM outbox WHERE account_id=? AND kind=? AND status='published' AND published_at>=?",
            (account_id, kind, since),
        ).fetchone()[0]


def count_created(account_id: int, kind: str, since: str) -> int:
    """Termasuk yang masih antri, untuk membatasi jumlah draft yang dibuat."""
    with conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM outbox WHERE account_id=? AND kind=? AND status!='rejected' AND created_at>=?",
            (account_id, kind, since),
        ).fetchone()[0]


def recent_post_texts(account_id: int, limit: int = 15) -> list[str]:
    with conn() as c:
        rows = c.execute(
            "SELECT text FROM outbox WHERE account_id=? AND kind='post' AND status!='rejected' ORDER BY id DESC LIMIT ?",
            (account_id, limit),
        ).fetchall()
    return [r["text"] for r in rows]


# ---------- seen ----------

def is_seen(account_id: int, media_id: str, kind: str) -> bool:
    with conn() as c:
        return c.execute(
            "SELECT 1 FROM seen WHERE account_id=? AND media_id=? AND kind=?", (account_id, media_id, kind)
        ).fetchone() is not None


def mark_seen(account_id: int, media_id: str, kind: str):
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen(account_id, media_id, kind, created_at) VALUES (?,?,?,?)",
            (account_id, media_id, kind, now()),
        )


# ---------- trends ----------

def add_trends(items: list[dict]):
    with conn() as c:
        for t in items:
            c.execute(
                "INSERT INTO trends(title, angle, reason, score, created_at) VALUES (?,?,?,?,?)",
                (t["title"], t.get("angle"), t.get("reason"), int(t.get("score", 0)), now()),
            )


def recent_trends(limit: int = 30):
    with conn() as c:
        return c.execute("SELECT * FROM trends ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def next_unused_trend():
    with conn() as c:
        return c.execute(
            "SELECT * FROM trends WHERE used=0 AND created_at>=? ORDER BY score DESC, id DESC LIMIT 1",
            (ago(days=2),),
        ).fetchone()


def mark_trend_used(trend_id: int):
    with conn() as c:
        c.execute("UPDATE trends SET used=1 WHERE id=?", (trend_id,))


def get_setting(key: str, default: str = "") -> str:
    with conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with conn() as c:
        c.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))


def is_paused() -> bool:
    return get_setting("paused", "0") == "1"


def stats_today(account_id: int) -> dict:
    since = ago(hours=24)
    with conn() as c:
        rows = c.execute(
            "SELECT kind, status, COUNT(*) n FROM outbox WHERE account_id=? AND created_at>=? GROUP BY kind, status",
            (account_id, since),
        ).fetchall()
    return {f"{r['kind']}_{r['status']}": r["n"] for r in rows}


def recent_logs(limit: int = 100):
    with conn() as c:
        return c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
