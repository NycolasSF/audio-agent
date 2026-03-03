import sqlite3
from contextlib import contextmanager
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
    """Create all tables if they don't exist."""
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
        """)
        conn.commit()
    finally:
        conn.close()
