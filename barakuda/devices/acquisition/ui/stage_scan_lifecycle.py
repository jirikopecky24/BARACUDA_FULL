from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class StageScanToken:
    generation: int
    request_id: int


class StageScanLifecycleGuard:
    """Thread-safe lifecycle guard for async stage scan results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._latest_request_id = 0
        self._closing = False

    def start_request(self) -> StageScanToken | None:
        with self._lock:
            if self._closing:
                return None
            self._latest_request_id += 1
            return StageScanToken(
                generation=self._generation,
                request_id=self._latest_request_id,
            )

    def cancel_all(self) -> None:
        with self._lock:
            self._closing = True
            self._generation += 1

    def should_publish(self, token: StageScanToken) -> tuple[bool, str]:
        with self._lock:
            if self._closing:
                return False, "panel_closing"
            if token.generation != self._generation:
                return False, "generation_mismatch"
            if token.request_id != self._latest_request_id:
                return False, "stale_request"
            return True, "accepted"

