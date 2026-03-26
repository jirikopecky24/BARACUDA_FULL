from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .schema import DragAnalysisResult, DragQCFlags, iter_qc_flags, AlignmentDiagnostics


def _qc_flags_dict(flags: DragQCFlags) -> dict[str, bool]:
    return {name: value for name, value in iter_qc_flags(flags)}


def drag_result_to_dict(result: DragAnalysisResult) -> dict[str, Any]:
    """Convert DragAnalysisResult to a flat dict suitable for JSON/CSV."""
    d: dict[str, Any] = {
        "basename": result.basename,
        "axis": result.axis,
        "protocol_type": result.protocol_type,
        "analysis_axis": result.analysis_axis,
        "stage_axis": result.stage_axis,
        # Provenance / auditability
        "um_per_px_source": result.um_per_px_source,
        "stage_um_per_unit_source": result.stage_um_per_unit_source,
        "motion_kinematics_source": result.motion_kinematics_source,
        "kappa_source": result.kappa_source,
        "selected_calibration_path": result.selected_calibration_path,
        "selected_stage_meta_path": result.selected_stage_meta_path,
        "selected_stage_trace_path": result.selected_stage_trace_path,
        "selected_timestamps_path": result.selected_timestamps_path,
        "used_fallbacks": result.used_fallbacks,
        "timing_source": result.timing_source,
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

    if result.alignment_diagnostics is not None:
        diag = result.alignment_diagnostics
        d.update(
            {
                "align_baseline_end_s": diag.baseline_end_s,
                "align_baseline_median": diag.baseline_median,
                "align_baseline_mad": diag.baseline_mad,
                "align_baseline_sigma": diag.baseline_sigma,
                "align_onset_threshold_sigma": diag.onset_threshold_sigma,
                "align_onset_threshold_abs": diag.onset_threshold_abs,
                "align_onset_min_hold_s": diag.onset_min_hold_s,
                "align_n_baseline_samples": diag.n_baseline_samples,
                "align_n_total_samples": diag.n_total_samples,
                "align_n_frames_outside_baseline": diag.n_frames_outside_baseline,
                "align_failure_reason": diag.failure_reason,
                "align_message": diag.message,
                "align_n_candidates": len(diag.candidate_onset_times_s),
            }
        )
    else:
        d.update(
            {
                "align_baseline_end_s": None,
                "align_baseline_median": None,
                "align_baseline_mad": None,
                "align_baseline_sigma": None,
                "align_onset_threshold_sigma": None,
                "align_onset_threshold_abs": None,
                "align_onset_min_hold_s": None,
                "align_n_baseline_samples": None,
                "align_n_total_samples": None,
                "align_n_frames_outside_baseline": None,
                "align_failure_reason": None,
                "align_message": None,
                "align_n_candidates": None,
            }
        )
    for name, value in iter_qc_flags(result.qc_flags):
        d[f"qc_{name}"] = value
    return d


def _alignment_diagnostics_to_payload(diag: AlignmentDiagnostics) -> dict[str, Any]:
    return {
        "baseline_end_s": diag.baseline_end_s,
        "baseline_median": diag.baseline_median,
        "baseline_mad": diag.baseline_mad,
        "baseline_sigma": diag.baseline_sigma,
        "onset_threshold_sigma": diag.onset_threshold_sigma,
        "onset_threshold_abs": diag.onset_threshold_abs,
        "onset_min_hold_s": diag.onset_min_hold_s,
        "n_baseline_samples": diag.n_baseline_samples,
        "n_total_samples": diag.n_total_samples,
        "n_frames_outside_baseline": diag.n_frames_outside_baseline,
        "candidate_onset_times_s": list(diag.candidate_onset_times_s),
        "candidate_durations_s": list(diag.candidate_durations_s),
        "failure_reason": diag.failure_reason,
        "message": diag.message,
    }


def export_alignment_diagnostics_json(result: DragAnalysisResult, output_dir: Path) -> Path | None:
    """Export full alignment diagnostics (can include candidate onset lists)."""
    if result.alignment_diagnostics is None:
        return None

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.basename}_alignment_diagnostics.json"
    payload = _alignment_diagnostics_to_payload(result.alignment_diagnostics)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


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
    # Convert nested structures (e.g. used_fallbacks) into JSON strings for stable CSV cells.
    flat = {
        k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v)
        for k, v in payload.items()
    }
    fieldnames = list(payload.keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerow(flat)
    return path

