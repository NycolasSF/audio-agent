from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Job:
    id: str
    status: str  # pending | processing | done | error
    model: str
    timestamp: str
    title: str = ""
    source: str = ""
    file_path: Optional[str] = None
    device: Optional[str] = None
    duration: float = 0.0
    percent: int = 0
    text: Optional[str] = None
    language: Optional[str] = None
    segments: Optional[List[dict]] = None
    error: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        if isinstance(d.get("segments"), str):
            try:
                d["segments"] = json.loads(d["segments"])
            except Exception:
                d["segments"] = []
        return d
