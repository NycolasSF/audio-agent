import json
from datetime import datetime
from typing import List, Optional

from core.interfaces.repo import TranscriptionRepo
from infra.db import get_connection


def _now() -> str:
    return datetime.now().isoformat()


def _row_to_dict(row) -> dict:
    d = dict(row)
    if isinstance(d.get("segments"), str):
        try:
            d["segments"] = json.loads(d["segments"])
        except Exception:
            d["segments"] = []
    if isinstance(d.get("speaker_names"), str):
        try:
            d["speaker_names"] = json.loads(d["speaker_names"])
        except Exception:
            d["speaker_names"] = {}
    return d


class SQLiteRepo(TranscriptionRepo):

    def create_job(self, data: dict) -> str:
        conn = get_connection()
        try:
            now = _now()
            conn.execute(
                """
                INSERT INTO jobs
                  (id, status, title, source, file_path, model, device,
                   timestamp, duration, percent, text, language, segments,
                   error, user_id, diarize, speaker_names, input_language, created_at, updated_at)
                VALUES
                  (:id, :status, :title, :source, :file_path, :model, :device,
                   :timestamp, :duration, :percent, :text, :language, :segments,
                   :error, :user_id, :diarize, :speaker_names, :input_language, :created_at, :updated_at)
                """,
                {
                    "id": data["id"],
                    "status": data.get("status", "pending"),
                    "title": data.get("title", ""),
                    "source": data.get("source", ""),
                    "file_path": data.get("file_path"),
                    "model": data["model"],
                    "device": data.get("device"),
                    "timestamp": data["timestamp"],
                    "duration": data.get("duration", 0.0),
                    "percent": data.get("percent", 0),
                    "text": data.get("text"),
                    "language": data.get("language"),
                    "segments": json.dumps(data["segments"]) if data.get("segments") is not None else None,
                    "error": data.get("error"),
                    "user_id": data.get("user_id"),
                    "diarize": int(data.get("diarize", 0)),
                    "speaker_names": None,
                    "input_language": data.get("input_language", "pt"),
                    "created_at": data.get("created_at", now),
                    "updated_at": now,
                },
            )
            conn.commit()
        finally:
            conn.close()
        return data["id"]

    def update_progress(self, job_id: str, pct: int) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE jobs SET percent=?, updated_at=? WHERE id=?",
                (pct, _now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_processing(self, job_id: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE jobs SET status='processing', percent=0, updated_at=? WHERE id=?",
                (_now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_done(self, job_id: str, result: dict) -> None:
        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE jobs
                SET status='done', percent=100, text=?, language=?,
                    segments=?, error=?, updated_at=?
                WHERE id=?
                """,
                (
                    result.get("text"),
                    result.get("language"),
                    json.dumps(result.get("segments", [])),
                    result.get("error"),
                    _now(),
                    job_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_error(self, job_id: str, error: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE jobs SET status='error', error=?, updated_at=? WHERE id=?",
                (error, _now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_job(self, job_id: str) -> Optional[dict]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    def get_job_owned_by(self, job_id: str, user_id: str) -> Optional[dict]:
        """Return job only if it belongs to user_id."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_jobs(self, limit: int = 1000, user_id: Optional[str] = None) -> List[dict]:
        conn = get_connection()
        try:
            if user_id:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def update_title(self, job_id: str, title: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE jobs SET title=?, updated_at=? WHERE id=?",
                (title, _now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_speaker_names(self, job_id: str, names: dict) -> None:
        """Merge *names* into the existing speaker_names JSON map for *job_id*."""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT speaker_names FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                return
            existing: dict = {}
            if row[0]:
                try:
                    existing = json.loads(row[0])
                except Exception:
                    pass
            existing.update(names)
            conn.execute(
                "UPDATE jobs SET speaker_names=?, updated_at=? WHERE id=?",
                (json.dumps(existing), _now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_job(self, job_id: str) -> None:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            conn.commit()
        finally:
            conn.close()
