import sqlite3
from pathlib import Path

from core import settings


def get_connection() -> sqlite3.Connection:
    """Return a new SQLite connection per call (thread-safe)."""
    Path(settings.TRANSCRIPTIONS_DIR).mkdir(exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist and run idempotent migrations."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id          TEXT PRIMARY KEY,
                status      TEXT NOT NULL DEFAULT 'pending',
                title       TEXT DEFAULT '',
                source      TEXT DEFAULT '',
                file_path   TEXT,
                model       TEXT NOT NULL,
                device      TEXT,
                timestamp   TEXT NOT NULL,
                duration    REAL DEFAULT 0.0,
                percent     INTEGER DEFAULT 0,
                text        TEXT,
                language    TEXT,
                segments    TEXT,
                error       TEXT,
                created_at  TEXT,
                updated_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS job_queue (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id     TEXT NOT NULL REFERENCES jobs(id),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS benchmarks (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id              TEXT NOT NULL,
                model               TEXT NOT NULL,
                device              TEXT NOT NULL,
                audio_duration      REAL,
                transcription_time  REAL,
                rtf                 REAL,
                created_at          TEXT
            );

            CREATE TABLE IF NOT EXISTS speaker_profiles (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS speaker_embeddings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                speaker_id TEXT REFERENCES speaker_profiles(id),
                embedding  BLOB,
                model      TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name          TEXT DEFAULT '',
                is_active     INTEGER DEFAULT 1,
                quota_minutes REAL DEFAULT 60.0,
                created_at    TEXT,
                updated_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS usage_minutes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    TEXT NOT NULL REFERENCES users(id),
                job_id     TEXT REFERENCES jobs(id),
                minutes    REAL NOT NULL,
                model      TEXT,
                created_at TEXT
            );
        """)
        conn.commit()

        # Idempotent migrations: add columns that may be missing on older DBs
        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
        if "user_id" not in existing_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN user_id TEXT REFERENCES users(id)")
            conn.commit()
        if "diarize" not in existing_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN diarize INTEGER DEFAULT 0")
            conn.commit()
        if "speaker_names" not in existing_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN speaker_names TEXT")
            conn.commit()
        if "input_language" not in existing_cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN input_language TEXT DEFAULT 'pt'")
            conn.commit()

        # is_admin column for users table
        user_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "is_admin" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
            conn.commit()
            # Auto-promote nycolas@gmail.com to admin
            conn.execute(
                "UPDATE users SET is_admin=1 WHERE email=?", ("nycolas@gmail.com",)
            )
            conn.commit()
        else:
            # Ensure nycolas@gmail.com is always admin (idempotent)
            conn.execute(
                "UPDATE users SET is_admin=1 WHERE email=?", ("nycolas@gmail.com",)
            )
            conn.commit()

    finally:
        conn.close()
