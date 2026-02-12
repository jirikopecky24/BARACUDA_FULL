from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class DatasetItem:
    path: Path
    status: str = "idle"  # idle | queued | running | done | warn | failed
    note: Optional[str] = None

    @property
    def name(self) -> str:
        return self.path.name
