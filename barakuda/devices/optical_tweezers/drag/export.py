from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .schema import DragAnalysisResult, DragQCFlags, iter_qc_flags


def _qc_flags_dict(flags: DragQCFlags) -> dict[str, bool]:
    return {name: value for name, value in iter_qc_flags(flags)}


def drag_result_to_dict(result: DragAnalysisResult) -> dict[str, Any]:
    """Convert DragAnalysisResult to a flat dict suitable for JSON/CSV."""
    d: dict[str, Any] = {
        "basename": result.basename,
        "axis": result.axis,
        "motion_start_stage_s": result.motion_start_stage_s,
        "motion_stop_stage_s": result.motion_stop_stage_s,
        "motion_start_video_s_detected": result.motion_start_video_s_detected,
        "motion_stop_video_s_stage_aligned": result.motion_stop_video_s_stage_aligned,
        "alignment_offset_s": result.alignment_offset_s,
        "baseline_start_s": result.windows.baseline_start_s,
        "baseline_end_s": result.windows.baseline_end_s,
        "steady_start_s": result.windows.steady_start_s,
        "steady_end_s": result.windows.steady_end_s,
        "baseline_position_px": result.baseline_position_px,
        "baseline_position_um": result.baseline_position_um,
        "steady_position_px": result.steady_position_px,
        "steady_position_um": result.steady_position_um,
        "offset_px_raw": result.offset_px_raw,
        "offset_um_raw": result.offset_um_raw,
        "offset_px_stage_signed": result.offset_px_stage_signed,
        "offset_um_stage_signed": result.offset_um_stage_signed,
        "abs_offset_um": result.abs_offset_um,
        "actual_travel_user": result.actual_travel_user,
        "actual_motion_duration_s": result.actual_motion_duration_s,
        "actual_speed_user_s": result.actual_speed_user_s,
        "actual_travel_um": result.actual_travel_um,
        "actual_speed_um_s": result.actual_speed_um_s,
        "drag_force_n": result.drag_force_n,
        "kappa_n_per_m": result.kappa_n_per_m,
        "kappa_pn_per_um": result.kappa_pn_per_um,
        "eta_pa_s": result.eta_pa_s,
        "analysis_status": result.analysis_status,
        "alignment_status": result.alignment_status,
        "physics_status": result.physics_status,
        "warnings": list(result.warnings),
        "notes": list(result.notes),
    }
    for name, value in iter_qc_flags(result.qc_flags):
        d[f"qc_{name}"] = value
    return d


def export_drag_summary_json(result: DragAnalysisResult, output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.basename}_drag_summary.json"
    payload = drag_result_to_dict(result)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def export_drag_summary_csv(result: DragAnalysisResult, output_dir: Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.basename}_drag_summary.csv"
    payload = drag_result_to_dict(result)
    fieldnames = list(payload.keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerow(payload)
    return path

