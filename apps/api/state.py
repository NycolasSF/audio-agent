"""Shared application state: singletons instantiated once at startup."""
from typing import Callable, Dict

from core.services.recorder import AudioRecorder
from core.services.transcriber import get_device
from infra.repo_sqlite import SQLiteRepo
from infra.queue_sqlite import SQLiteQueue
from infra.user_repo import UserRepo
from apps.worker.worker import Worker

DEVICE: str = get_device()

repo = SQLiteRepo()
queue = SQLiteQueue()
user_repo = UserRepo()

# job_id → thread-safe callable(pct: int)
# Populated by ws/handler.py when a WebSocket client is waiting for a job.
progress_callbacks: Dict[str, Callable] = {}

worker = Worker(queue, repo, progress_callbacks, user_repo)

recorder = AudioRecorder()
