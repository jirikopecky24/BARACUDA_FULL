from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from barakuda.core.trajectory_csv_io import read_trajectory_csv, write_trajectory_csv_atomic
from barakuda.core.qc_flags import QcParams, compute_track_loss_flags
from barakuda.core.drift_correction import DriftParams, estimate_drift, apply_drift_correction


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
    return summary
