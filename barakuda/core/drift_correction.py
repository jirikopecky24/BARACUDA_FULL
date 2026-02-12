from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DriftParams:
    """Drift correction parameters.

    If enabled, we estimate drift as a symmetric moving average over a window of
    `window_s` seconds (converted to frames using fps). NaN samples are ignored.

    The implementation is deterministic and does not depend on scipy.
    """

    enabled: bool = True
    window_s: float = 1.0


def _fill_nans_nearest(x: np.ndarray) -> np.ndarray:
    """Fill NaNs by nearest non-NaN neighbor (forward/backward pass).

    This keeps the result deterministic and avoids introducing sharp gaps.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return x

    out = x.copy()
    isn = np.isnan(out)
    if not np.any(isn):
        return out

    # forward fill
    last = np.nan
    for i in range(out.size):
        if np.isfinite(out[i]):
            last = out[i]
        else:
            out[i] = last

    # backward fill (for leading NaNs)
    last = np.nan
    for i in range(out.size - 1, -1, -1):
        if np.isfinite(out[i]):
            last = out[i]
        else:
            out[i] = last

    # if still NaN (all NaN input), replace with 0
    if np.any(np.isnan(out)):
        out = np.nan_to_num(out, nan=0.0)
    return out


def moving_average_nan(x: np.ndarray, window: int) -> np.ndarray:
    """Centered moving average ignoring NaNs.

    Returns an array of the same length. For positions where the window has no
    finite samples, the result is NaN.
    """
    x = np.asarray(x, dtype=np.float64)
    n = int(x.size)
    if n == 0:
        return x.copy()

    w = int(window)
    if w < 1:
        w = 1
    # enforce odd window for a clean center
    if w % 2 == 0:
        w += 1

    half = w // 2

    finite = np.isfinite(x)
    xf = np.where(finite, x, 0.0)
    wf = finite.astype(np.float64)

    # cumulative sums for O(n)
    csum = np.cumsum(xf)
    wsum = np.cumsum(wf)

    def segsum(a: np.ndarray, i0: int, i1: int) -> float:
        # inclusive indices i0..i1
        if i0 <= 0:
            return float(a[i1])
        return float(a[i1] - a[i0 - 1])

    out = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        i0 = max(0, i - half)
        i1 = min(n - 1, i + half)
        sw = segsum(wsum, i0, i1)
        if sw <= 0.0:
            out[i] = np.nan
        else:
            sx = segsum(csum, i0, i1)
            out[i] = sx / sw

    return out


def estimate_drift(
    x_px: np.ndarray,
    y_px: np.ndarray,
    fps: float,
    params: DriftParams,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (drift_x, drift_y, window_frames)."""
    x = np.asarray(x_px, dtype=np.float64)
    y = np.asarray(y_px, dtype=np.float64)

    if not bool(params.enabled):
        return np.zeros_like(x), np.zeros_like(y), 0

    fps = float(fps) if fps and float(fps) > 0 else 1.0
    win_frames = int(round(float(params.window_s) * fps))
    if win_frames < 1:
        win_frames = 1

    dx = moving_average_nan(x, win_frames)
    dy = moving_average_nan(y, win_frames)

    dx = _fill_nans_nearest(dx)
    dy = _fill_nans_nearest(dy)

    return dx, dy, win_frames


def apply_drift_correction(
    x_px: np.ndarray,
    y_px: np.ndarray,
    drift_x: np.ndarray,
    drift_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x_px, dtype=np.float64)
    y = np.asarray(y_px, dtype=np.float64)
    dx = np.asarray(drift_x, dtype=np.float64)
    dy = np.asarray(drift_y, dtype=np.float64)

    if x.shape != dx.shape or y.shape != dy.shape:
        raise ValueError("drift arrays must match x/y shape")

    return x - dx, y - dy
