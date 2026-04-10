"""
Database – single SQLite file, auto-initialised on startup.
Tables: users, jobs_seen, applications, star_stories, email_log
"""
import sqlite3
from pathlib import Path
from app.config import settings

DB_PATH = Path(settings.sqlite_db_path)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id   INTEGER PRIMARY KEY,
            name          TEXT,
            email         TEXT,
            master_resume TEXT,          -- raw text of uploaded resume
            created_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS jobs_seen (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id   INTEGER NOT NULL,
            url           TEXT    NOT NULL,
            title         TEXT,
            company       TEXT,
            source        TEXT,
            seen_at       TEXT DEFAULT (datetime('now')),
            UNIQUE(telegram_id, url)
        );

        CREATE TABLE IF NOT EXISTS applications (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id   INTEGER NOT NULL,
            company       TEXT    NOT NULL,
            role          TEXT    NOT NULL,
            status        TEXT    DEFAULT 'Applied',
            url           TEXT,
            notes         TEXT,
            salary        TEXT,
            source        TEXT,
            applied_date  TEXT    DEFAULT (date('now')),
            followup_date TEXT,
            interview_date TEXT,
            created_at    TEXT    DEFAULT (datetime('now')),
            updated_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS star_stories (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id   INTEGER NOT NULL,
            title         TEXT    NOT NULL,
            situation     TEXT,
            task          TEXT,
            action        TEXT,
            result        TEXT,
            themes        TEXT,          -- comma-separated e.g. "leadership,analytics"
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS email_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id   INTEGER NOT NULL,
            to_email      TEXT,
            to_name       TEXT,
            company       TEXT,
            role          TEXT,
            subject       TEXT,
            body          TEXT,
            sent          INTEGER DEFAULT 0,
            followup_date TEXT,
            followup_sent INTEGER DEFAULT 0,
            sent_at       TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS gmail_tokens (
            telegram_id           INTEGER PRIMARY KEY,
            sender_email          TEXT    NOT NULL,
            refresh_token_enc     TEXT    NOT NULL,
            created_at            TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS saved_searches (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id   INTEGER NOT NULL,
            name          TEXT,
            role          TEXT    NOT NULL,
            location      TEXT    NOT NULL DEFAULT 'singapore',
            limit_        INTEGER DEFAULT 5,
            active        INTEGER DEFAULT 1,
            created_at    TEXT    DEFAULT (datetime('now'))
        );
        """)
    print("✅ Database ready:", DB_PATH)


# ── Helpers ──────────────────────────────────────────────────────────────────

def upsert_user(telegram_id: int, name: str = "", email: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(telegram_id,name,email) VALUES(?,?,?)",
            (telegram_id, name, email),
        )


def save_master_resume(telegram_id: int, text: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(telegram_id,master_resume) VALUES(?,?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET master_resume=excluded.master_resume",
            (telegram_id, text),
        )


def get_master_resume(telegram_id: int) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT master_resume FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
    return row["master_resume"] if row else None


def mark_job_seen(telegram_id: int, url: str, title: str, company: str, source: str) -> bool:
    """Returns True if this is a NEW job (not seen before)."""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO jobs_seen(telegram_id,url,title,company,source) VALUES(?,?,?,?,?)",
                (telegram_id, url, title, company, source),
            )
        return True
    except sqlite3.IntegrityError:
        return False  # already seen


def get_applications(telegram_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM applications WHERE telegram_id=? ORDER BY created_at DESC",
            (telegram_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_application(telegram_id: int, company: str, role: str, status: str = "Applied",
                    url: str = "", notes: str = "", salary: str = "",
                    source: str = "", followup_date: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO applications
               (telegram_id,company,role,status,url,notes,salary,source,followup_date)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (telegram_id, company, role, status, url, notes, salary, source, followup_date),
        )
        return cur.lastrowid


def update_application_status(app_id: int, status: str, notes: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE applications SET status=?, notes=?, updated_at=datetime('now') WHERE id=?",
            (status, notes, app_id),
        )


def get_followup_due(telegram_id: int) -> list[dict]:
    """Applications where follow-up date is today or past and status still Applied."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM applications
               WHERE telegram_id=?
               AND status='Applied'
               AND followup_date <= date('now')
               AND followup_date IS NOT NULL""",
            (telegram_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_active_users() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT telegram_id FROM users").fetchall()
    return [r["telegram_id"] for r in rows]


def get_saved_searches(telegram_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM saved_searches WHERE telegram_id=? AND active=1",
            (telegram_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_search_profile(telegram_id: int, name: str, role: str, location: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO saved_searches(telegram_id,name,role,location) VALUES(?,?,?,?)",
            (telegram_id, name, role, location),
        )


def log_email(telegram_id: int, to_email: str, to_name: str, company: str,
              role: str, subject: str, body: str, sent: bool, followup_date: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO email_log
               (telegram_id,to_email,to_name,company,role,subject,body,sent,followup_date)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (telegram_id, to_email, to_name, company, role, subject, body, int(sent), followup_date),
        )


def get_star_stories(telegram_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM star_stories WHERE telegram_id=? ORDER BY created_at DESC",
            (telegram_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_star_story(telegram_id: int, title: str, situation: str,
                   task: str, action: str, result: str, themes: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO star_stories(telegram_id,title,situation,task,action,result,themes)
               VALUES(?,?,?,?,?,?,?)""",
            (telegram_id, title, situation, task, action, result, themes),
        )
