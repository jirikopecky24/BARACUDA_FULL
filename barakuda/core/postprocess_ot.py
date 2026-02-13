from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from barakuda.core.trajectory_csv_io import read_trajectory_csv, write_trajectory_csv_atomic
from barakuda.core.qc_flags import QcParams, compute_track_loss_flags
from barakuda.core.drift_correction import DriftParams, estimate_drift, apply_drift_correction
from barakuda.core.ot_physics import PsdParams, compute_msd, compute_psd_welch, fit_lorentzian_psd


@dataclass(frozen=True)
class PostprocessParams:
    """OT-3.1: postprocess settings (QC + drift).

    All settings are meant to be recorded into run.json (audit) and into
    trajectory.csv header lines.
    """

    qc_enabled: bool = True
    q_min: float = 0.0
    jump_max_px: float = 50.0

    drift_enabled: bool = True
    drift_window_s: float = 1.0

    export_um_columns: bool = True


def postprocess_trajectory_csv_inplace(
    trajectory_csv_path: Path,
    fps: float,
    um_per_px: float | None,
    params: PostprocessParams,
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> dict[str, Any]:
    """Enrich trajectory.csv in-place.

    Adds columns:
      - lost (0/1)
      - lost_reason
      - x_corr_px, y_corr_px
      - x_corr_um, y_corr_um (optional, if um_per_px provided)

    Returns a summary dict suitable for writing into run.json.
    """

    trajectory_csv_path = Path(trajectory_csv_path)
    table = read_trajectory_csv(trajectory_csv_path)

    # --- basic required columns ---
    required = ["frame", "t_s", "x_px", "y_px", "quality"]
    missing = [c for c in required if c not in table.header]
    if missing:
        raise ValueError(f"trajectory.csv missing columns: {missing}")

    def col(name: str) -> np.ndarray:
        return np.array([float(r.get(name, "nan")) for r in table.rows], dtype=np.float64)

    x = col("x_px")
    y = col("y_px")
    q = col("quality")

    # --- QC ---
    if bool(params.qc_enabled):
        lost, reason = compute_track_loss_flags(
            x, y, q,
            QcParams(q_min=float(params.q_min), jump_max_px=float(params.jump_max_px))
        )
    else:
        lost = np.zeros_like(x, dtype=bool)
        reason = np.full(x.shape[0], "", dtype="<U16")

    # Make drift ignore lost points
    x_for_drift = x.copy()
    y_for_drift = y.copy()
    x_for_drift[lost] = np.nan
    y_for_drift[lost] = np.nan

    # --- drift ---
    drift_params = DriftParams(enabled=bool(params.drift_enabled), window_s=float(params.drift_window_s))
    drift_x, drift_y, win_frames = estimate_drift(x_for_drift, y_for_drift, fps=float(fps), params=drift_params)
    x_corr, y_corr = apply_drift_correction(x, y, drift_x, drift_y)

    # --- update rows (preserve existing cols, append new ones if missing) ---
    new_cols: list[str] = []
    for name in ["lost", "lost_reason", "x_corr_px", "y_corr_px"]:
        if name not in table.header:
            new_cols.append(name)

    if params.export_um_columns and um_per_px is not None and float(um_per_px) > 0:
        for name in ["x_corr_um", "y_corr_um"]:
            if name not in table.header:
                new_cols.append(name)

    header = list(table.header) + new_cols

    um = None
    if params.export_um_columns and um_per_px is not None and float(um_per_px) > 0:
        um = float(um_per_px)

    for i, r in enumerate(table.rows):
        r["lost"] = "1" if bool(lost[i]) else "0"
        r["lost_reason"] = str(reason[i])
        r["x_corr_px"] = f"{float(x_corr[i]):.8g}"
        r["y_corr_px"] = f"{float(y_corr[i]):.8g}"
        if um is not None:
            r["x_corr_um"] = f"{float(x_corr[i] * um):.8g}"
            r["y_corr_um"] = f"{float(y_corr[i] * um):.8g}"

    # --- update metadata lines ---
    n = int(x.shape[0])
    lost_n = int(np.sum(lost))
    lost_frac = float(lost_n) / float(n) if n > 0 else 0.0

    meta = list(table.meta_lines)
    meta.append(f"# postprocess_ot3_qc_enabled={bool(params.qc_enabled)}")
    meta.append(f"# postprocess_ot3_q_min={float(params.q_min)}")
    meta.append(f"# postprocess_ot3_jump_max_px={float(params.jump_max_px)}")
    meta.append(f"# postprocess_ot3_drift_enabled={bool(params.drift_enabled)}")
    meta.append(f"# postprocess_ot3_drift_window_s={float(params.drift_window_s)}")
    meta.append(f"# postprocess_ot3_drift_window_frames={int(win_frames)}")
    meta.append(f"# postprocess_ot3_lost_frames={lost_n}")
    meta.append(f"# postprocess_ot3_lost_fraction={lost_frac:.6g}")

    write_trajectory_csv_atomic(trajectory_csv_path, meta, header, table.rows)

    summary: dict[str, Any] = {
        "qc": {
            "enabled": bool(params.qc_enabled),
            "q_min": float(params.q_min),
            "jump_max_px": float(params.jump_max_px),
            "lost_frames": lost_n,
            "lost_fraction": lost_frac,
        },
        "drift": {
            "enabled": bool(params.drift_enabled),
            "window_s": float(params.drift_window_s),
            "window_frames": int(win_frames),
        },
        "columns_added": new_cols,
        "um_per_px": (float(um_per_px) if um_per_px is not None else None),
    }

    # ---------------- Physics analysis (OT): MSD + PSD + Lorentz fit ----------------
    # Choose corrected columns if present
    x_use = col("x_corr_px") if "x_corr_px" in table.header else x
    y_use = col("y_corr_px") if "y_corr_px" in table.header else y
    t_use = col("t_s")

    # Apply analysis range in frames (defaults: full range)
    frames = np.array([int(float(r.get("frame", "0"))) for r in table.rows], dtype=int)
    sF = int(start_frame) if start_frame is not None else int(frames.min())
    eF = int(end_frame) if end_frame is not None else int(frames.max())
    if eF < sF:
        sF, eF = eF, sF

    mask_rng = (frames >= sF) & (frames <= eF) & np.isfinite(x_use) & np.isfinite(y_use) & np.isfinite(t_use)
    if int(np.sum(mask_rng)) < 16:
        # Not enough data for physics — skip but don't crash
        summary["physics"] = {"skipped": True, "reason": "too few samples after filtering"}
        return summary

    x_rng = x_use[mask_rng]
    y_rng = y_use[mask_rng]

    # dt from fps (deterministic)
    dt_s = 1.0 / float(fps)

    # MSD (px^2)
    msd = compute_msd(x_rng, y_rng, dt_s=dt_s, max_lag=None)

    # PSD (px^2/Hz) using Welch
    nperseg = 1024
    if x_rng.size < nperseg:
        nperseg = max(64, int(2 ** np.floor(np.log2(x_rng.size))))
    noverlap = int(nperseg // 2)

    psd_params = PsdParams(fs_hz=float(fps), nperseg=int(nperseg), noverlap=int(noverlap), detrend=True)
    f_x, pxx = compute_psd_welch(x_rng, psd_params)
    f_y, pyy = compute_psd_welch(y_rng, psd_params)

    # Lorentz fit (use a conservative band)
    fit_band_min = max(1.0, float(f_x[1]) if f_x.size > 1 else 1.0)
    fit_band_max = float(np.max(f_x))
    try:
        fit_x = fit_lorentzian_psd(f_x, pxx, fmin_hz=fit_band_min, fmax_hz=fit_band_max)
    except Exception:
        fit_x = {"error": "fit failed"}
    try:
        fit_y = fit_lorentzian_psd(f_y, pyy, fmin_hz=fit_band_min, fmax_hz=fit_band_max)
    except Exception:
        fit_y = {"error": "fit failed"}

    # Save outputs next to trajectory with strict naming
    base = trajectory_csv_path.name.replace("_trajectory.csv", "")
    out_dir = trajectory_csv_path.parent

    msd_path = out_dir / f"{base}_msd.csv"
    psd_x_path = out_dir / f"{base}_psd_x.csv"
    psd_y_path = out_dir / f"{base}_psd_y.csv"
    fit_path = out_dir / f"{base}_psd_fit.json"

    # CSV writing (with units in header names)
    msd_header = ["tau_s", "msd_x_px2", "msd_y_px2", "msd_r_px2"]
    msd_rows_out: list[dict[str, str]] = []
    for i in range(msd["tau_s"].size):
        row_d: dict[str, str] = {
            "tau_s": f"{msd['tau_s'][i]:.12g}",
            "msd_x_px2": f"{msd['msd_x'][i]:.12g}",
            "msd_y_px2": f"{msd['msd_y'][i]:.12g}",
            "msd_r_px2": f"{msd['msd_r'][i]:.12g}",
        }
        msd_rows_out.append(row_d)

    if um_per_px is not None and float(um_per_px) > 0:
        scale2 = float(um_per_px) ** 2
        msd_header += ["msd_x_um2", "msd_y_um2", "msd_r_um2"]
        for i in range(msd["tau_s"].size):
            msd_rows_out[i]["msd_x_um2"] = f"{(msd['msd_x'][i] * scale2):.12g}"
            msd_rows_out[i]["msd_y_um2"] = f"{(msd['msd_y'][i] * scale2):.12g}"
            msd_rows_out[i]["msd_r_um2"] = f"{(msd['msd_r'][i] * scale2):.12g}"

    def _write_psd_csv(path: Path, f_arr: np.ndarray, p_arr: np.ndarray) -> None:
        psd_header = ["f_hz", "psd_px2_per_hz"]
        psd_rows: list[dict[str, str]] = [{"f_hz": f"{f_arr[i]:.12g}", "psd_px2_per_hz": f"{p_arr[i]:.12g}"} for i in range(f_arr.size)]
        if um_per_px is not None and float(um_per_px) > 0:
            s2 = float(um_per_px) ** 2
            psd_header.append("psd_um2_per_hz")
            for i in range(f_arr.size):
                psd_rows[i]["psd_um2_per_hz"] = f"{(p_arr[i] * s2):.12g}"
        import csv as csv_mod
        with path.open("w", encoding="utf-8", newline="") as fobj:
            wr = csv_mod.DictWriter(fobj, fieldnames=psd_header)
            wr.writeheader()
            wr.writerows(psd_rows)

    import csv as csv_mod
    import json
    with msd_path.open("w", encoding="utf-8", newline="") as fobj:
        wr = csv_mod.DictWriter(fobj, fieldnames=msd_header)
        wr.writeheader()
        wr.writerows(msd_rows_out)

    _write_psd_csv(psd_x_path, f_x, pxx)
    _write_psd_csv(psd_y_path, f_y, pyy)

    fit_payload = {
        "range_frames": {"start_frame": int(sF), "end_frame": int(eF)},
        "psd_params": {
            "fs_hz": float(psd_params.fs_hz),
            "nperseg": int(psd_params.nperseg),
            "noverlap": int(psd_params.noverlap),
            "detrend": bool(psd_params.detrend),
            "window": str(psd_params.window),
        },
        "fit_x": fit_x,
        "fit_y": fit_y,
    }
    fit_path.write_text(json.dumps(fit_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # QC plot (single PNG): PSD (x+y+fits) + MSD
    qc_png = out_dir / f"{base}_qc.png"
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure(figsize=(10, 8))

        # PSD panel
        ax1 = fig.add_subplot(2, 1, 1)
        ax1.loglog(f_x[1:], pxx[1:], label="PSD X")
        ax1.loglog(f_y[1:], pyy[1:], label="PSD Y")

        # plot fits (only if fit succeeded)
        if "fc_hz" in fit_x and "fc_hz" in fit_y:
            fx = np.asarray(f_x, dtype=np.float64)

            def _lorentz_curve(f: np.ndarray, A: float, fc: float, B: float) -> np.ndarray:
                return (A / (fc * fc + f * f)) + B

            px_fit = _lorentz_curve(fx, float(fit_x["A"]), float(fit_x["fc_hz"]), float(fit_x["B"]))
            py_fit = _lorentz_curve(fx, float(fit_y["A"]), float(fit_y["fc_hz"]), float(fit_y["B"]))

            ax1.loglog(fx[1:], px_fit[1:], linestyle="--", label=f"Fit X (fc={fit_x['fc_hz']:.2f} Hz)")
            ax1.loglog(fx[1:], py_fit[1:], linestyle="--", label=f"Fit Y (fc={fit_y['fc_hz']:.2f} Hz)")

        ax1.set_xlabel("f [Hz]")
        ax1.set_ylabel("PSD [px^2/Hz]")
        ax1.set_title("PSD + Lorentzian fit")
        ax1.legend()

        # MSD panel
        ax2 = fig.add_subplot(2, 1, 2)
        ax2.loglog(msd["tau_s"], msd["msd_r"], label="MSD r (px^2)")
        ax2.set_xlabel("tau [s]")
        ax2.set_ylabel("MSD [px^2]")
        ax2.set_title("MSD")
        ax2.legend()

        fig.tight_layout()
        fig.savefig(qc_png, dpi=160)
        plt.close(fig)

    except Exception:
        # plotting must never fail the run
        pass

    summary["physics"] = {
        "range_frames": {"start_frame": int(sF), "end_frame": int(eF)},
        "msd_csv": msd_path.name,
        "psd_x_csv": psd_x_path.name,
        "psd_y_csv": psd_y_path.name,
        "psd_fit_json": fit_path.name,
        "qc_png": qc_png.name,
        "lorentz_fit": {"x": fit_x, "y": fit_y},
    }

    return summary
