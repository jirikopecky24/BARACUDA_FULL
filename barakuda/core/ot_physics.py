from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class PsdParams:
    fs_hz: float
    nperseg: int = 1024
    noverlap: int = 512
    detrend: bool = True
    window: str = "hann"  # only "hann" supported


def _hann(n: int) -> np.ndarray:
    n = int(n)
    if n <= 1:
        return np.ones((max(n, 1),), dtype=np.float64)
    k = np.arange(n, dtype=np.float64)
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * k / (n - 1))


def compute_psd_welch(x: np.ndarray, params: PsdParams) -> tuple[np.ndarray, np.ndarray]:
    """
    Deterministic Welch PSD (no scipy).
    Returns: f_hz, Pxx [units^2/Hz]
    """
    x = np.asarray(x, dtype=np.float64)
    fs = float(params.fs_hz)
    if not np.isfinite(fs) or fs <= 0:
        raise ValueError("PSD requires fs_hz > 0")

    n = int(params.nperseg)
    if n < 8:
        raise ValueError("nperseg too small")

    no = int(params.noverlap)
    if no < 0 or no >= n:
        raise ValueError("noverlap must be in [0, nperseg)")

    step = n - no
    if x.size < n:
        raise ValueError("Signal shorter than nperseg")

    # window
    if params.window.lower() != "hann":
        raise ValueError("Only Hann window supported")
    w = _hann(n)
    w2 = np.sum(w * w)

    # segments (deterministic)
    starts = np.arange(0, x.size - n + 1, step, dtype=int)
    if starts.size == 0:
        raise ValueError("No segments for Welch")

    # FFT frequencies
    f = np.fft.rfftfreq(n, d=1.0 / fs)
    p_acc = np.zeros_like(f, dtype=np.float64)

    for s in starts:
        seg = x[s : s + n].astype(np.float64, copy=False)

        if params.detrend:
            seg = seg - np.mean(seg)

        seg = seg * w
        X = np.fft.rfft(seg)
        # periodogram scaling: (1/(fs * sum(w^2))) * |X|^2
        p = (np.abs(X) ** 2) / (fs * w2)
        p_acc += p

    pxx = p_acc / float(starts.size)
    return f, pxx


def compute_msd(x: np.ndarray, y: np.ndarray, dt_s: float, max_lag: int | None = None) -> dict[str, np.ndarray]:
    """
    MSD for x(t), y(t) (in px or um, caller decides).
    Returns dict with:
      lag, tau_s, msd_x, msd_y, msd_r
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.size != y.size:
        raise ValueError("x and y length mismatch")
    if x.size < 4:
        raise ValueError("trajectory too short for MSD")
    dt = float(dt_s)
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError("dt_s must be > 0")

    n = x.size
    Lmax = (n // 2) if max_lag is None else int(max_lag)
    Lmax = max(1, min(Lmax, n - 1))

    lag = np.arange(1, Lmax + 1, dtype=int)
    tau = lag.astype(np.float64) * dt

    msd_x = np.empty_like(tau)
    msd_y = np.empty_like(tau)
    msd_r = np.empty_like(tau)

    for i, L in enumerate(lag):
        dx = x[L:] - x[:-L]
        dy = y[L:] - y[:-L]
        msd_x[i] = float(np.mean(dx * dx))
        msd_y[i] = float(np.mean(dy * dy))
        msd_r[i] = float(np.mean(dx * dx + dy * dy))

    return {
        "lag": lag,
        "tau_s": tau,
        "msd_x": msd_x,
        "msd_y": msd_y,
        "msd_r": msd_r,
    }


def fit_lorentzian_psd(
    f_hz: np.ndarray,
    pxx: np.ndarray,
    fmin_hz: float = 1.0,
    fmax_hz: float | None = None,
) -> dict[str, Any]:
    """
    Deterministic Lorentzian PSD fit without scipy.

    Model: P(f) = A / (fc^2 + f^2) + B

    We do a grid search over fc (log-spaced), and for each fc solve (A,B) by least squares.
    Returns dict: fc_hz, A, B, rmse, n_used, fmin_hz, fmax_hz
    """
    f = np.asarray(f_hz, dtype=np.float64)
    p = np.asarray(pxx, dtype=np.float64)
    if f.size != p.size or f.size < 8:
        raise ValueError("PSD arrays too short")

    if fmax_hz is None:
        fmax_hz = float(np.max(f))

    fmin_hz = float(fmin_hz)
    fmax_hz = float(fmax_hz)
    if fmin_hz <= 0 or fmax_hz <= fmin_hz:
        raise ValueError("invalid fit band")

    mask = (f >= fmin_hz) & (f <= fmax_hz) & np.isfinite(p) & (p > 0)
    ff = f[mask]
    pp = p[mask]
    if ff.size < 8:
        raise ValueError("not enough PSD points in fit band")

    # fc search grid (deterministic)
    fc_min = max(0.1, float(np.min(ff)))
    fc_max = float(np.max(ff))
    # 60 points is usually enough and still fast
    fc_grid = np.logspace(np.log10(fc_min), np.log10(fc_max), 60)

    best = None

    # Precompute f^2
    f2 = ff * ff
    ones = np.ones_like(ff)

    for fc in fc_grid:
        denom = (fc * fc + f2)
        col1 = 1.0 / denom  # A coefficient
        # Solve [col1, 1] * [A, B] = P  (least squares)
        M = np.stack([col1, ones], axis=1)
        # deterministic lstsq
        sol, _, _, _ = np.linalg.lstsq(M, pp, rcond=None)
        A, B = float(sol[0]), float(sol[1])
        pred = A * col1 + B
        rmse = float(np.sqrt(np.mean((pred - pp) ** 2)))

        cand = (rmse, fc, A, B)
        if best is None or cand[0] < best[0]:
            best = cand

    assert best is not None
    rmse, fc, A, B = best
    return {
        "fc_hz": float(fc),
        "A": float(A),
        "B": float(B),
        "rmse": float(rmse),
        "n_used": int(ff.size),
        "fmin_hz": float(fmin_hz),
        "fmax_hz": float(fmax_hz),
    }
