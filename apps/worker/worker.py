import time
import threading
from typing import Callable, Dict, Optional

from core.interfaces.queue import JobQueue
from core.interfaces.repo import TranscriptionRepo
from core.services.transcriber import transcribe_with_progress
from infra.benchmark import BenchmarkContext
from apps.api import state as _state


class Worker(threading.Thread):
    """Background worker that dequeues and processes transcription jobs."""

    def __init__(
        self,
        queue: JobQueue,
        repo: TranscriptionRepo,
        progress_callbacks: Dict[str, Callable],
        user_repo=None,
        device: str = "cpu",
        gpu_limit: int = 70,
        name: str = "TranscriptionWorker",
        should_dequeue: Optional[Callable[[], bool]] = None,
    ):
        super().__init__(daemon=True, name=name)
        self.queue = queue
        self.repo = repo
        self.progress_callbacks = progress_callbacks
        self.user_repo = user_repo
        self.device = device
        self.gpu_limit = gpu_limit
        # Se fornecido, o worker só dequeua quando este callback retornar True.
        # Usado para workers CPU esperarem a GPU estar ocupada.
        self._should_dequeue = should_dequeue
        # Exposed for stuck-detection in the status endpoint
        self.current_job_id: Optional[str] = None

    def run(self) -> None:
        while True:
            try:
                if self._should_dequeue and not self._should_dequeue():
                    time.sleep(0.5)
                    continue
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

            # Capture before any DB mutation so we don't need a second get_job later
            user_id = job.get("user_id")
            duration = job.get("duration") or 0.0
            model = job.get("model")

            self.repo.mark_processing(job_id)

            def progress_cb(pct: int) -> None:
                self.repo.update_progress(job_id, pct)
                _state.progress_store[job_id] = pct
                cb = self.progress_callbacks.get(job_id)
                if cb:
                    try:
                        cb(pct)
                    except Exception:
                        pass

            input_language = job.get("input_language") or "pt"
            with BenchmarkContext(
                job_id=job_id,
                model=model,
                device=self.device,
                audio_duration=duration,
            ):
                result = transcribe_with_progress(
                    file_path=job["file_path"],
                    model_name=model,
                    device=self.device,
                    progress_cb=progress_cb,
                    language=None if input_language == "auto" else input_language,
                    gpu_limit=self.gpu_limit,
                )

            if result["success"] and job.get("diarize"):
                try:
                    from core.services.diarizer import diarize, merge_speaker_labels
                    print(f"[Worker] Diarizando {job_id}…")
                    d_segs = diarize(job["file_path"])
                    result["segments"] = merge_speaker_labels(result["segments"], d_segs)
                except Exception as e:
                    print(f"[Worker] Diarização falhou (continuando sem): {e}")

            if result["success"]:
                self.repo.mark_done(job_id, result)
                if self.user_repo and user_id and duration:
                    try:
                        self.user_repo.record_usage(user_id, job_id, duration / 60, model)
                    except Exception as e:
                        print(f"[Worker] Erro ao registrar uso para {job_id}: {e}")
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
            _state.progress_store.pop(job_id, None)
