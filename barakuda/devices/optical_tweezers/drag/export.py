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
        "selected_trajectory_path": result.selected_trajectory_path,
        "current_drag_input_path": result.current_drag_input_path,
        "current_drag_item_root": result.current_drag_item_root,
        "brownian_baseline_folder": result.brownian_baseline_folder,
        "baseline_selection_mode": result.baseline_selection_mode,
        "drag_preflight_status": result.drag_preflight_status,
        "drag_preflight_message": result.drag_preflight_message,
        "current_drag_output_root": result.current_drag_output_root,
        "current_drag_report_path": result.current_drag_report_path,
        "current_drag_summary_json_path": result.current_drag_summary_json_path,
        "current_drag_summary_csv_path": result.current_drag_summary_csv_path,
        "current_drag_diagnostic_png_path": result.current_drag_diagnostic_png_path,
        "current_drag_alignment_json_path": result.current_drag_alignment_json_path,
        "used_fallbacks": result.used_fallbacks,
        "artifact_selection": result.artifact_selection,
        "artifact_selection_details": result.artifact_selection,
        "timing_source": result.timing_source,
        "timestamp_validation_pass": result.timestamp_validation_pass,
        "timestamp_validation_message": result.timestamp_validation_message,
        "report_source_kind": result.report_source_kind,
        "report_source_path": result.report_source_path,
        "motion_start_stage_s": result.motion_start_stage_s,
        "motion_stop_stage_s": result.motion_stop_stage_s,
        "motion_start_video_s_detected": result.motion_start_video_s_detected,
        "motion_stop_video_s_stage_aligned": result.motion_stop_video_s_stage_aligned,
        "alignment_offset_s": result.alignment_offset_s,
        "alignment_message": result.alignment_message,
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
        "commanded_travel_user_ref": result.commanded_travel_user_ref,
        "commanded_speed_user_s_ref": result.commanded_speed_user_s_ref,
        "actual_travel_um": result.actual_travel_um,
        "actual_speed_um_s": result.actual_speed_um_s,
        "drag_force_n": result.drag_force_n,
        "kappa_n_per_m": result.kappa_n_per_m,
        "kappa_pn_per_um": result.kappa_pn_per_um,
        "eta_pa_s": result.eta_pa_s,
        "analysis_status": result.analysis_status,
        "alignment_status": result.alignment_status,
        "physics_status": result.physics_status,
        "drag_physics_confidence": result.drag_physics_confidence,
        "drag_physics_warning": result.drag_physics_warning,
        "baseline_robustness_flag": result.baseline_robustness_flag,
        "onset_robustness_flag": result.onset_robustness_flag,
        "kinematics_robustness_flag": result.kinematics_robustness_flag,
        "baseline_robustness_message": result.baseline_robustness_message,
        "onset_robustness_message": result.onset_robustness_message,
        "kinematics_robustness_message": result.kinematics_robustness_message,
        "baseline_strategy_primary": result.baseline_strategy_primary,
        "baseline_strategy_alt": result.baseline_strategy_alt,
        "baseline_position_primary_px": result.baseline_position_primary_px,
        "baseline_position_primary_um": result.baseline_position_primary_um,
        "baseline_position_alt_px": result.baseline_position_alt_px,
        "baseline_position_alt_um": result.baseline_position_alt_um,
        "offset_primary_um": result.offset_primary_um,
        "offset_alt_um": result.offset_alt_um,
        "eta_primary_pa_s": result.eta_primary_pa_s,
        "eta_alt_pa_s": result.eta_alt_pa_s,
        "baseline_strategy_difference_ratio": result.baseline_strategy_difference_ratio,
        "relaxed_onset_used": result.relaxed_onset_used,
        "competing_durable_candidates_count": result.competing_durable_candidates_count,
        "onset_candidate_density": result.onset_candidate_density,
        "speed_stage_json": result.speed_stage_json,
        "speed_trace_derived": result.speed_trace_derived,
        "speed_used_for_physics": result.speed_used_for_physics,
        "speed_consistency_error_pct": result.speed_consistency_error_pct,
        "expected_offset_if_eta_1mPas_um": result.expected_offset_if_eta_1mPas_um,
        "expected_offset_if_eta_from_baseline_um": result.expected_offset_if_eta_from_baseline_um,
        "measured_offset_um": result.measured_offset_um,
        "offset_underestimation_ratio_vs_water": result.offset_underestimation_ratio_vs_water,
        "offset_underestimation_ratio_vs_baseline": result.offset_underestimation_ratio_vs_baseline,
        "drag_validation_gate": result.drag_validation_gate,
        "drag_validation_reason": result.drag_validation_reason,
        "offset_current_windows_um": result.offset_current_windows_um,
        "offset_alt_baseline_um": result.offset_alt_baseline_um,
        "eta_current_windows": result.eta_current_windows,
        "eta_alt_baseline": result.eta_alt_baseline,
        "baseline_reference_median_px": result.baseline_reference_median_px,
        "baseline_reference_window_start_s": result.baseline_reference_window_start_s,
        "baseline_reference_window_end_s": result.baseline_reference_window_end_s,
        "baseline_median_delta_px": result.baseline_median_delta_px,
        "baseline_median_delta_um": result.baseline_median_delta_um,
        "stage_speed_from_trace_um_s": result.stage_speed_from_trace_um_s,
        "stage_speed_relative_diff": result.stage_speed_relative_diff,
        "stage_speed_consistent": result.stage_speed_consistent,
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
                "onset_relaxed_used": diag.onset_relaxed_used,
                "onset_competing_durable_candidates": diag.onset_competing_durable_candidates,
                "onset_ambiguity_score": diag.onset_ambiguity_score,
                "onset_confidence_class": diag.onset_confidence_class,
                "onset_candidate_density": diag.onset_candidate_density,
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
        "onset_relaxed_used": diag.onset_relaxed_used,
        "onset_competing_durable_candidates": diag.onset_competing_durable_candidates,
        "onset_ambiguity_score": diag.onset_ambiguity_score,
        "onset_confidence_class": diag.onset_confidence_class,
        "onset_candidate_density": diag.onset_candidate_density,
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


def export_drag_summary_json(
    result: DragAnalysisResult,
    output_dir: Path,
    *,
    protocol_path: str | None = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.basename}_drag_summary.json"
    payload = drag_result_to_dict(result)
    payload["protocol_present"] = bool(protocol_path)
    payload["protocol_path"] = protocol_path
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def export_drag_summary_csv(
    result: DragAnalysisResult,
    output_dir: Path,
    *,
    protocol_path: str | None = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.basename}_drag_summary.csv"
    payload = drag_result_to_dict(result)
    payload["protocol_present"] = bool(protocol_path)
    payload["protocol_path"] = protocol_path
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

