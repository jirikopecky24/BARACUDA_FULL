from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import math


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

    # Estimate standard error of fc using bootstrap-like approach
    # based on RMSE and number of data points
    # SE(fc) ≈ rmse * fc / (A * sqrt(n))
    # This is a heuristic approximation for the fitting uncertainty
    fc_se = float(rmse * fc / (abs(A) * math.sqrt(ff.size))) if A != 0 and ff.size > 0 else 0.0
    fc_se = min(fc_se, 0.2 * fc)  # Cap at 20% relative uncertainty

    return {
        "fc_hz": float(fc),
        "fc_hz_se": float(fc_se),
        "A": float(A),
        "B": float(B),
        "rmse": float(rmse),
        "n_used": int(ff.size),
        "fmin_hz": float(fmin_hz),
        "fmax_hz": float(fmax_hz),
    }

# ---------------- Calibration helpers (Brownian vs Dragging) ----------------

@dataclass(frozen=True)
class DragParams:
    stage_speed_um_s: float
    axis: str = "x"               # "x" | "y"
    viscosity_pa_s: float = 1.0e-3
    bead_radius_um: float = 0.5   # 1 µm diameter bead -> 0.5 µm radius


@dataclass(frozen=True)
class DragResult:
    drag_force_n: float
    offset_um: float
    kappa_n_per_m: float
    kappa_pn_per_um: float
    axis: str
    stage_speed_um_s: float
    viscosity_pa_s: float
    bead_radius_um: float


def stokes_gamma_n_s_per_m(viscosity_pa_s: float, bead_radius_um: float) -> float:
    """Gamma = 6π η R  [N·s/m]"""
    eta = float(viscosity_pa_s)
    r_m = float(bead_radius_um) * 1e-6
    if not np.isfinite(eta) or eta <= 0:
        raise ValueError("viscosity_pa_s must be > 0")
    if not np.isfinite(r_m) or r_m <= 0:
        raise ValueError("bead_radius_um must be > 0")
    return float(6.0 * math.pi * eta * r_m)


def kappa_from_fc_n_per_m(fc_hz: float, viscosity_pa_s: float, bead_radius_um: float) -> float:
    """kappa = 2π γ fc  [N/m]"""
    fc = float(fc_hz)
    if not np.isfinite(fc) or fc <= 0:
        raise ValueError("fc_hz must be > 0")
    gamma = stokes_gamma_n_s_per_m(viscosity_pa_s, bead_radius_um)
    return float(2.0 * math.pi * gamma * fc)


def compute_dragging_from_offset(offset_um: float, params: DragParams) -> DragResult:
    """Dragging stiffness from offset Δx under constant-velocity stage pulling.

    F_drag = 6π η R v
    kappa  = F_drag / Δx
    """
    axis = str(params.axis).lower().strip()
    if axis not in ("x", "y"):
        raise ValueError("DragParams.axis must be 'x' or 'y'")

    v_um_s = float(params.stage_speed_um_s)
    if not np.isfinite(v_um_s) or v_um_s <= 0:
        raise ValueError("stage_speed_um_s must be > 0")

    eta = float(params.viscosity_pa_s)
    r_um = float(params.bead_radius_um)
    if not np.isfinite(eta) or eta <= 0:
        raise ValueError("viscosity_pa_s must be > 0")
    if not np.isfinite(r_um) or r_um <= 0:
        raise ValueError("bead_radius_um must be > 0")

    off = float(offset_um)
    if not np.isfinite(off) or abs(off) < 1e-12:
        raise ValueError("offset_um is ~0; cannot estimate stiffness")

    v_m_s = v_um_s * 1e-6
    r_m = r_um * 1e-6

    f_drag = float(6.0 * math.pi * eta * r_m * v_m_s)  # N
    kappa = float(f_drag / (off * 1e-6))               # N/m (signed)
    kappa_abs = float(abs(kappa))

    return DragResult(
        drag_force_n=f_drag,
        offset_um=off,
        kappa_n_per_m=kappa,
        # N/m -> pN/µm: 1 N = 1e12 pN and 1 m = 1e6 µm => 1 N/m = 1e6 pN/µm
        kappa_pn_per_um=float(kappa_abs * 1e6),  # (N/m)->(pN/µm)
        axis=axis,
        stage_speed_um_s=v_um_s,
        viscosity_pa_s=eta,
        bead_radius_um=r_um,
    )


# ---------------- Fundamental constants ----------------
K_B = 1.380649e-23  # J/K


@dataclass(frozen=True)
class CalibrationParams:
    temperature_c: float = 25.0
    bead_diameter_um: float = 1.0  # default as requested
    viscosity_pa_s_override: float = 0.0  # if >0, use as provided instead of inferred


@dataclass(frozen=True)
class CalibrationResult:
    temperature_k: float
    bead_radius_um: float

    # Equipartition stiffness (per axis)
    kappa_x_n_per_m: float
    kappa_y_n_per_m: float
    kappa_x_pn_per_um: float
    kappa_y_pn_per_um: float
    kappa_iso_ratio: float  # kx/ky

    # Viscosity inferred from kappa + fc (per axis)
    eta_x_pa_s: float
    eta_y_pa_s: float
    eta_mean_pa_s: float

    # Diffusion from eta (mean)
    d_m2_s: float

    # Diagnostics
    var_x_um2: float
    var_y_um2: float
    fc_x_hz: float
    fc_y_hz: float
    n_used: int

    # Uncertainties (standard errors)
    kappa_x_pn_per_um_se: float = 0.0
    kappa_y_pn_per_um_se: float = 0.0
    eta_mean_pa_s_se: float = 0.0
    d_m2_s_se: float = 0.0
    fc_x_hz_se: float = 0.0
    fc_y_hz_se: float = 0.0


def _to_kappa_pn_per_um(kappa_n_per_m: float) -> float:
    """
    Convert stiffness from N/m to pN/µm.

    1 N = 1e12 pN
    1 m = 1e6 µm
    => 1 N/m = (1e12 / 1e6) pN/µm = 1e6 pN/µm
    """
    return float(abs(kappa_n_per_m) * 1e6)


def compute_calibration_from_equipartition_and_fc(
    x_um: np.ndarray,
    y_um: np.ndarray,
    fc_x_hz: float,
    fc_y_hz: float,
    params: CalibrationParams,
    fc_x_hz_se: float = 0.0,
    fc_y_hz_se: float = 0.0,
) -> CalibrationResult:
    """
    Returns: kappa_x, kappa_y from equipartition, and inferred viscosity eta from (kappa, fc).
    Requires:
      - x_um, y_um already drift-corrected (or at least centered)
      - bead diameter (for radius)
      - temperature
      - fc_x_hz_se, fc_y_hz_se: standard errors on corner frequencies (optional)
    """
    x = np.asarray(x_um, dtype=np.float64)
    y = np.asarray(y_um, dtype=np.float64)
    m = np.isfinite(x) & np.isfinite(y)
    x = x[m]
    y = y[m]
    n = x.size
    if n < 32:
        raise ValueError("not enough samples for calibration")

    T_k = float(params.temperature_c) + 273.15
    if not np.isfinite(T_k) or T_k <= 0:
        raise ValueError("temperature invalid")

    d_um = float(params.bead_diameter_um)
    if not np.isfinite(d_um) or d_um <= 0:
        raise ValueError("bead_diameter_um must be > 0")
    r_um = 0.5 * d_um
    r_m = r_um * 1e-6

    # variances (um^2)
    var_x = float(np.var(x, ddof=1))
    var_y = float(np.var(y, ddof=1))
    if var_x <= 0 or var_y <= 0:
        raise ValueError("variance <= 0 (check units, drift correction, or tracking)")

    # Standard error of variance: SE(var) = var * sqrt(2/(n-1))
    # This comes from chi-squared distribution of sample variance
    var_x_se = var_x * math.sqrt(2.0 / (n - 1)) if n > 1 else 0.0
    var_y_se = var_y * math.sqrt(2.0 / (n - 1)) if n > 1 else 0.0

    # equipartition: kappa = kBT / <x^2>
    kBT = K_B * T_k
    kappa_x = float(kBT / (var_x * 1e-12))  # um^2 -> m^2 via 1e-12
    kappa_y = float(kBT / (var_y * 1e-12))

    # Uncertainty in kappa: δkappa/kappa = δvar/var (error propagation for f=a/x)
    kappa_x_se = kappa_x * (var_x_se / var_x) if var_x > 0 else 0.0
    kappa_y_se = kappa_y * (var_y_se / var_y) if var_y > 0 else 0.0

    # viscosity from kappa + fc: eta = kappa / (12π^2 R fc)
    # derived from: fc = kappa / (2πγ), γ = 6π η R => eta = kappa / (12 π^2 R fc)
    fx = float(fc_x_hz)
    fy = float(fc_y_hz)
    fx_se = float(fc_x_hz_se) if fc_x_hz_se > 0 else 0.0
    fy_se = float(fc_y_hz_se) if fc_y_hz_se > 0 else 0.0
    if not np.isfinite(fx) or fx <= 0 or not np.isfinite(fy) or fy <= 0:
        raise ValueError("fc_x_hz/fc_y_hz must be > 0")

    denom_x = float(12.0 * (math.pi ** 2) * r_m * fx)
    denom_y = float(12.0 * (math.pi ** 2) * r_m * fy)
    eta_x = float(kappa_x / denom_x)
    eta_y = float(kappa_y / denom_y)

    # Uncertainty in eta: δeta/eta = sqrt((δkappa/kappa)^2 + (δfc/fc)^2)
    rel_err_kappa_x = kappa_x_se / kappa_x if kappa_x > 0 else 0.0
    rel_err_kappa_y = kappa_y_se / kappa_y if kappa_y > 0 else 0.0
    rel_err_fc_x = fx_se / fx if fx > 0 else 0.0
    rel_err_fc_y = fy_se / fy if fy > 0 else 0.0

    eta_x_se = eta_x * math.sqrt(rel_err_kappa_x**2 + rel_err_fc_x**2)
    eta_y_se = eta_y * math.sqrt(rel_err_kappa_y**2 + rel_err_fc_y**2)

    # if override viscosity provided, use it for D (but keep inferred for reporting)
    eta_mean = float(0.5 * (eta_x + eta_y))
    eta_mean_se = float(0.5 * math.sqrt(eta_x_se**2 + eta_y_se**2))
    eta_for_d = float(params.viscosity_pa_s_override) if float(params.viscosity_pa_s_override) > 0 else eta_mean

    # diffusion: D = kBT / (6π η R)
    d = float(kBT / (6.0 * math.pi * eta_for_d * r_m))

    # Uncertainty in D: δD/D = δη/η (since D ∝ 1/η)
    rel_err_eta = eta_mean_se / eta_mean if eta_mean > 0 else 0.0
    d_se = d * rel_err_eta

    return CalibrationResult(
        temperature_k=float(T_k),
        bead_radius_um=float(r_um),
        kappa_x_n_per_m=float(kappa_x),
        kappa_y_n_per_m=float(kappa_y),
        kappa_x_pn_per_um=_to_kappa_pn_per_um(kappa_x),
        kappa_y_pn_per_um=_to_kappa_pn_per_um(kappa_y),
        kappa_iso_ratio=float(kappa_x / kappa_y) if kappa_y != 0 else float("nan"),
        eta_x_pa_s=float(eta_x),
        eta_y_pa_s=float(eta_y),
        eta_mean_pa_s=float(eta_mean),
        d_m2_s=float(d),
        var_x_um2=float(var_x),
        var_y_um2=float(var_y),
        fc_x_hz=float(fx),
        fc_y_hz=float(fy),
        n_used=int(n),
        kappa_x_pn_per_um_se=_to_kappa_pn_per_um(kappa_x_se),
        kappa_y_pn_per_um_se=_to_kappa_pn_per_um(kappa_y_se),
        eta_mean_pa_s_se=float(eta_mean_se),
        d_m2_s_se=float(d_se),
        fc_x_hz_se=float(fx_se),
        fc_y_hz_se=float(fy_se),
    )

