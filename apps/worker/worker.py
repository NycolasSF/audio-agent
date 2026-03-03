import time
import threading
from typing import Callable, Dict, Optional

from core.interfaces.queue import JobQueue
from core.interfaces.repo import TranscriptionRepo
from core.services.transcriber import transcribe_with_progress
from infra.benchmark import BenchmarkContext


class Worker(threading.Thread):
    """Background worker that dequeues and processes transcription jobs."""

    def __init__(
        self,
        queue: JobQueue,
        repo: TranscriptionRepo,
        progress_callbacks: Dict[str, Callable],
    ):
        super().__init__(daemon=True, name="TranscriptionWorker")
        self.queue = queue
        self.repo = repo
        self.progress_callbacks = progress_callbacks
        # Exposed for stuck-detection in the status endpoint
        self.current_job_id: Optional[str] = None

    def run(self) -> None:
        while True:
            try:
                job_id = self.queue.next_job()
                if job_id is None:
                    time.sleep(0.5)
                    continue
                self._process(job_id)
            except Exception as e:
                print(f"[Worker] Erro inesperado no loop: {e}")
                time.sleep(1)

    def _process(self, job_id: str) -> None:
        self.current_job_id = job_id
        try:
            job = self.repo.get_job(job_id)
            if not job:
                print(f"[Worker] Job {job_id} não encontrado, descartando.")
                return

            self.repo.mark_processing(job_id)

            def progress_cb(pct: int) -> None:
                self.repo.update_progress(job_id, pct)
                cb = self.progress_callbacks.get(job_id)
                if cb:
                    try:
                        cb(pct)
                    except Exception:
                        pass

            with BenchmarkContext(
                job_id=job_id,
                model=job["model"],
                device=job["device"] or "cpu",
                audio_duration=job["duration"] or 0.0,
            ):
                result = transcribe_with_progress(
                    file_path=job["file_path"],
                    model_name=job["model"],
                    device=job["device"] or "cpu",
                    progress_cb=progress_cb,
                )

            if result["success"]:
                self.repo.mark_done(job_id, result)
            else:
                self.repo.mark_error(job_id, result.get("error", "Erro desconhecido"))

        except Exception as e:
            print(f"[Worker] Erro ao processar {job_id}: {e}")
            try:
                self.repo.mark_error(job_id, str(e))
            except Exception:
                pass
        finally:
            self.current_job_id = None
