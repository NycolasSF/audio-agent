from abc import ABC, abstractmethod
from typing import Optional


class JobQueue(ABC):
    @abstractmethod
    def enqueue(self, job_id: str) -> None: ...

    @abstractmethod
    def next_job(self) -> Optional[str]:
        """Return next job_id or None if queue is empty."""
        ...
