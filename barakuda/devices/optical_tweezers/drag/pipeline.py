from __future__ import annotations

import csv
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from barakuda.core.video_reader import VideoReader
from barakuda.devices.optical_tweezers.pipeline.tracking import (
    Roi,
    TrackingMethod,
    choose_tracking_polarity,
    roi_follow_center,
    track_particle,
)

from .analysis import analyze_drag_run
from .io import discover_drag_run_paths, DragIoError
from .schema import DragAnalysisConfig
from barakuda.core.run_protocol import (
    create_protocol_from_context,
    load_protocol,
    merge_protocol,
    save_protocol,
)


def _run_tracking_to_trajectory(
    raw_path: Path,
    output_dir: Path,
    tracking_config: dict[str, Any] | None = None,
) -> Path:
    """Run shared OT tracking on RAW video and write a minimal trajectory CSV.

    This is a tracking-only helper (no Brownian/drag physics). It writes:
      <basename>_trajectory.csv
    with columns:
      frame, t_s, x_px, y_px, quality
    """
    tracking_config = dict(tracking_config or {})
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reader = VideoReader(str(raw_path))
    try:
        fps = float(reader.meta.fps)
        if not np.isfinite(fps) or fps <= 0:
            raise DragIoError(f"Invalid FPS detected for {raw_path.name}: {fps}")

        n_frames = int(getattr(reader.meta, "frame_count", 0))
        if n_frames <= 0:
            raise DragIoError(f"No frames detected in video: {raw_path}")

        # Tracking defaults (RADIAL_SYMMETRY, auto polarity, full-frame ROI).
        method = TrackingMethod(tracking_config.get("method", "RADIAL_SYMMETRY"))
        blur_sigma = float(tracking_config.get("blur_sigma", 1.2))
        radial_grad_threshold = float(tracking_config.get("radial_grad_threshold", 2.0))
        invert_default = bool(tracking_config.get("invert", True))
        auto_polarity = bool(tracking_config.get("auto_polarity", True))

        init_roi = tracking_config.get(
            "roi",
            [0, 0, int(getattr(reader.meta, "width", 0)), int(getattr(reader.meta, "height", 0))],
        )
        roi_obj = Roi(*init_roi)

        t_s: list[float] = []
        x_px: list[float] = []
        y_px: list[float] = []
        quality: list[float] = []

        locked_invert = invert_default
        locked_det = None

        for fi in range(n_frames):
            frame = reader.get_frame(fi)
            if locked_det is None and auto_polarity:
                locked_invert, locked_det = choose_tracking_polarity(
                    frame,
                    roi_obj,
                    method=method,
                    blur_sigma=blur_sigma,
                    radial_grad_threshold=radial_grad_threshold,
                    annulus_enabled=False,
                    annulus_auto=False,
                    annulus_r_inner_px=None,
                    annulus_r_outer_px=None,
                    annulus_profile_smooth=3,
                    compute_device="cpu",
                )
            if fi == 0 and locked_det is not None:
                det = locked_det
                locked_det = None
            else:
                det = track_particle(
                    frame,
                    roi_obj,
                    method=method,
                    compute_device="cpu",
                    invert=locked_invert,
                    blur_sigma=blur_sigma,
                    radial_grad_threshold=radial_grad_threshold,
                    auto_polarity=False,
                    annulus_enabled=False,
                    annulus_auto=False,
                    annulus_r_inner_px=None,
                    annulus_r_outer_px=None,
                    annulus_profile_smooth=3,
                )

            t_s.append(fi / fps if fps > 0 else 0.0)
            x_px.append(float(det.x_px))
            y_px.append(float(det.y_px))
            quality.append(float(det.quality))

            roi_obj = roi_follow_center(frame.shape, roi_obj, det.x_px, det.y_px)

    finally:
        reader.close()

    basename = raw_path.stem
    traj_path = output_dir / f"{basename}_trajectory.csv"
    with traj_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "t_s", "x_px", "y_px", "quality"])
        for fi, (t, x, y, q) in enumerate(zip(t_s, x_px, y_px, quality)):
            w.writerow([fi, f"{t:.9f}", f"{x:.9f}", f"{y:.9f}", f"{q:.9f}"])

    return traj_path


def generate_drag_trajectory_from_raw(
    run_dir: Path,
    output_csv_dir: Path,
    tracking_config: dict[str, Any] | None = None,
) -> Path:
    """Run OT tracking on Drag RAW and write ``<basename>_trajectory.csv`` under ``output_csv_dir``.

    Does not search for an existing trajectory CSV; does not use Brownian calibration.
    """
    paths = discover_drag_run_paths(
        run_dir,
        trajectory_path=None,
        require_trajectory=False,
        include_trajectory_discovery=False,
    )
    output_csv_dir = Path(output_csv_dir)
    output_csv_dir.mkdir(parents=True, exist_ok=True)
    return _run_tracking_to_trajectory(paths.raw_path, output_csv_dir, tracking_config=tracking_config)


def finalize_drag_run_from_trajectory(
    run_dir: Path,
    trajectory_path: Path,
    drag_config: DragAnalysisConfig,
    output_root: Path,
) -> tuple["DragAnalysisResult", dict[str, Path]]:
    """Physics, exports, and protocol merge after Drag-owned trajectory exists.

    ``drag_config`` must already include Brownian-derived calibration (κ, etc.) when required.
    """
    paths = discover_drag_run_paths(
        run_dir,
        trajectory_path=None,
        require_trajectory=False,
        include_trajectory_discovery=False,
    )
    canonical_root = Path(output_root).resolve()
    out_audit = canonical_root / "audit"
    out_csv = canonical_root / "csv"
    out_results = canonical_root / "results"
    for d in (canonical_root, out_audit, out_csv, out_results):
        d.mkdir(parents=True, exist_ok=True)

    from .export import (
        export_alignment_diagnostics_json,
        export_drag_summary_csv,
        export_drag_summary_json,
    )
    from .plotting import plot_drag_diagnostic
    from .analysis import _interp_time_for_frames  # reuse helper
    from barakuda.core.trajectory_csv_io import read_trajectory_csv
    import csv as _csv

    cfg = replace(
        drag_config,
        current_drag_output_root=str(canonical_root),
    )
    traj_path = Path(trajectory_path).resolve()
    result = analyze_drag_run(
        run_dir,
        cfg,
        trajectory_path=traj_path,
        trajectory_source_kind="generated_from_drag_raw",
        trajectory_generated_in_this_workflow=True,
    )
    expected_summary_path = out_audit / f"{result.basename}_drag_summary.json"
    result = replace(
        result,
        report_source_kind="drag_summary",
        report_source_path=str(expected_summary_path),
    )

    # Exports
    summary_json = export_drag_summary_json(
        result,
        out_audit,
    )
    summary_csv = export_drag_summary_csv(
        result,
        out_csv,
    )
    alignment_diag_json = export_alignment_diagnostics_json(result, out_audit)

    # Diagnostic plot needs full time axis and px signal
    traj_table = read_trajectory_csv(traj_path)
    frames = [int(float(r.get("frame", "0"))) for r in traj_table.rows]
    axis = result.axis
    sig_px = [float(r.get(f"{axis}_px", "nan")) for r in traj_table.rows]

    ts_frames: list[int] = []
    ts_times: list[float] = []
    with paths.timestamps_path.open("r", encoding="utf-8", newline="") as f:
        rdr = _csv.DictReader(f)
        for row in rdr:
            if not row:
                continue
            try:
                ts_frames.append(int(row.get("frame", "0")))
                ts_times.append(float(row.get("timestamp_s", "nan")))
            except Exception:  # noqa: BLE001
                continue

    t_video = _interp_time_for_frames(ts_frames, ts_times, frames)
    diagnostic_png = plot_drag_diagnostic(t_video, sig_px, result, out_results)
    windows_csv = out_csv / f"{result.basename}_drag_windows.csv"
    with windows_csv.open("w", encoding="utf-8", newline="") as wf:
        w = _csv.writer(wf)
        w.writerow(["window", "start_s", "end_s", "duration_s"])
        for name, start_s, end_s in (
            ("baseline", result.windows.baseline_start_s, result.windows.baseline_end_s),
            ("steady", result.windows.steady_start_s, result.windows.steady_end_s),
        ):
            w.writerow([name, f"{float(start_s):.9f}", f"{float(end_s):.9f}", f"{float(end_s - start_s):.9f}"])
    trace_annotated_csv = out_csv / f"{result.basename}_drag_trace_annotated.csv"
    with trace_annotated_csv.open("w", encoding="utf-8", newline="") as tf:
        w = _csv.writer(tf)
        w.writerow(
            [
                "frame",
                "video_time_s",
                "video_time_rel_s",
                "axis_px",
                "is_baseline_window",
                "is_steady_window",
                "is_motion_interval",
                "stage_time_aligned_s",
            ]
        )
        primary_motion_start = (
            result.expected_stage_start_video_s
            if (result.drag_anchor_mode == "stage_validated" and result.expected_stage_start_video_s is not None)
            else result.motion_start_video_s_detected
        )
        primary_motion_stop = (
            result.expected_stage_stop_video_s
            if (result.drag_anchor_mode == "stage_validated" and result.expected_stage_stop_video_s is not None)
            else result.motion_stop_video_s_stage_aligned
        )
        t0 = float(result.t_first_s) if result.t_first_s is not None else float(t_video[0] if t_video else 0.0)
        for fi, t_s, px in zip(frames, t_video, sig_px):
            is_baseline = result.windows.baseline_start_s <= t_s <= result.windows.baseline_end_s
            is_steady = result.windows.steady_start_s <= t_s <= result.windows.steady_end_s
            if primary_motion_stop is not None:
                is_motion = primary_motion_start <= t_s <= primary_motion_stop
            else:
                is_motion = t_s >= primary_motion_start
            stage_aligned_s = t_s - float(result.alignment_offset_s)
            w.writerow(
                [
                    int(fi),
                    f"{float(t_s):.9f}",
                    f"{float(t_s - t0):.9f}",
                    f"{float(px):.9f}",
                    int(bool(is_baseline)),
                    int(bool(is_steady)),
                    int(bool(is_motion)),
                    f"{float(stage_aligned_s):.9f}",
                ]
            )

    result = replace(
        result,
        current_drag_output_root=str(canonical_root),
        current_drag_summary_json_path=str(summary_json),
        current_drag_summary_csv_path=str(summary_csv),
        current_drag_diagnostic_png_path=str(diagnostic_png) if diagnostic_png is not None else None,
        current_drag_alignment_json_path=str(alignment_diag_json) if alignment_diag_json is not None else None,
        report_source_kind="drag_summary",
        report_source_path=str(summary_json),
    )

    outputs = {
        "trajectory": traj_path,
        "summary_json": summary_json,
        "summary_csv": summary_csv,
        "windows_csv": windows_csv,
        "trace_annotated_csv": trace_annotated_csv,
        "diagnostic_png": diagnostic_png,
        "alignment_diagnostics_json": alignment_diag_json,
    }
    protocol_path = _update_run_protocol_with_drag_analysis(
        run_dir=canonical_root,
        result=result,
        outputs=outputs,
    )
    if protocol_path:
        summary_json = export_drag_summary_json(
            result,
            out_audit,
            protocol_path=str(protocol_path),
        )
        summary_csv = export_drag_summary_csv(
            result,
            out_csv,
            protocol_path=str(protocol_path),
        )
        result = replace(
            result,
            current_drag_summary_json_path=str(summary_json),
            current_drag_summary_csv_path=str(summary_csv),
            report_source_kind="drag_summary",
            report_source_path=str(summary_json),
        )
        outputs["summary_json"] = summary_json
        outputs["summary_csv"] = summary_csv
    return result, outputs


def run_drag_from_raw(
    run_dir: Path,
    drag_config: DragAnalysisConfig | None = None,
    tracking_config: dict[str, Any] | None = None,
    output_root: Path | None = None,
) -> tuple["DragAnalysisResult", dict[str, Path]]:
    """End-to-end DRAG over a RAW run folder (tracking on RAW, then analysis).

    ``drag_config`` must carry calibration inputs (e.g. κ from Brownian) when used
    from a full shell pipeline; this helper does not load Brownian folders itself.
    """
    paths = discover_drag_run_paths(
        run_dir,
        trajectory_path=None,
        require_trajectory=False,
        include_trajectory_discovery=False,
    )
    canonical_root = (
        Path(output_root).resolve()
        if output_root is not None
        else (Path(paths.run_dir).resolve() / "analysis")
    )
    out_csv = canonical_root / "csv"
    out_csv.mkdir(parents=True, exist_ok=True)
    traj_path = _run_tracking_to_trajectory(paths.raw_path, out_csv, tracking_config=tracking_config)
    cfg = drag_config or DragAnalysisConfig(analysis_axis="x")
    return finalize_drag_run_from_trajectory(run_dir, traj_path, cfg, canonical_root)


def _update_run_protocol_with_drag_analysis(
    *,
    run_dir: Path,
    result: "DragAnalysisResult",
    outputs: dict[str, Path] | None = None,
) -> Path | None:
    provenance_warnings = [
        w for w in result.warnings if isinstance(w, str) and w.startswith("PROVENANCE_WARNING:")
    ]
    analysis_updates: dict[str, Any] = {
        "analysis_type": "drag",
        "selected_calibration_path": result.selected_calibration_path,
        "report_source_kind": result.report_source_kind,
        "report_source_path": result.report_source_path,
        "analysis_axis": result.analysis_axis,
        "stage_axis": result.stage_axis,
        "warnings": list(result.warnings),
        "qc_flags": {
            name: value for name, value in result.qc_flags.__dict__.items()
        },
        "physics_status": result.physics_status,
        "analysis_status": result.analysis_status,
        "drag_physics_confidence": result.drag_physics_confidence,
        "drag_physics_warning": result.drag_physics_warning,
        "baseline_robustness_flag": result.baseline_robustness_flag,
        "baseline_robustness_message": result.baseline_robustness_message,
        "onset_robustness_flag": result.onset_robustness_flag,
        "onset_robustness_message": result.onset_robustness_message,
        "kinematics_robustness_flag": result.kinematics_robustness_flag,
        "kinematics_robustness_message": result.kinematics_robustness_message,
        "drag_validation_gate": result.drag_validation_gate,
        "drag_validation_reason": result.drag_validation_reason,
        "alignment_sanity_flag": result.alignment_sanity_flag,
        "alignment_sanity_message": result.alignment_sanity_message,
        "expected_stage_start_video_s": result.expected_stage_start_video_s,
        "expected_stage_stop_video_s": result.expected_stage_stop_video_s,
        "detected_stage_start_video_s": result.detected_stage_start_video_s,
        "detected_stage_stop_video_s": result.detected_stage_stop_video_s,
        "stage_video_start_delta_s": result.stage_video_start_delta_s,
        "stage_video_stop_delta_s": result.stage_video_stop_delta_s,
        "drag_anchor_mode_requested": result.drag_anchor_mode_requested,
        "drag_anchor_mode_effective": result.drag_anchor_mode,
        "drag_anchor_mode": result.drag_anchor_mode,
        "primary_timing_source_for_windows": result.primary_timing_source_for_windows,
        "motion_timing_primary_source": result.motion_timing_primary_source,
        "detected_onset_video_s": result.detected_onset_video_s,
        "detected_onset_diagnostic_only": result.detected_onset_diagnostic_only,
        "detected_onset_consistency_flag": result.detected_onset_consistency_flag,
        "detected_onset_consistency_message": result.detected_onset_consistency_message,
        "stage_anchor_confidence": result.stage_anchor_confidence,
        "stage_anchor_reason": result.stage_anchor_reason,
        "physics_primary_gate": result.physics_primary_gate,
        "detection_qc_gate": result.detection_qc_gate,
        "final_drag_verdict": result.final_drag_verdict,
        "final_drag_reason": result.final_drag_reason,
        "stage_validated_physics_acceptable": result.stage_validated_physics_acceptable,
        "detected_onset_qc_only": result.detected_onset_qc_only,
        "detected_onset_veto_applied": result.detected_onset_veto_applied,
        "baseline_strategy_primary": result.baseline_strategy_primary,
        "baseline_strategy_alt": result.baseline_strategy_alt,
        "onset_ambiguity_score": (
            result.alignment_diagnostics.onset_ambiguity_score
            if result.alignment_diagnostics is not None
            else None
        ),
        "onset_confidence_class": (
            result.alignment_diagnostics.onset_confidence_class
            if result.alignment_diagnostics is not None
            else None
        ),
        "selected_results": {
            "drag_force_n": result.drag_force_n,
            "kappa_n_per_m": result.kappa_n_per_m,
            "kappa_pn_per_um": result.kappa_pn_per_um,
            "eta_pa_s": result.eta_pa_s,
            "actual_speed_um_s": result.actual_speed_um_s,
            "eta_current_windows": result.eta_current_windows,
            "eta_alt_baseline": result.eta_alt_baseline,
            "offset_current_windows_um": result.offset_current_windows_um,
            "offset_alt_baseline_um": result.offset_alt_baseline_um,
            "eta_primary_pa_s": result.eta_primary_pa_s,
            "eta_alt_pa_s": result.eta_alt_pa_s,
            "offset_primary_um": result.offset_primary_um,
            "offset_alt_um": result.offset_alt_um,
            "baseline_strategy_difference_ratio": result.baseline_strategy_difference_ratio,
            "expected_offset_if_eta_1mPas_um": result.expected_offset_if_eta_1mPas_um,
            "expected_offset_if_eta_from_baseline_um": result.expected_offset_if_eta_from_baseline_um,
            "measured_offset_um": result.measured_offset_um,
            "offset_underestimation_ratio_vs_water": result.offset_underestimation_ratio_vs_water,
            "offset_underestimation_ratio_vs_baseline": result.offset_underestimation_ratio_vs_baseline,
            "speed_stage_json": result.speed_stage_json,
            "speed_trace_derived": result.speed_trace_derived,
            "speed_used_for_physics": result.speed_used_for_physics,
            "speed_consistency_error_pct": result.speed_consistency_error_pct,
        },
    }
    if provenance_warnings:
        analysis_updates["provenance_warnings"] = provenance_warnings
    if outputs:
        analysis_updates["summary_references"] = {
            k: str(v) for k, v in outputs.items() if v is not None
        }
    provenance_updates: dict[str, Any] = {
        "um_per_px_source": result.um_per_px_source,
        "stage_um_per_unit_source": result.stage_um_per_unit_source,
        "kappa_source": result.kappa_source,
        "timing_source": result.timing_source,
        "motion_kinematics_source": result.motion_kinematics_source,
        "analysis_axis": result.analysis_axis,
        "stage_axis": result.stage_axis,
        "selected_stage_meta_path": result.selected_stage_meta_path,
        "selected_stage_trace_path": result.selected_stage_trace_path,
        "selected_timestamps_path": result.selected_timestamps_path,
        "selected_trajectory_path": result.selected_trajectory_path,
        "trajectory_source_kind": result.trajectory_source_kind,
        "trajectory_generated_in_this_workflow": result.trajectory_generated_in_this_workflow,
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
        "report_source_kind": result.report_source_kind,
        "report_source_path": result.report_source_path,
        "alignment_message": result.alignment_message,
        "commanded_travel_user_ref": result.commanded_travel_user_ref,
        "commanded_speed_user_s_ref": result.commanded_speed_user_s_ref,
        "stage_speed_from_trace_um_s": result.stage_speed_from_trace_um_s,
        "stage_speed_relative_diff": result.stage_speed_relative_diff,
        "stage_speed_consistent": result.stage_speed_consistent,
        "baseline_reference_median_px": result.baseline_reference_median_px,
        "baseline_reference_window_start_s": result.baseline_reference_window_start_s,
        "baseline_reference_window_end_s": result.baseline_reference_window_end_s,
        "baseline_median_delta_px": result.baseline_median_delta_px,
        "baseline_median_delta_um": result.baseline_median_delta_um,
        "window_clipping_applied": result.window_clipping_applied,
        "window_clipping_message": result.window_clipping_message,
        "drag_anchor_mode_requested": result.drag_anchor_mode_requested,
        "drag_anchor_mode_effective": result.drag_anchor_mode,
        "drag_anchor_mode": result.drag_anchor_mode,
        "primary_timing_source_for_windows": result.primary_timing_source_for_windows,
        "motion_timing_primary_source": result.motion_timing_primary_source,
        "detected_onset_video_s": result.detected_onset_video_s,
        "detected_onset_diagnostic_only": result.detected_onset_diagnostic_only,
        "detected_onset_consistency_flag": result.detected_onset_consistency_flag,
        "detected_onset_consistency_message": result.detected_onset_consistency_message,
        "stage_anchor_confidence": result.stage_anchor_confidence,
        "stage_anchor_reason": result.stage_anchor_reason,
        "physics_primary_gate": result.physics_primary_gate,
        "detection_qc_gate": result.detection_qc_gate,
        "final_drag_verdict": result.final_drag_verdict,
        "final_drag_reason": result.final_drag_reason,
        "stage_validated_physics_acceptable": result.stage_validated_physics_acceptable,
        "detected_onset_qc_only": result.detected_onset_qc_only,
        "detected_onset_veto_applied": result.detected_onset_veto_applied,
        "baseline_window_original_start_s": result.baseline_window_original_start_s,
        "baseline_window_original_end_s": result.baseline_window_original_end_s,
        "steady_window_original_start_s": result.steady_window_original_start_s,
        "steady_window_original_end_s": result.steady_window_original_end_s,
        "baseline_window_clipped_start_s": result.baseline_window_clipped_start_s,
        "baseline_window_clipped_end_s": result.baseline_window_clipped_end_s,
        "steady_window_clipped_start_s": result.steady_window_clipped_start_s,
        "steady_window_clipped_end_s": result.steady_window_clipped_end_s,
        "baseline_position_primary_px": result.baseline_position_primary_px,
        "baseline_position_primary_um": result.baseline_position_primary_um,
        "baseline_position_alt_px": result.baseline_position_alt_px,
        "baseline_position_alt_um": result.baseline_position_alt_um,
        "baseline_strategy_difference_ratio": result.baseline_strategy_difference_ratio,
        "relaxed_onset_used": result.relaxed_onset_used,
        "competing_durable_candidates_count": result.competing_durable_candidates_count,
        "onset_candidate_density": result.onset_candidate_density,
        "selected_calibration_path": result.selected_calibration_path,
        "used_fallbacks": dict(result.used_fallbacks),
        "artifact_selection": dict(result.artifact_selection),
        "selected_sidecar_paths": {
            "stage_meta_path": result.selected_stage_meta_path,
            "stage_trace_path": result.selected_stage_trace_path,
            "timestamps_path": result.selected_timestamps_path,
            "trajectory_path": result.selected_trajectory_path,
        },
    }
    updates = {
        "identity": {
            "run_id": result.basename,
            "source_type": "analysis",
        },
        "analysis": analysis_updates,
        "provenance": provenance_updates,
    }
    try:
        existing = load_protocol(run_dir)
    except Exception:
        existing = create_protocol_from_context()
    try:
        merged = merge_protocol(existing, updates, allow_manual_overwrite=False)
        protocol_path = save_protocol(merged, run_dir)
        audit_protocol = Path(run_dir) / "audit" / "run_protocol.json"
        audit_protocol.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(protocol_path, audit_protocol)
        return protocol_path
    except Exception as exc:
        raise RuntimeError(
            f"DRAG run_protocol update failed for run_dir={Path(run_dir).resolve()}: {exc}"
        ) from exc

