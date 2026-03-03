from datetime import datetime
from typing import Optional

from core.interfaces.queue import JobQueue
from infra.db import get_connection


class SQLiteQueue(JobQueue):

    def enqueue(self, job_id: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO job_queue (job_id, created_at) VALUES (?, ?)",
                (job_id, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def next_job(self) -> Optional[str]:
        """Atomically dequeue the oldest job. Returns job_id or None."""
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, job_id FROM job_queue ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            conn.execute("DELETE FROM job_queue WHERE id = ?", (row["id"],))
            conn.commit()
            return row["job_id"]
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
