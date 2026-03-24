from __future__ import annotations

from typing import Any
import numpy as np


def resample_to_uniform_timebase(
    t_s: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
) -> dict[str, Any]:
    """
    Resample paired x/y signals onto a uniform time grid from measured timestamps.
    """
    t = np.asarray(t_s, dtype=np.float64)
    xv = np.asarray(x, dtype=np.float64)
    yv = np.asarray(y, dtype=np.float64)

    valid = np.isfinite(t) & np.isfinite(xv) & np.isfinite(yv)
    t = t[valid]
    xv = xv[valid]
    yv = yv[valid]
    if t.size < 4:
        raise ValueError("Not enough finite timestamped samples for resampling.")

    order = np.argsort(t)
    t = t[order]
    xv = xv[order]
    yv = yv[order]

    dt = np.diff(t)
    keep = np.concatenate([[True], dt > 0.0])
    t = t[keep]
    xv = xv[keep]
    yv = yv[keep]
    if t.size < 4:
        raise ValueError("Not enough strictly increasing timestamp samples.")

    dt = np.diff(t)
    if np.any(~np.isfinite(dt)) or np.any(dt <= 0):
        raise ValueError("Timestamps are invalid after cleaning.")

    dt_med = float(np.median(dt))
    fs_hz = float(1.0 / dt_med)
    t_uniform = np.arange(float(t[0]), float(t[-1]) + 0.5 * dt_med, dt_med, dtype=np.float64)
    if t_uniform.size < 4:
        raise ValueError("Uniform resampled signal too short.")

    xu = np.interp(t_uniform, t, xv)
    yu = np.interp(t_uniform, t, yv)

    return {
        "t_uniform_s": t_uniform,
        "x_uniform": xu,
        "y_uniform": yu,
        "fs_uniform_hz": fs_hz,
        "dt_stats": {
            "min_s": float(np.min(dt)),
            "max_s": float(np.max(dt)),
            "median_s": dt_med,
            "mean_s": float(np.mean(dt)),
            "std_s": float(np.std(dt)),
        },
        "n_in": int(len(t_s)),
        "n_valid": int(valid.sum()),
        "n_out": int(t_uniform.size),
    }
