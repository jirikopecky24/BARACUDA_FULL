from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from barakuda.core.trajectory_csv_io import read_trajectory_csv, write_trajectory_csv_atomic
from barakuda.core.qc_flags import QcParams, compute_track_loss_flags
from barakuda.core.drift_correction import DriftParams, estimate_drift, apply_drift_correction
from barakuda.core.ot_physics import (
    PsdParams,
    compute_msd,
    compute_psd_welch,
    fit_lorentzian_psd,
    fit_lorentzian_psd,
    DragParams,
    CalibrationParams,
    compute_calibration_from_equipartition_and_fc,
)

# Consistent figure styling for all OT plots
FIGURE_SIZE = (7, 5)
FIGURE_SIZE_WIDE = (10, 8)
AXIS_LABEL_FONTSIZE = 11
TICK_LABEL_FONTSIZE = 9
TITLE_FONTSIZE = 12
PLOT_DPI = 300
PLOT_COLOR = "#1F6AA5"
GRID_COLOR = "#CAD5E0"
PANEL_BG = "#F8FBFD"


@dataclass(frozen=True)
class PostprocessParams:
    """OT-3.1: postprocess settings (QC + drift + physics).

    All settings are meant to be recorded into run.json (audit) and into
    trajectory.csv header lines.
    """

    # QC
    qc_enabled: bool = True
    q_min: float = 0.0
    jump_max_px: float = 50.0

    # Drift
    drift_enabled: bool = True
    drift_window_s: float = 1.0

    # Units
    export_um_columns: bool = True

    # Physics mode
    # - BROWNIAN: equilibrium fluctuations → MSD + PSD + Lorentz fit (default)
    # - DRAGGING: stage pulling calibration (constant v) + optional PSD/MSD on residuals
    physics_mode: str = "BROWNIAN"  # "BROWNIAN" | "DRAGGING"

    # Dragging parameters (used only when physics_mode == "DRAGGING")
    stage_speed_um_s: float = 0.0
    drag_axis: str = "x"  # "x" or "y"
    viscosity_pa_s: float = 1.0e-3
    bead_radius_um: float = 0.5
    temperature_c: float = 25.0
    bead_diameter_um: float = 1.0


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
    meta.append(f"# postprocess_ot3_physics_mode={str(params.physics_mode)}")
    meta.append(f"# postprocess_ot3_stage_speed_um_s={float(params.stage_speed_um_s)}")
    meta.append(f"# postprocess_ot3_drag_axis={str(params.drag_axis)}")
    meta.append(f"# postprocess_ot3_viscosity_pa_s={float(params.viscosity_pa_s)}")
    meta.append(f"# postprocess_ot3_bead_radius_um={float(params.bead_radius_um)}")
    meta.append(f"# postprocess_ot3_temperature_c={float(params.temperature_c)}")
    meta.append(f"# postprocess_ot3_bead_diameter_um={float(params.bead_diameter_um)}")
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

    # ---------------- Physics analysis (OT): two modes ----------------
    # Mode A) BROWNIAN (default): equilibrium fluctuations → MSD + PSD + Lorentz fit
    # Mode B) DRAGGING: stage pulling (constant v) → stiffness from Stokes drag + optional PSD/MSD on residuals

    physics_mode = str(params.physics_mode).upper().strip()

    # Choose corrected columns if present (px)
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
        summary["physics"] = {"skipped": True, "reason": "too few samples after filtering", "range_frames": {"start_frame": int(sF), "end_frame": int(eF)}}
        return summary

    x_rng = x_use[mask_rng]
    y_rng = y_use[mask_rng]
    t_rng = t_use[mask_rng]

    # dt from fps (deterministic)
    dt_s = 1.0 / float(fps)

    base = trajectory_csv_path.name.replace("_trajectory.csv", "")
    out_dir = trajectory_csv_path.parent

    # Helper: PSD + MSD + fits (shared)
    def _compute_brownian_physics(x_sig: np.ndarray, y_sig: np.ndarray) -> dict[str, Any]:
        # MSD (px^2)
        msd = compute_msd(x_sig, y_sig, dt_s=dt_s, max_lag=None)

        # PSD (px^2/Hz) using Welch
        nperseg = 1024
        if x_sig.size < nperseg:
            nperseg = max(64, int(2 ** np.floor(np.log2(x_sig.size))))
        noverlap = int(nperseg // 2)

        psd_params = PsdParams(fs_hz=float(fps), nperseg=int(nperseg), noverlap=int(noverlap), detrend=True)
        f_x, pxx = compute_psd_welch(x_sig, psd_params)
        f_y, pyy = compute_psd_welch(y_sig, psd_params)

        # Lorentz fit (conservative band)
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

        # Save outputs (strict naming)
        msd_path = out_dir / f"{base}_msd.csv"
        psd_x_path = out_dir / f"{base}_psd_x.csv"
        psd_y_path = out_dir / f"{base}_psd_y.csv"
        fit_path = out_dir / f"{base}_psd_fit.json"

        # MSD CSV
        msd_header = ["tau_s", "msd_x_px2", "msd_y_px2", "msd_r_px2"]
        msd_rows_out: list[dict[str, str]] = []
        for i in range(msd["tau_s"].size):
            msd_rows_out.append({
                "tau_s": f"{msd['tau_s'][i]:.12g}",
                "msd_x_px2": f"{msd['msd_x'][i]:.12g}",
                "msd_y_px2": f"{msd['msd_y'][i]:.12g}",
                "msd_r_px2": f"{msd['msd_r'][i]:.12g}",
            })

        if um_per_px is not None and float(um_per_px) > 0:
            scale2 = float(um_per_px) ** 2
            msd_header += ["msd_x_um2", "msd_y_um2", "msd_r_um2"]
            for i in range(msd["tau_s"].size):
                msd_rows_out[i]["msd_x_um2"] = f"{(msd['msd_x'][i] * scale2):.12g}"
                msd_rows_out[i]["msd_y_um2"] = f"{(msd['msd_y'][i] * scale2):.12g}"
                msd_rows_out[i]["msd_r_um2"] = f"{(msd['msd_r'][i] * scale2):.12g}"

        import csv as csv_mod
        with msd_path.open("w", encoding="utf-8", newline="") as fobj:
            wr = csv_mod.DictWriter(fobj, fieldnames=msd_header)
            wr.writeheader()
            wr.writerows(msd_rows_out)

        def _write_psd_csv(path: Path, f_arr: np.ndarray, p_arr: np.ndarray) -> None:
            psd_header = ["f_hz", "psd_px2_per_hz"]
            psd_rows: list[dict[str, str]] = [{"f_hz": f"{f_arr[i]:.12g}", "psd_px2_per_hz": f"{p_arr[i]:.12g}"} for i in range(f_arr.size)]
            if um_per_px is not None and float(um_per_px) > 0:
                s2 = float(um_per_px) ** 2
                psd_header.append("psd_um2_per_hz")
                for i in range(f_arr.size):
                    psd_rows[i]["psd_um2_per_hz"] = f"{(p_arr[i] * s2):.12g}"
            with path.open("w", encoding="utf-8", newline="") as fobj:
                wr = csv_mod.DictWriter(fobj, fieldnames=psd_header)
                wr.writeheader()
                wr.writerows(psd_rows)

        _write_psd_csv(psd_x_path, f_x, pxx)
        _write_psd_csv(psd_y_path, f_y, pyy)

        import json as json_mod
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
        fit_path.write_text(json_mod.dumps(fit_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        # ---- Calibration (kappa, eta, D) + histograms (from static/brownian segment) ----
        # Requires scale (um_per_px)
        if um_per_px is not None and float(um_per_px) > 0:
            # use corrected px if available, then convert to um
            x_um = x_rng * float(um_per_px)
            y_um = y_rng * float(um_per_px)

            # pull fc from fits (if fit succeeded)
            fc_x = float(fit_x.get("fc_hz", 0.0)) if isinstance(fit_x, dict) else 0.0
            fc_y = float(fit_y.get("fc_hz", 0.0)) if isinstance(fit_y, dict) else 0.0
            fc_x_se = float(fit_x.get("fc_hz_se", 0.0)) if isinstance(fit_x, dict) else 0.0
            fc_y_se = float(fit_y.get("fc_hz_se", 0.0)) if isinstance(fit_y, dict) else 0.0

            # Validation (UI/config)
            if not np.isfinite(params.bead_diameter_um) or float(params.bead_diameter_um) <= 0:
                raise ValueError("bead_diameter_um must be > 0 (UI/config)")

            if "_2um_" in base and abs(params.bead_diameter_um - 1.0) < 0.1:
                summary.setdefault("warnings", []).append(f"Filename '{base}' suggests 2um bead, but analysis uses 1um!")

            try:
                cal = compute_calibration_from_equipartition_and_fc(
                    x_um=x_um,
                    y_um=y_um,
                    fc_x_hz=fc_x,
                    fc_y_hz=fc_y,
                    params=CalibrationParams(
                        temperature_c=float(params.temperature_c),
                        bead_diameter_um=float(params.bead_diameter_um),
                        viscosity_pa_s_override=0.0,
                    ),
                    fc_x_hz_se=fc_x_se,
                    fc_y_hz_se=fc_y_se,
                )

                fc_ratio = cal.fc_x_hz / cal.fc_y_hz if cal.fc_y_hz > 0 else float("nan")
                anisotropy_pass = bool(0.5 <= fc_ratio <= 2.0)

                eta_primary = cal.eta_mean_pa_s
                eta_primary_axis = "mean"
                if not anisotropy_pass:
                    # pick the axis with higher fc (usually less polluted by drift)
                    if cal.fc_y_hz >= cal.fc_x_hz:
                        eta_primary = cal.eta_y_pa_s
                        eta_primary_axis = "y"
                    else:
                        eta_primary = cal.eta_x_pa_s
                        eta_primary_axis = "x"

                import json as _json
                cal_json = out_dir / f"{base}_calibration.json"
                cal_csv = out_dir / f"{base}_calibration.csv"

                payload = {
                    "range_frames": {"start_frame": int(sF), "end_frame": int(eF)},
                    "temperature_c": float(params.temperature_c),
                    "temperature_k": cal.temperature_k,
                    "bead_diameter_um": float(params.bead_diameter_um),
                    "bead_radius_um": cal.bead_radius_um,
                    "anisotropy": {
                        "fc_ratio_x_over_y": fc_ratio,
                        "pass": anisotropy_pass,
                        "eta_primary_pa_s": eta_primary,
                        "eta_primary_axis": eta_primary_axis,
                    },
                    "kappa": {
                        "kappa_x_n_per_m": cal.kappa_x_n_per_m,
                        "kappa_y_n_per_m": cal.kappa_y_n_per_m,
                        "kappa_x_pn_per_um": cal.kappa_x_pn_per_um,
                        "kappa_y_pn_per_um": cal.kappa_y_pn_per_um,
                        "kappa_x_pn_per_um_se": cal.kappa_x_pn_per_um_se,
                        "kappa_y_pn_per_um_se": cal.kappa_y_pn_per_um_se,
                        "kappa_iso_ratio": cal.kappa_iso_ratio,
                    },
                    "viscosity": {
                        "eta_x_pa_s": cal.eta_x_pa_s,
                        "eta_y_pa_s": cal.eta_y_pa_s,
                        "eta_mean_pa_s": cal.eta_mean_pa_s,
                        "eta_mean_pa_s_se": cal.eta_mean_pa_s_se,
                    },
                    "diffusion": {
                        "D_m2_s": cal.d_m2_s,
                        "D_m2_s_se": cal.d_m2_s_se,
                    },
                    "diagnostics": {
                        "var_x_um2": cal.var_x_um2,
                        "var_y_um2": cal.var_y_um2,
                        "fc_x_hz": cal.fc_x_hz,
                        "fc_y_hz": cal.fc_y_hz,
                        "fc_x_hz_se": cal.fc_x_hz_se,
                        "fc_y_hz_se": cal.fc_y_hz_se,
                        "n_used": cal.n_used,
                    },
                    "kappa_unit_check": {
                        "expected_x_pn_per_um": float(cal.kappa_x_n_per_m * 1e6),
                        "expected_y_pn_per_um": float(cal.kappa_y_n_per_m * 1e6),
                        "actual_x_pn_per_um": float(cal.kappa_x_pn_per_um),
                        "actual_y_pn_per_um": float(cal.kappa_y_pn_per_um),
                        "pass": bool(
                            abs(cal.kappa_x_pn_per_um - cal.kappa_x_n_per_m * 1e6) <= 1e-6
                            and abs(cal.kappa_y_pn_per_um - cal.kappa_y_n_per_m * 1e6) <= 1e-6
                        ),
                    },
                }
                cal_json.write_text(_json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

                import csv as _csv
                with cal_csv.open("w", encoding="utf-8", newline="") as f:
                    w = _csv.writer(f)
                    w.writerow(["metric", "value", "uncertainty"])
                    w.writerow(["temperature_C", f"{float(params.temperature_c):.12g}", ""])
                    w.writerow(["bead_diameter_um", f"{float(params.bead_diameter_um):.12g}", ""])
                    w.writerow(["kappa_x_n_per_m", f"{cal.kappa_x_n_per_m:.12g}", ""])
                    w.writerow(["kappa_y_n_per_m", f"{cal.kappa_y_n_per_m:.12g}", ""])
                    w.writerow(["kappa_x_pn_per_um", f"{cal.kappa_x_pn_per_um:.12g}", f"{cal.kappa_x_pn_per_um_se:.12g}"])
                    w.writerow(["kappa_y_pn_per_um", f"{cal.kappa_y_pn_per_um:.12g}", f"{cal.kappa_y_pn_per_um_se:.12g}"])
                    w.writerow(["kappa_iso_ratio", f"{cal.kappa_iso_ratio:.12g}", ""])
                    w.writerow(["eta_x_pa_s", f"{cal.eta_x_pa_s:.12g}", ""])
                    w.writerow(["eta_y_pa_s", f"{cal.eta_y_pa_s:.12g}", ""])
                    w.writerow(["eta_mean_pa_s", f"{cal.eta_mean_pa_s:.12g}", f"{cal.eta_mean_pa_s_se:.12g}"])
                    w.writerow(["D_m2_s", f"{cal.d_m2_s:.12g}", f"{cal.d_m2_s_se:.12g}"])
                    w.writerow(["fc_x_hz", f"{cal.fc_x_hz:.12g}", f"{cal.fc_x_hz_se:.12g}"])
                    w.writerow(["fc_y_hz", f"{cal.fc_y_hz:.12g}", f"{cal.fc_y_hz_se:.12g}"])

                # Histograms: x,y,r in um (simple deterministic bins)
                def _write_hist(csv_path: Path, png_path: Path, data_um: np.ndarray, title: str) -> None:
                    data_um = np.asarray(data_um, dtype=np.float64)
                    data_um = data_um[np.isfinite(data_um)]
                    if data_um.size < 16:
                        return

                    # deterministic bins: 100 bins in [p0.5, p99.5]
                    lo = float(np.percentile(data_um, 0.5))
                    hi = float(np.percentile(data_um, 99.5))
                    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
                        return

                    bins = 100
                    hist, edges = np.histogram(data_um, bins=bins, range=(lo, hi))
                    centers = 0.5 * (edges[:-1] + edges[1:])

                    # --- CSV ---
                    import csv as _csv
                    with csv_path.open("w", encoding="utf-8", newline="") as f:
                        w = _csv.writer(f)
                        w.writerow(["bin_center_um", "count"])
                        for c, h in zip(centers, hist):
                            w.writerow([f"{float(c):.12g}", str(int(h))])

                    # --- PNG + SVG ---
                    try:
                        import matplotlib
                        matplotlib.use("Agg")
                        import matplotlib.pyplot as plt

                        fig = plt.figure(figsize=FIGURE_SIZE)
                        ax = fig.add_subplot(1, 1, 1)
                        ax.set_facecolor(PANEL_BG)
                        ax.plot(centers, hist, color=PLOT_COLOR, linewidth=1.5)
                        ax.set_xlabel("position [µm]", fontsize=AXIS_LABEL_FONTSIZE)
                        ax.set_ylabel("count", fontsize=AXIS_LABEL_FONTSIZE)
                        ax.set_title(title, fontsize=TITLE_FONTSIZE, fontweight="bold")
                        ax.tick_params(labelsize=TICK_LABEL_FONTSIZE)
                        ax.grid(True, linestyle="--", linewidth=0.5, color=GRID_COLOR)
                        fig.tight_layout()
                        fig.savefig(png_path, dpi=PLOT_DPI)
                        svg_path = png_path.with_suffix(".svg")
                        fig.savefig(svg_path, format="svg")
                        plt.close(fig)
                    except Exception:
                        pass

                hx = out_dir / f"{base}_hist_x.csv"
                hy = out_dir / f"{base}_hist_y.csv"
                hr = out_dir / f"{base}_hist_r.csv"

                hx_png = out_dir / f"{base}_hist_x.png"
                hy_png = out_dir / f"{base}_hist_y.png"
                hr_png = out_dir / f"{base}_hist_r.png"

                _write_hist(hx, hx_png, x_um, "Histogram X")
                _write_hist(hy, hy_png, y_um, "Histogram Y")
                _write_hist(hr, hr_png, np.sqrt(x_um * x_um + y_um * y_um), "Histogram R")

                summary.setdefault("calibration", {})
                summary["calibration"] = {
                    "calibration_json": cal_json.name,
                    "calibration_csv": cal_csv.name,
                    "hist_x_csv": hx.name,
                    "hist_y_csv": hy.name,
                    "hist_r_csv": hr.name,
                }
            except Exception as e:
                summary.setdefault("calibration", {})
                summary["calibration"] = {"skipped": True, "reason": repr(e)}

        # QC plot (single PNG + SVG): PSD (x+y+fits) + MSD
        qc_png = out_dir / f"{base}_qc.png"
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig = plt.figure(figsize=FIGURE_SIZE_WIDE)

            ax1 = fig.add_subplot(2, 1, 1)
            ax1.set_facecolor(PANEL_BG)
            ax1.loglog(f_x[1:], pxx[1:], label="PSD X", color=PLOT_COLOR, linewidth=1.5)
            ax1.loglog(f_y[1:], pyy[1:], label="PSD Y", color="#E57373", linewidth=1.5)

            if "fc_hz" in fit_x and "fc_hz" in fit_y:
                fx = np.asarray(f_x, dtype=np.float64)

                def _lorentz_curve(f: np.ndarray, A: float, fc: float, B: float) -> np.ndarray:
                    return (A / (fc * fc + f * f)) + B

                px_fit = _lorentz_curve(fx, float(fit_x["A"]), float(fit_x["fc_hz"]), float(fit_x["B"]))
                py_fit = _lorentz_curve(fx, float(fit_y["A"]), float(fit_y["fc_hz"]), float(fit_y["B"]))

                ax1.loglog(fx[1:], px_fit[1:], linestyle="--", label=f"Fit X (fc={fit_x['fc_hz']:.2f} Hz)", color=PLOT_COLOR)
                ax1.loglog(fx[1:], py_fit[1:], linestyle="--", label=f"Fit Y (fc={fit_y['fc_hz']:.2f} Hz)", color="#E57373")

            ax1.set_xlabel("f [Hz]", fontsize=AXIS_LABEL_FONTSIZE)
            ax1.set_ylabel("PSD [px²/Hz]", fontsize=AXIS_LABEL_FONTSIZE)
            ax1.set_title("PSD + Lorentzian fit", fontsize=TITLE_FONTSIZE, fontweight="bold")
            ax1.tick_params(labelsize=TICK_LABEL_FONTSIZE)
            ax1.grid(True, which="both", linestyle="--", linewidth=0.5, color=GRID_COLOR)
            ax1.legend(fontsize=TICK_LABEL_FONTSIZE)

            ax2 = fig.add_subplot(2, 1, 2)
            ax2.set_facecolor(PANEL_BG)
            ax2.loglog(msd["tau_s"], msd["msd_r"], label="MSD r (px²)", color=PLOT_COLOR, linewidth=1.5)
            ax2.set_xlabel("τ [s]", fontsize=AXIS_LABEL_FONTSIZE)
            ax2.set_ylabel("MSD [px²]", fontsize=AXIS_LABEL_FONTSIZE)
            ax2.set_title("MSD", fontsize=TITLE_FONTSIZE, fontweight="bold")
            ax2.tick_params(labelsize=TICK_LABEL_FONTSIZE)
            ax2.grid(True, which="both", linestyle="--", linewidth=0.5, color=GRID_COLOR)
            ax2.legend(fontsize=TICK_LABEL_FONTSIZE)

            fig.tight_layout()
            fig.savefig(qc_png, dpi=PLOT_DPI)
            qc_svg = qc_png.with_suffix(".svg")
            fig.savefig(qc_svg, format="svg")
            plt.close(fig)
        except Exception:
            pass

        return {
            "range_frames": {"start_frame": int(sF), "end_frame": int(eF)},
            "msd_csv": msd_path.name,
            "psd_x_csv": psd_x_path.name,
            "psd_y_csv": psd_y_path.name,
            "psd_fit_json": fit_path.name,
            "qc_png": qc_png.name,
            "lorentz_fit": {"x": fit_x, "y": fit_y},
        }

    if physics_mode == "DRAGGING":
        # Handled in batch_controller (2-video comparison)
        summary["physics"] = {"mode": "DRAGGING", "note": "Computed in batch comparison"}
        return summary

    # Default: BROWNIAN
    summary["physics"] = {"mode": "BROWNIAN"} | _compute_brownian_physics(x_rng, y_rng)
    return summary


def render_tracking_preview(
    video_path: Path,
    trajectory_csv_path: Path,
    output_path: Path,
    frame_idx: int = 10,
    um_per_px: float | None = None,
) -> Path | None:
    """
    Generate tracking preview image showing a video frame with tracked position overlay.

    Args:
        video_path: Path to the video file (.raw, .avi, etc.)
        trajectory_csv_path: Path to the trajectory CSV with x_px, y_px columns
        output_path: Path where to save the preview image (PNG)
        frame_idx: Which frame to show (default: 10)
        um_per_px: Scale for scalebar (µm per pixel), if None scalebar uses pixels

    Returns:
        Path to the saved image, or None if generation failed
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle
        from matplotlib_scalebar.scalebar import ScaleBar

        from barakuda.core.video_reader import VideoReader
        from barakuda.core.trajectory_csv_io import read_trajectory_csv

        video_path = Path(video_path)
        trajectory_csv_path = Path(trajectory_csv_path)
        output_path = Path(output_path)

        if not video_path.is_file() or not trajectory_csv_path.is_file():
            return None

        reader = VideoReader(video_path)
        frame = reader.get_frame(frame_idx)
        reader.close()

        table = read_trajectory_csv(trajectory_csv_path)
        if frame_idx >= len(table.rows):
            frame_idx = len(table.rows) - 1
        row = table.rows[frame_idx]

        x_px = float(row.get("x_px", 0))
        y_px = float(row.get("y_px", 0))

        fig = plt.figure(figsize=FIGURE_SIZE)
        ax = fig.add_subplot(1, 1, 1)

        # Show frame (grayscale or RGB)
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            ax.imshow(frame)
        else:
            ax.imshow(frame, cmap="gray")

        # Overlay tracked position
        circle = Circle((x_px, y_px), radius=8, fill=False, color="red", linewidth=2)
        ax.add_patch(circle)
        ax.plot(x_px, y_px, "r+", markersize=10, markeredgewidth=2)

        # Add scalebar
        if um_per_px is not None and um_per_px > 0:
            scalebar = ScaleBar(
                um_per_px, "µm",
                location="lower right",
                color="white",
                box_color="black",
                box_alpha=0.6,
                font_properties={"size": 10},
            )
        else:
            scalebar = ScaleBar(
                1, "px",
                location="lower right",
                color="white",
                box_color="black",
                box_alpha=0.6,
                font_properties={"size": 10},
            )
        ax.add_artist(scalebar)

        ax.set_title(f"Tracking Preview (frame {frame_idx})", fontsize=TITLE_FONTSIZE, fontweight="bold")
        ax.axis("off")
        fig.tight_layout()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=PLOT_DPI, bbox_inches="tight")
        svg_path = output_path.with_suffix(".svg")
        fig.savefig(svg_path, format="svg", bbox_inches="tight")
        plt.close(fig)

        return output_path

    except Exception:
        return None


def render_random_tracking_previews(
    video_path: Path,
    trajectory_csv_path: Path,
    raw_dir: Path,
    *,
    um_per_px: float | None = None,
    n_frames: int = 10,
) -> None:
    """
    Generate multiple tracking preview images at random frames across the run.

    Images are saved into the item's raw directory as video_preview_01.png, ..., up to n_frames.
    """
    from barakuda.core.trajectory_csv_io import read_trajectory_csv

    try:
        video_path = Path(video_path)
        trajectory_csv_path = Path(trajectory_csv_path)
        raw_dir = Path(raw_dir)
        if not video_path.is_file() or not trajectory_csv_path.is_file():
            return

        table = read_trajectory_csv(trajectory_csv_path)
        n_rows = len(table.rows)
        if n_rows <= 0:
            return

        n = min(max(1, int(n_frames)), n_rows)
        if n_rows <= n:
            indices = np.arange(n_rows, dtype=int)
        else:
            indices = np.random.choice(n_rows, size=n, replace=False)
        indices = sorted(int(i) for i in indices)

        raw_dir.mkdir(parents=True, exist_ok=True)

        written = 0
        for idx, frame_idx in enumerate(indices, start=1):
            if idx > n_frames:
                break
            output_path = raw_dir / f"video_preview_{idx:02d}.png"
            try:
                result = render_tracking_preview(
                    video_path=video_path,
                    trajectory_csv_path=trajectory_csv_path,
                    output_path=output_path,
                    frame_idx=int(frame_idx),
                    um_per_px=um_per_px,
                )
                if result is not None and output_path.is_file():
                    written += 1
            except Exception:
                continue
    except Exception:
        return None
