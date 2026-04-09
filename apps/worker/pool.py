"""WorkerPool — gerencia workers GPU e CPU em paralelo."""
import torch
from typing import Callable, Dict

from core.interfaces.queue import JobQueue
from core.interfaces.repo import TranscriptionRepo
from apps.worker.worker import Worker


class WorkerPool:
    """
    GPU tem prioridade absoluta: o worker GPU sempre pega o próximo job.
    Workers CPU só entram quando a GPU já está ocupada (processando outro job),
    permitindo paralelismo real sem roubar trabalho da GPU quando ela está livre.

    Configuração via env:
      GPU_UTIL_LIMIT  — limite de utilização da GPU em % (padrão 70)
      CPU_WORKERS     — workers CPU de overflow (padrão 1)
    """

    def __init__(
        self,
        queue: JobQueue,
        repo: TranscriptionRepo,
        progress_callbacks: Dict[str, Callable],
        user_repo=None,
        gpu_util_limit: int = 70,
        cpu_workers: int = 1,
    ):
        self._gpu_worker: Worker | None = None
        self._cpu_worker_list: list[Worker] = []

        if torch.cuda.is_available():
            self._gpu_worker = Worker(
                queue=queue,
                repo=repo,
                progress_callbacks=progress_callbacks,
                user_repo=user_repo,
                device="cuda",
                gpu_limit=gpu_util_limit,
                name="Worker-GPU",
            )

        for i in range(cpu_workers):
            # Workers CPU só dequeiam quando a GPU já está ocupada.
            # Se não há GPU, dequeiam sempre (comportam-se como worker principal).
            gpu_ref = self._gpu_worker

            def _gpu_busy(w=gpu_ref) -> bool:
                return w is None or w.current_job_id is not None

            self._cpu_worker_list.append(
                Worker(
                    queue=queue,
                    repo=repo,
                    progress_callbacks=progress_callbacks,
                    user_repo=user_repo,
                    device="cpu",
                    gpu_limit=100,
                    name=f"Worker-CPU-{i + 1}",
                    should_dequeue=_gpu_busy,
                )
            )

        self._workers: list[Worker] = (
            ([self._gpu_worker] if self._gpu_worker else []) + self._cpu_worker_list
        )

        # Fallback: se CUDA indisponível e cpu_workers=0, garante ao menos 1 worker
        if not self._workers:
            self._workers.append(
                Worker(
                    queue=queue,
                    repo=repo,
                    progress_callbacks=progress_callbacks,
                    user_repo=user_repo,
                    device="cpu",
                    name="Worker-CPU-0",
                )
            )

    def start(self) -> None:
        for w in self._workers:
            w.start()
            print(f"[Pool] {w.name} iniciado ({w.device.upper()})")

    def is_processing(self, job_id: str) -> bool:
        """Retorna True se qualquer worker estiver processando este job."""
        return any(w.current_job_id == job_id for w in self._workers)

    @property
    def current_job_id(self) -> str | None:
        """Compatibilidade: retorna o primeiro job_id ativo encontrado."""
        for w in self._workers:
            if w.current_job_id:
                return w.current_job_id
        return None

    @property
    def workers(self) -> list[Worker]:
        return self._workers
