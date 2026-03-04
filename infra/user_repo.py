import uuid
from datetime import datetime
from typing import List, Optional

from infra.db import get_connection


def _now() -> str:
    return datetime.now().isoformat()


class UserRepo:

    def create_user(self, email: str, password_hash: str, name: str = "") -> str:
        """Insert new user. Returns user_id. Raises ValueError on duplicate email."""
        user_id = uuid.uuid4().hex
        now = _now()
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO users (id, email, password_hash, name, is_active,
                                   quota_minutes, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (user_id, email.lower().strip(), password_hash, name,
                 _quota_default(), now, now),
            )
            conn.commit()
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                raise ValueError("Email já cadastrado")
            raise
        finally:
            conn.close()
        return user_id

    def get_by_email(self, email: str) -> Optional[dict]:
        """Return user dict including password_hash, or None."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_by_id(self, user_id: str) -> Optional[dict]:
        """Return user dict WITHOUT password_hash, or None."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, email, name, is_active, quota_minutes, created_at, updated_at "
                "FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_usage_total(self, user_id: str) -> float:
        """Return total transcribed minutes for the user (0.0 if none)."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT SUM(minutes) AS total FROM usage_minutes WHERE user_id=?",
                (user_id,),
            ).fetchone()
            return float(row["total"] or 0.0)
        finally:
            conn.close()

    def record_usage(self, user_id: str, job_id: str, minutes: float, model: str) -> None:
        """Insert a usage_minutes record."""
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO usage_minutes (user_id, job_id, minutes, model, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, job_id, round(minutes, 4), model, _now()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_usage_history(self, user_id: str, limit: int = 100) -> List[dict]:
        """Return recent usage records for the user."""
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT id, job_id, minutes, model, created_at "
                "FROM usage_minutes WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def _quota_default() -> float:
    from core import settings
    return settings.DEFAULT_QUOTA_MINUTES
