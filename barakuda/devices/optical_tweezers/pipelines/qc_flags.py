from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class QcParams:
    """Quality-control parameters for track-loss flagging.

    Conventions:
    - `q_min <= 0` disables the quality threshold.
    - `jump_max_px <= 0` disables the jump threshold.

    Reasons produced:
    - "nan": non-finite x/y/quality
    - "quality": quality < q_min
    - "jump": step size from last good point exceeds jump_max_px
    """

    q_min: float = 0.0
    jump_max_px: float = 50.0


def compute_track_loss_flags(
    x_px: np.ndarray,
    y_px: np.ndarray,
    quality: np.ndarray,
    params: QcParams,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (lost_bool, reason_str).

    Deterministic single-pass logic:
    1) Mark NaN/Inf as lost("nan")
    2) Mark low quality as lost("quality") if enabled
    3) Mark large jumps as lost("jump") if enabled, comparing to the last *good* point

    `reason_str` is a fixed-width numpy array of dtype '<U16'.
    """

    x = np.asarray(x_px, dtype=np.float64)
    y = np.asarray(y_px, dtype=np.float64)
    q = np.asarray(quality, dtype=np.float64)

    n = int(x.shape[0])
    if y.shape[0] != n or q.shape[0] != n:
        raise ValueError("x_px, y_px, quality must have the same length")

    lost = np.zeros(n, dtype=bool)
    reason = np.full(n, "", dtype="<U16")

    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(q)
    lost_nan = ~finite
    if np.any(lost_nan):
        lost[lost_nan] = True
        reason[lost_nan] = "nan"

    # Quality threshold
    if params.q_min is not None and float(params.q_min) > 0.0:
        lowq = finite & (q < float(params.q_min))
        if np.any(lowq):
            lost[lowq] = True
            reason[lowq] = "quality"

    # Jump threshold
    if params.jump_max_px is not None and float(params.jump_max_px) > 0.0:
        jmax = float(params.jump_max_px)
        last_good_i: int | None = None
        for i in range(n):
            if lost[i]:
                continue
            if last_good_i is None:
                last_good_i = i
                continue
            dx = float(x[i] - x[last_good_i])
            dy = float(y[i] - y[last_good_i])
            if (dx * dx + dy * dy) ** 0.5 > jmax:
                lost[i] = True
                reason[i] = "jump"
                # last_good_i stays unchanged (still last good)
            else:
                last_good_i = i

    return lost, reason
