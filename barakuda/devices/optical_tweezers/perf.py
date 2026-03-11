from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
import os
import threading
import time

_LOCK = threading.Lock()
_STATS: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])


def enabled() -> bool:
    value = str(os.getenv("BARAKUDA_OT_PERF", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def add(tag: str, elapsed_s: float) -> None:
    if not enabled():
        return
    with _LOCK:
        stat = _STATS[str(tag)]
        stat[0] += 1.0
        stat[1] += float(max(0.0, elapsed_s))


@contextmanager
def record(tag: str):
    if not enabled():
        yield
        return
    t0 = time.perf_counter()
    try:
        yield
    finally:
        add(tag, time.perf_counter() - t0)


def snapshot(reset: bool = False) -> dict[str, dict[str, float]]:
    with _LOCK:
        out = {
            tag: {
                "count": int(values[0]),
                "total_ms": round(values[1] * 1000.0, 3),
                "avg_ms": round((values[1] * 1000.0 / values[0]), 3) if values[0] > 0 else 0.0,
            }
            for tag, values in _STATS.items()
            if values[0] > 0
        }
        if reset:
            _STATS.clear()
    return dict(sorted(out.items()))


def clear() -> None:
    with _LOCK:
        _STATS.clear()
