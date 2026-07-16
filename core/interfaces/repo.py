from abc import ABC, abstractmethod
from typing import List, Optional  # noqa: F401


class TranscriptionRepo(ABC):
    @abstractmethod
    def create_job(self, data: dict) -> str: ...

    @abstractmethod
    def update_progress(self, job_id: str, pct: int) -> None: ...

    @abstractmethod
    def mark_processing(self, job_id: str) -> None: ...

    @abstractmethod
    def mark_done(self, job_id: str, result: dict) -> None: ...

    @abstractmethod
    def mark_error(self, job_id: str, error: str) -> None: ...

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[dict]: ...

    @abstractmethod
    def list_jobs(self, limit: int = 200, user_id: Optional[str] = None,
                  full: bool = False, offset: int = 0) -> List[dict]: ...

    @abstractmethod
    def count_jobs(self, user_id: Optional[str] = None) -> int: ...

    @abstractmethod
    def update_title(self, job_id: str, title: str) -> None: ...

    @abstractmethod
    def update_speaker_names(self, job_id: str, names: dict) -> None: ...

    @abstractmethod
    def delete_job(self, job_id: str) -> None: ...
