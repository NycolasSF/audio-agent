"""Shared application state: singletons instantiated once at startup."""
from typing import Callable, Dict

from core.services.recorder import AudioRecorder
from core.services.transcriber import get_device
from core.settings import GPU_UTIL_LIMIT, CPU_WORKERS
from infra.repo_sqlite import SQLiteRepo
from infra.queue_sqlite import SQLiteQueue
from infra.user_repo import UserRepo
from apps.worker.pool import WorkerPool

DEVICE: str = get_device()

repo = SQLiteRepo()
queue = SQLiteQueue()
user_repo = UserRepo()

# job_id → thread-safe callable(pct: int)
# Populated by ws/handler.py when a WebSocket client is waiting for a job.
progress_callbacks: Dict[str, Callable] = {}

pool = WorkerPool(
    queue=queue,
    repo=repo,
    progress_callbacks=progress_callbacks,
    user_repo=user_repo,
    gpu_util_limit=GPU_UTIL_LIMIT,
    cpu_workers=CPU_WORKERS,
)

recorder = AudioRecorder()
