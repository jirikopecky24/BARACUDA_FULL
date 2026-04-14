from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence

from barakuda.core.trajectory_csv_io import read_trajectory_csv

from .alignment import detect_motion_onset, build_alignment_result, DragAlignmentError
from .io import load_drag_run, DragIoError
from .physics import compute_drag_force, compute_kappa_from_drag, compute_eta_from_drag, DragPhysicsError
from .schema import (
    DragAnalysisConfig,
    DragAnalysisResult,
    DragQCFlags,
    DragRunLoaded,
    DragStageTiming,
    DragWindowParams,
    DragWindows,
)
from .windows import compute_windows, DragWindowError


def _median_in_window(t: Sequence[float], y: Sequence[float], t0: float, t1: float) -> float:
    vals = [y[i] for i in range(len(t)) if t0 <= t[i] <= t1 and math.isfinite(y[i])]
    if not vals:
        return float("nan")
    vals_sorted = sorted(vals)
    m = len(vals_sorted)
    mid = m // 2
    if m % 2 == 1:
        return float(vals_sorted[mid])
    return float(0.5 * (vals_sorted[mid - 1] + vals_sorted[mid]))


def _window_stats(
    t: Sequence[float],
    y: Sequence[float],
    t0: float,
    t1: float,
) -> tuple[float, float, int, float]:
    """Robust median stats in a time window (median, sigma_MAD, n, SE_median)."""
    vals = [float(y[i]) for i in range(len(t)) if t0 <= t[i] <= t1 and math.isfinite(y[i])]
    if not vals:
        return float("nan"), float("nan"), 0, float("nan")
    vals_sorted = sorted(vals)
    m = len(vals_sorted)
    mid = m // 2
    if m % 2 == 1:
        median = float(vals_sorted[mid])
    else:
        median = float(0.5 * (vals_sorted[mid - 1] + vals_sorted[mid]))
    if m < 2:
        return median, float("nan"), m, float("nan")
    abs_dev = sorted(abs(v - median) for v in vals_sorted)
    mad = abs_dev[mid] if (m % 2 == 1) else 0.5 * (abs_dev[mid - 1] + abs_dev[mid])
    sigma_mad = 1.4826 * float(mad)
    if not math.isfinite(sigma_mad) or sigma_mad <= 0:
        mean = sum(vals_sorted) / float(m)
        var = sum((v - mean) ** 2 for v in vals_sorted) / float(max(1, m - 1))
        sigma_mad = math.sqrt(max(0.0, var))
    se_median = 1.253314 * sigma_mad / math.sqrt(float(m)) if sigma_mad > 0 else float("nan")
    return median, sigma_mad, m, se_median


def _classify_onset_ambiguity(
    candidate_count: int,
    candidate_durations: Sequence[float],
    min_hold_s: float,
    used_relaxed_onset: bool,
) -> tuple[int, float, float, str]:
    durable = sum(1 for d in candidate_durations if float(d) >= float(min_hold_s))
    competing = max(0, durable - 1)
    density = (float(candidate_count) / max(1.0, float(min_hold_s)))
    score = 0.0
    score += min(0.6, competing * 0.2)
    if candidate_count > 8:
        score += min(0.25, (candidate_count - 8) * 0.01)
    if used_relaxed_onset:
        score += 0.25
    score = max(0.0, min(1.0, score))
    if score >= 0.65:
        cls = "low"
    elif score >= 0.30:
        cls = "medium"
    else:
        cls = "high"
    return competing, density, score, cls


def _clip_window_to_video(
    start_s: float,
    end_s: float,
    t_first_s: float,
    t_last_s: float,
) -> tuple[float, float, bool]:
    cs = max(float(start_s), float(t_first_s))
    ce = min(float(end_s), float(t_last_s))
    clipped = (abs(cs - float(start_s)) > 1e-12) or (abs(ce - float(end_s)) > 1e-12)
    return cs, ce, clipped


def _interp_time_for_frames(
    frame_indices: Sequence[int],
    frame_times: Sequence[float],
    target_frames: Sequence[int],
) -> list[float]:
    """Map trajectory frame indices to video timestamps via nearest neighbor."""
    if not frame_indices or not frame_times or len(frame_indices) != len(frame_times):
        raise ValueError("Invalid frame_indices/frame_times inputs")
    index_to_time = {int(f): float(t) for f, t in zip(frame_indices, frame_times)}
    missing_frames = [int(fi) for fi in target_frames if int(fi) not in index_to_time]
    if missing_frames:
        preview = ", ".join(str(fi) for fi in missing_frames[:5])
        extra = "" if len(missing_frames) <= 5 else f" (+{len(missing_frames) - 5} more)"
        raise DragIoError(
            "Trajectory frame indices are missing in timestamps mapping; "
            "refusing silent frame->time clipping. "
            f"Missing frames: {preview}{extra}"
        )
    out: list[float] = []
    for fi in target_frames:
        t = index_to_time[int(fi)]
        out.append(float(t))
    return out


def _extract_axis_series(
    traj_path: Path,
    axis: str,
    um_per_px: float | None,
) -> tuple[list[int], list[float], list[float] | None]:
    """Extract frame indices and axis signal (px and optional µm) from trajectory CSV."""
    table = read_trajectory_csv(traj_path)
    rows = table.rows

    frame_col = "frame"
    if frame_col not in table.header:
        raise DragIoError(f"Trajectory CSV {traj_path.name} must contain 'frame' column")

    axis_px_col = f"{axis}_px"
    axis_um_col = f"{axis}_um"
    if axis_px_col not in table.header:
        raise DragIoError(f"Trajectory CSV {traj_path.name} must contain '{axis_px_col}' column")

    frames: list[int] = []
    sig_px: list[float] = []
    sig_um: list[float] | None = [] if um_per_px is not None or axis_um_col in table.header else None

    for r in rows:
        try:
            fi = int(float(r.get(frame_col, "nan")))
            x_px = float(r.get(axis_px_col, "nan"))
        except Exception:  # noqa: BLE001
            continue
        if not math.isfinite(x_px):
            continue
        frames.append(fi)
        sig_px.append(x_px)
        if sig_um is not None:
            if axis_um_col in table.header:
                try:
                    x_um = float(r.get(axis_um_col, "nan"))
                except Exception:  # noqa: BLE001
                    x_um = math.nan
            else:
                x_um = x_px * float(um_per_px or 0.0)
            sig_um.append(x_um)

    if sig_um is not None and not sig_um:
        sig_um = None

    return frames, sig_px, sig_um


def _safe_positive_float(raw: object) -> float | None:
    try:
        val = float(raw)
    except Exception:  # noqa: BLE001
        return None
    if not math.isfinite(val) or val <= 0:
        return None
    return val


def _estimate_stage_markers(
    timing: DragStageTiming,
    protocol_params: dict[str, object],
) -> tuple[float | None, str, float | None, str]:
    steady_state_start_s = None
    steady_source = "motion_start_anchor"
    if timing.steady_state_start_stage_s is not None:
        steady_state_start_s = float(timing.steady_state_start_stage_s)
        steady_source = "stage_trace_steady_state_start"
    elif timing.motion_running_confirmed_s is not None:
        steady_state_start_s = float(timing.motion_running_confirmed_s)
        steady_source = "stage_trace_motion_running_confirmed"
    elif timing.motion_start_stage_s is not None:
        steady_state_start_s = float(timing.motion_start_stage_s)
        steady_source = "stage_trace_motion_start"
    elif timing.motion_command_issued_s is not None:
        steady_state_start_s = float(timing.motion_command_issued_s)
        steady_source = "stage_trace_motion_command_issued"

    decel_start_s = None
    decel_source = "motion_stop_fallback"
    if timing.deceleration_start_stage_s is not None:
        decel_start_s = float(timing.deceleration_start_stage_s)
        decel_source = "stage_trace_deceleration_start"
        return steady_state_start_s, steady_source, decel_start_s, decel_source

    if timing.motion_stop_stage_s is None:
        return steady_state_start_s, steady_source, decel_start_s, decel_source

    commanded_speed = _safe_positive_float(protocol_params.get("speed_user_s_commanded"))
    commanded_decel = _safe_positive_float(protocol_params.get("decel_user_s2_commanded"))
    if commanded_speed is not None and commanded_decel is not None:
        decel_duration_s = commanded_speed / commanded_decel
        if math.isfinite(decel_duration_s) and decel_duration_s > 0:
            candidate = float(timing.motion_stop_stage_s) - decel_duration_s
            lower_bound = (
                float(steady_state_start_s) if steady_state_start_s is not None else float("-inf")
            )
            if candidate > lower_bound:
                decel_start_s = candidate
                decel_source = "estimated_from_commanded_speed_decel"
    return steady_state_start_s, steady_source, decel_start_s, decel_source


def analyze_drag_run(
    run_dir: Path,
    config: DragAnalysisConfig,
    trajectory_path: Path | None = None,
    *,
    allow_discovered_trajectory: bool = False,
    trajectory_source_kind: str | None = None,
    trajectory_generated_in_this_workflow: bool | None = None,
) -> DragAnalysisResult:
    """High-level entry point: perform DRAG analysis for a single run folder.

    Default thesis-safe path: pass ``trajectory_path`` to the CSV produced by Drag
    tracking (e.g. ``run_drag_from_raw`` / ``generate_drag_trajectory_from_raw``).

    Set ``allow_discovered_trajectory=True`` only for explicit debug/legacy reuse of
    an on-disk trajectory without running tracking first.
    """
    rd = Path(run_dir)
    if trajectory_path is None:
        if not allow_discovered_trajectory:
            raise DragIoError(
                "Drag analysis requires trajectory_path for the default path (trajectory from Drag tracking "
                "on this RAW). Use allow_discovered_trajectory=True only to reuse an existing on-disk "
                "trajectory CSV (non-default / debug)."
            )
        loaded = load_drag_run(rd, trajectory_path=None, allow_discover_trajectory=True)
        _traj_kind = trajectory_source_kind or "reused_existing_trajectory"
        _traj_gen = (
            False if trajectory_generated_in_this_workflow is None else bool(trajectory_generated_in_this_workflow)
        )
    else:
        loaded = load_drag_run(rd, trajectory_path=Path(trajectory_path), allow_discover_trajectory=False)
        if trajectory_source_kind == "generated_from_drag_raw":
            _traj_kind = "generated_from_drag_raw"
            _traj_gen = True if trajectory_generated_in_this_workflow is None else bool(trajectory_generated_in_this_workflow)
        else:
            _traj_kind = trajectory_source_kind or "provided_explicit_path"
            _traj_gen = (
                bool(trajectory_generated_in_this_workflow)
                if trajectory_generated_in_this_workflow is not None
                else False
            )

    axis = config.analysis_axis
    stage_axis = loaded.stage_meta.axis
    if stage_axis != axis:
        raise ValueError(
            "DRAG axis mismatch: configured analysis_axis="
            f"{axis!r} but loaded stage metadata axis={stage_axis!r}. "
            "Stage motion axis must match the analysis axis to preserve sign conventions "
            "and compute offsets/physics from the intended displacement component."
        )
    um_per_px = config.um_per_px

    # 1) Extract trajectory along requested axis
    traj_path = loaded.paths.trajectory_path
    assert traj_path is not None  # enforced by load_drag_run
    traj_frames, traj_px, traj_um = _extract_axis_series(traj_path, axis, um_per_px)

    # 2) Map trajectory frames to authoritative video timestamps
    t_video = _interp_time_for_frames(loaded.frame_indices, loaded.frame_timestamps_s, traj_frames)

    # 3) Alignment: detect onset
    timing_anchor_used = "motion_start_legacy"
    if loaded.stage_timing.motion_running_confirmed_s is not None:
        motion_start_stage_s = float(loaded.stage_timing.motion_running_confirmed_s)
        timing_anchor_used = "motion_running_confirmed"
    elif loaded.stage_timing.motion_start_stage_s is not None:
        motion_start_stage_s = float(loaded.stage_timing.motion_start_stage_s)
        timing_anchor_used = "motion_start_legacy"
    elif loaded.stage_timing.motion_command_issued_s is not None:
        motion_start_stage_s = float(loaded.stage_timing.motion_command_issued_s)
        timing_anchor_used = "motion_command_issued"
    else:
        motion_start_stage_s = 0.0
    motion_stop_stage_s = (
        float(loaded.stage_timing.motion_stop_stage_s)
        if loaded.stage_timing.motion_stop_stage_s is not None
        else None
    )
    t_first_s = min(t_video) if t_video else float("nan")
    t_last_s = max(t_video) if t_video else float("nan")
    elapsed_time_s = (t_last_s - t_first_s) if (math.isfinite(t_first_s) and math.isfinite(t_last_s)) else float("nan")
    expected_stage_start_video_s = (
        t_first_s + motion_start_stage_s if math.isfinite(t_first_s) else float("nan")
    )
    expected_stage_stop_video_s = (
        t_first_s + motion_stop_stage_s
        if (math.isfinite(t_first_s) and motion_stop_stage_s is not None)
        else None
    )
    stage_anchor_available = (
        bool(loaded.timestamp_validation_pass)
        and math.isfinite(expected_stage_start_video_s)
        and expected_stage_stop_video_s is not None
        and math.isfinite(expected_stage_stop_video_s)
    )
    requested_anchor_mode = str(config.drag_anchor_mode or "auto")
    if requested_anchor_mode == "stage_validated":
        use_stage_validated_anchor = stage_anchor_available
    elif requested_anchor_mode == "detected_onset":
        use_stage_validated_anchor = False
    else:
        use_stage_validated_anchor = stage_anchor_available
    drag_anchor_mode = "stage_validated" if use_stage_validated_anchor else "detected_onset"

    # Baseline for onset detection: first N seconds of video (video time), not stage time.
    # This avoids n_baseline=0 when video and stage clocks are not aligned yet.
    t0_video = min(t_video) if t_video else 0.0
    baseline_duration_s = max(1.0, getattr(config.window_params, "baseline_duration_s", 3.0))
    baseline_end_for_onset = t0_video + baseline_duration_s
    onset_video_s, alignment_diag = detect_motion_onset(
        t_s=t_video,
        signal=traj_px,
        baseline_end_s=baseline_end_for_onset,
        onset_threshold_sigma=config.onset_threshold_sigma,
        onset_min_hold_s=config.onset_min_hold_s,
    )
    # Fallback: progressively relax threshold (weak bead excursion vs noise)
    used_relaxed_onset = False
    _fail = ("no_excursion_above_threshold", "no_segment_long_enough")
    if onset_video_s is None and alignment_diag.failure_reason in _fail:
        for relaxed_sigma, relaxed_hold in (
            (max(1.8, float(config.onset_threshold_sigma) - 2.0), max(0.12, config.onset_min_hold_s * 0.45)),
            (max(1.35, float(config.onset_threshold_sigma) * 0.38), max(0.08, config.onset_min_hold_s * 0.3)),
        ):
            onset_relaxed, diag_relaxed = detect_motion_onset(
                t_s=t_video,
                signal=traj_px,
                baseline_end_s=baseline_end_for_onset,
                onset_threshold_sigma=float(relaxed_sigma),
                onset_min_hold_s=float(relaxed_hold),
            )
            if onset_relaxed is not None:
                onset_video_s = onset_relaxed
                alignment_diag = diag_relaxed
                used_relaxed_onset = True
                break

    qc = DragQCFlags()
    warnings: list[str] = []

    if requested_anchor_mode == "stage_validated" and not stage_anchor_available:
        warnings.append(
            "PHYSICS_WARNING: drag_anchor_mode=stage_validated was requested but validated stage "
            "start/stop in video time is unavailable (timestamps, trace, or finite expected window); "
            "effective mode is detected_onset for windows."
        )

    if used_relaxed_onset:
        warnings.append("Alignment used relaxed onset detection (lower threshold or shorter min_hold).")

    # Provenance visibility: surface non-authoritative scale/timing inputs explicitly.
    # These warnings are prefixed so oscillatory exports can selectively propagate them.
    if config.um_per_px_source is not None:
        if "default" in str(config.um_per_px_source) or "fallback" in str(config.um_per_px_source) or str(config.um_per_px_source) == "ui_fallback":
            warnings.append(
                f"PROVENANCE_WARNING: um_per_px_source={config.um_per_px_source!r}; "
                "absolute µm physics depends on scale provenance."
            )
    if loaded.paths.used_fallbacks.get("timestamps_path") is not None:
        warnings.append(
            "PROVENANCE_WARNING: Using fallback timestamps sidecar "
            f"({loaded.paths.used_fallbacks['timestamps_path']}); timebase may be legacy-aligned."
        )
    if loaded.paths.used_fallbacks.get("stage_meta_path") is not None:
        warnings.append(
            "PROVENANCE_WARNING: Using fallback stage metadata sidecar "
            f"({loaded.paths.used_fallbacks['stage_meta_path']}); sign/protocol context may differ."
        )

    if onset_video_s is None and config.manual_offset_s is None and not use_stage_validated_anchor:
        qc.alignment_confident = False
        analysis_root = (
            Path(config.current_drag_output_root).resolve()
            if config.current_drag_output_root
            else (Path(loaded.paths.run_dir).resolve() / "analysis")
        )
        fail_audit_dir = analysis_root / "audit"
        fail_results_dir = analysis_root / "results"
        fail_audit_dir.mkdir(parents=True, exist_ok=True)
        fail_results_dir.mkdir(parents=True, exist_ok=True)
        basename = loaded.paths.basename
        # Export alignment failure diagnostics for debugging
        try:
            diag_dict = {
                "baseline_end_s": alignment_diag.baseline_end_s,
                "baseline_median": alignment_diag.baseline_median,
                "baseline_mad": alignment_diag.baseline_mad,
                "baseline_sigma": alignment_diag.baseline_sigma,
                "onset_threshold_sigma": alignment_diag.onset_threshold_sigma,
                "onset_threshold_abs": alignment_diag.onset_threshold_abs,
                "onset_min_hold_s": alignment_diag.onset_min_hold_s,
                "n_baseline_samples": alignment_diag.n_baseline_samples,
                "n_total_samples": alignment_diag.n_total_samples,
                "n_frames_outside_baseline": alignment_diag.n_frames_outside_baseline,
                "candidate_onset_times_s": list(alignment_diag.candidate_onset_times_s),
                "candidate_durations_s": list(alignment_diag.candidate_durations_s),
                "failure_reason": alignment_diag.failure_reason,
                "message": alignment_diag.message,
            }
            failure_json = fail_audit_dir / f"{basename}_alignment_failure.json"
            failure_json.write_text(json.dumps(diag_dict, indent=2, ensure_ascii=False), encoding="utf-8")
            from .plotting import plot_alignment_debug
            debug_png = fail_results_dir / f"{basename}_alignment_debug.png"
            plot_alignment_debug(
                t_s=t_video,
                signal_px=traj_px,
                diagnostics=alignment_diag,
                motion_start_stage_s=motion_start_stage_s,
                motion_stop_stage_s=motion_stop_stage_s,
                output_path=debug_png,
            )
        except Exception:  # noqa: BLE001
            pass
        raise DragAlignmentError(
            "Automatic motion onset detection failed and no manual_offset_s was provided.",
            diagnostics=alignment_diag,
        )

    _raw_detected_onset_s = (
        float(onset_video_s) if onset_video_s is not None and math.isfinite(float(onset_video_s)) else None
    )

    if onset_video_s is None and use_stage_validated_anchor:
        alignment_status = "stage_validated_no_detected_onset"
    elif onset_video_s is None and config.manual_offset_s is not None:
        # Use stage timing with manual offset; synthetic onset at aligned stage time.
        onset_video_s = config.manual_offset_s + motion_start_stage_s
        qc.alignment_confident = False
        alignment_status = "manual_offset"
    else:
        alignment_status = "detected"

    if config.manual_offset_s is not None:
        primary_video_anchor_s = float(config.manual_offset_s) + float(motion_start_stage_s)
        motion_timing_primary_source = "manual_offset"
    elif use_stage_validated_anchor and math.isfinite(expected_stage_start_video_s):
        primary_video_anchor_s = float(expected_stage_start_video_s)
        motion_timing_primary_source = "expected_stage_timing"
    else:
        primary_video_anchor_s = (
            float(onset_video_s)
            if onset_video_s is not None and math.isfinite(float(onset_video_s))
            else float(expected_stage_start_video_s)
        )
        motion_timing_primary_source = "trajectory_detected_onset"

    alignment = build_alignment_result(
        motion_start_stage_s=motion_start_stage_s,
        motion_stop_stage_s=motion_stop_stage_s,
        onset_video_s=primary_video_anchor_s,
        manual_offset_s=config.manual_offset_s,
    )

    if config.export_alignment_debug_plot:
        # Debug-only output: keep plots opt-in (can be heavy in batch).
        try:
            from .plotting import plot_alignment_debug

            analysis_root = (
                Path(config.current_drag_output_root).resolve()
                if config.current_drag_output_root
                else (Path(loaded.paths.run_dir).resolve() / "analysis")
            )
            out_png = analysis_root / "results" / f"{loaded.paths.basename}_alignment_debug.png"
            out_png.parent.mkdir(parents=True, exist_ok=True)
            plot_alignment_debug(
                t_s=t_video,
                signal_px=traj_px,
                diagnostics=alignment_diag,
                motion_start_stage_s=motion_start_stage_s,
                motion_stop_stage_s=motion_stop_stage_s,
                output_path=out_png,
            )
        except Exception as e:  # noqa: BLE001
            warnings.append(f"alignment_debug_plot failed: {e!r}")

    qc_motion_start_video_s = (
        float(_raw_detected_onset_s)
        if (
            use_stage_validated_anchor
            and _raw_detected_onset_s is not None
            and math.isfinite(_raw_detected_onset_s)
        )
        else float(alignment.motion_start_video_s_detected)
    )

    detected_stage_start_for_export = (
        _raw_detected_onset_s
        if use_stage_validated_anchor
        else float(alignment.motion_start_video_s_detected)
    )

    detected_stage_stop_video_s = alignment.motion_stop_video_s_stage_aligned
    stage_video_start_delta_s = (
        float(_raw_detected_onset_s) - float(expected_stage_start_video_s)
        if (
            _raw_detected_onset_s is not None
            and math.isfinite(_raw_detected_onset_s)
            and math.isfinite(expected_stage_start_video_s)
        )
        else None
    )
    stage_video_stop_delta_s = (
        detected_stage_stop_video_s - expected_stage_stop_video_s
        if (
            detected_stage_stop_video_s is not None
            and expected_stage_stop_video_s is not None
            and math.isfinite(detected_stage_stop_video_s)
            and math.isfinite(expected_stage_stop_video_s)
        )
        else None
    )

    stage_anchor_breaking_reasons: list[str] = []
    detected_qc_reasons: list[str] = []
    if math.isfinite(t_first_s) and qc_motion_start_video_s < t_first_s:
        detected_qc_reasons.append("detected_start_before_video_start")
    if (
        math.isfinite(t_last_s)
        and detected_stage_stop_video_s is not None
        and detected_stage_stop_video_s > t_last_s
    ):
        detected_qc_reasons.append("detected_stop_after_video_end")
    if (
        detected_stage_stop_video_s is not None
        and math.isfinite(elapsed_time_s)
        and (detected_stage_stop_video_s - qc_motion_start_video_s) > (elapsed_time_s + 1e-6)
    ):
        detected_qc_reasons.append("aligned_motion_longer_than_video")
    if (
        stage_anchor_available
        and math.isfinite(qc_motion_start_video_s)
        and math.isfinite(expected_stage_start_video_s)
    ):
        start_delta_abs = abs(qc_motion_start_video_s - expected_stage_start_video_s)
    else:
        start_delta_abs = None
    if (
        stage_anchor_available
        and detected_stage_stop_video_s is not None
        and expected_stage_stop_video_s is not None
    ):
        stop_delta_abs = abs(detected_stage_stop_video_s - expected_stage_stop_video_s)
    else:
        stop_delta_abs = None
    if start_delta_abs is not None and start_delta_abs > 1.0:
        detected_qc_reasons.append("detected_start_far_from_expected_stage_start")
    if stop_delta_abs is not None and stop_delta_abs > 1.0:
        detected_qc_reasons.append("detected_stop_far_from_expected_stage_stop")
    if math.isfinite(t_first_s) and math.isfinite(expected_stage_start_video_s):
        if expected_stage_start_video_s < t_first_s:
            stage_anchor_breaking_reasons.append("expected_stage_start_before_video_start")
        if expected_stage_start_video_s > t_last_s:
            stage_anchor_breaking_reasons.append("expected_stage_start_after_video_end")
    if expected_stage_stop_video_s is not None and math.isfinite(t_last_s):
        if expected_stage_stop_video_s > t_last_s:
            stage_anchor_breaking_reasons.append("expected_stage_stop_after_video_end")
        if expected_stage_stop_video_s < t_first_s:
            stage_anchor_breaking_reasons.append("expected_stage_stop_before_video_start")
    if (
        expected_stage_stop_video_s is not None
        and math.isfinite(expected_stage_start_video_s)
        and expected_stage_stop_video_s <= expected_stage_start_video_s
    ):
        stage_anchor_breaking_reasons.append("expected_stage_window_invalid")

    (
        stage_steady_start_s,
        steady_start_marker_source,
        stage_deceleration_start_s,
        deceleration_start_source,
    ) = _estimate_stage_markers(
        loaded.stage_timing,
        loaded.stage_meta.protocol_params,
    )
    steady_state_start_video_s = (
        (t_first_s + float(stage_steady_start_s))
        if (stage_steady_start_s is not None and math.isfinite(t_first_s))
        else None
    )
    if not use_stage_validated_anchor:
        # Keep detected_onset behavior stable: steady start remains onset-anchored.
        steady_state_start_video_s = None
    deceleration_start_video_s = (
        (t_first_s + float(stage_deceleration_start_s))
        if (stage_deceleration_start_s is not None and math.isfinite(t_first_s))
        else None
    )
    if (
        deceleration_start_video_s is not None
        and expected_stage_stop_video_s is not None
        and deceleration_start_video_s >= expected_stage_stop_video_s
    ):
        deceleration_start_video_s = None
        stage_deceleration_start_s = None
        deceleration_start_source = "motion_stop_fallback"

    # 4) Windows
    try:
        primary_motion_start_video_s = (
            float(expected_stage_start_video_s)
            if use_stage_validated_anchor and math.isfinite(expected_stage_start_video_s)
            else alignment.motion_start_video_s_detected
        )
        primary_motion_stop_video_s = (
            float(expected_stage_stop_video_s)
            if use_stage_validated_anchor and expected_stage_stop_video_s is not None
            else alignment.motion_stop_video_s_stage_aligned
        )
        windows_original = compute_windows(
            motion_start_video_s=primary_motion_start_video_s,
            motion_stop_video_s_stage_aligned=primary_motion_stop_video_s,
            params=config.window_params,
            steady_state_start_video_s=steady_state_start_video_s,
            deceleration_start_video_s=deceleration_start_video_s,
        )
        qc.baseline_window_ok = True
        qc.steady_window_ok = True
    except DragWindowError as e:
        qc.baseline_window_ok = False
        qc.steady_window_ok = False
        warnings.append(str(e))
        raise

    baseline_window_original_start_s = windows_original.baseline_start_s
    baseline_window_original_end_s = windows_original.baseline_end_s
    steady_window_original_start_s = windows_original.steady_start_s
    steady_window_original_end_s = windows_original.steady_end_s
    baseline_window_outside_video = False
    steady_window_outside_video = False
    if math.isfinite(t_first_s) and math.isfinite(t_last_s):
        if baseline_window_original_start_s < t_first_s or baseline_window_original_end_s > t_last_s:
            baseline_window_outside_video = True
        if steady_window_original_start_s < t_first_s or steady_window_original_end_s > t_last_s:
            steady_window_outside_video = True

    baseline_window_clipped_start_s = baseline_window_original_start_s
    baseline_window_clipped_end_s = baseline_window_original_end_s
    steady_window_clipped_start_s = steady_window_original_start_s
    steady_window_clipped_end_s = steady_window_original_end_s
    window_clipping_applied = False
    window_clip_reasons: list[str] = []
    if math.isfinite(t_first_s) and math.isfinite(t_last_s):
        baseline_window_clipped_start_s, baseline_window_clipped_end_s, b_clipped = _clip_window_to_video(
            baseline_window_original_start_s,
            baseline_window_original_end_s,
            t_first_s,
            t_last_s,
        )
        steady_window_clipped_start_s, steady_window_clipped_end_s, s_clipped = _clip_window_to_video(
            steady_window_original_start_s,
            steady_window_original_end_s,
            t_first_s,
            t_last_s,
        )
        window_clipping_applied = b_clipped or s_clipped
        if b_clipped:
            window_clip_reasons.append("baseline_window_clipped_to_video_range")
        if s_clipped:
            window_clip_reasons.append("steady_window_clipped_to_video_range")
    if baseline_window_clipped_end_s <= baseline_window_clipped_start_s:
        stage_anchor_breaking_reasons.append("baseline_window_invalid_after_clipping")
        qc.baseline_window_ok = False
    if steady_window_clipped_end_s <= steady_window_clipped_start_s:
        stage_anchor_breaking_reasons.append("steady_window_invalid_after_clipping")
        qc.steady_window_ok = False
    baseline_clip_fraction = 0.0
    steady_clip_fraction = 0.0
    baseline_original_duration = baseline_window_original_end_s - baseline_window_original_start_s
    baseline_clipped_duration = baseline_window_clipped_end_s - baseline_window_clipped_start_s
    if baseline_original_duration > 0:
        baseline_clip_fraction = max(
            0.0,
            1.0 - (baseline_clipped_duration / baseline_original_duration),
        )
    steady_original_duration = steady_window_original_end_s - steady_window_original_start_s
    steady_clipped_duration = steady_window_clipped_end_s - steady_window_clipped_start_s
    if steady_original_duration > 0:
        steady_clip_fraction = max(
            0.0,
            1.0 - (steady_clipped_duration / steady_original_duration),
        )

    windows = DragWindows(
        baseline_start_s=baseline_window_clipped_start_s,
        baseline_end_s=baseline_window_clipped_end_s,
        steady_start_s=steady_window_clipped_start_s,
        steady_end_s=steady_window_clipped_end_s,
    )

    window_clipping_message = ", ".join(window_clip_reasons) if window_clip_reasons else None
    if window_clipping_applied:
        warnings.append(
            "PHYSICS_WARNING: window clipping applied to video bounds: "
            f"{window_clipping_message}."
        )

    # Check steady duration
    steady_duration = windows.steady_end_s - windows.steady_start_s
    if steady_duration < config.window_params.min_steady_duration_s:
        qc.sufficient_steady_duration = False
        warnings.append(
            f"Steady window duration {steady_duration:.3f}s is shorter than "
            f"min_steady_duration_s={config.window_params.min_steady_duration_s:.3f}s."
        )
        if config.strict_steady:
            raise DragWindowError("Steady window too short for strict mode.")

    # 5) Compute baseline / steady medians and offsets
    baseline_px, _baseline_sigma_px, _baseline_n, baseline_px_se = _window_stats(
        t_video,
        traj_px,
        windows.baseline_start_s,
        windows.baseline_end_s,
    )
    steady_px, _steady_sigma_px, _steady_n, steady_px_se = _window_stats(
        t_video,
        traj_px,
        windows.steady_start_s,
        windows.steady_end_s,
    )

    if not (math.isfinite(baseline_px) and math.isfinite(steady_px)):
        qc.offset_detected = False
        warnings.append("Failed to compute baseline or steady median in px.")
        raise DragWindowError("Cannot compute baseline/steady medians.")

    offset_px_raw = steady_px - baseline_px
    offset_px_se = (
        math.sqrt((baseline_px_se**2) + (steady_px_se**2))
        if (math.isfinite(baseline_px_se) and math.isfinite(steady_px_se))
        else None
    )

    # Convert to µm if possible
    baseline_um = steady_um = offset_um_raw = offset_um_se = None
    if um_per_px is not None and um_per_px > 0:
        baseline_um = baseline_px * um_per_px
        steady_um = steady_px * um_per_px
        offset_um_raw = offset_px_raw * um_per_px
        if offset_px_se is not None and math.isfinite(offset_px_se):
            offset_um_se = float(abs(offset_px_se * um_per_px))
    else:
        warnings.append("um_per_px not provided; µm-level positions and offsets are unavailable.")

    # Stage-signed offsets
    sign = (
        loaded.stage_meta.sign_stage_to_image_x
        if axis == "x"
        else loaded.stage_meta.sign_stage_to_image_y
    )
    offset_px_stage_signed = offset_px_raw * float(sign)
    offset_um_stage_signed = offset_um_raw * float(sign) if offset_um_raw is not None else None
    abs_offset_um = abs(offset_um_stage_signed) if offset_um_stage_signed is not None else None

    # Baseline robustness audit (without changing the primary output).
    baseline_reference_start_s = min(t_video) if t_video else float("nan")
    baseline_reference_end_s = alignment_diag.baseline_end_s
    baseline_reference_px = _median_in_window(
        t_video,
        traj_px,
        baseline_reference_start_s,
        baseline_reference_end_s,
    )
    baseline_median_delta_px = (
        baseline_px - baseline_reference_px
        if math.isfinite(baseline_reference_px)
        else float("nan")
    )
    baseline_median_delta_um = (
        baseline_median_delta_px * um_per_px
        if (um_per_px is not None and um_per_px > 0 and math.isfinite(baseline_median_delta_px))
        else None
    )
    offset_alt_baseline_um = None
    eta_alt_baseline = None
    baseline_robustness_flag = "pass"
    baseline_robustness_message = "Baseline strategies agree within tolerance."
    if math.isfinite(baseline_reference_px):
        offset_alt_baseline_um = (
            abs((steady_px - baseline_reference_px) * um_per_px)
            if (um_per_px is not None and um_per_px > 0)
            else None
        )
        sigma_px = float(alignment_diag.baseline_sigma) if math.isfinite(alignment_diag.baseline_sigma) else 0.0
        baseline_delta_threshold_px = max(0.25, 2.0 * sigma_px)
        if abs(float(baseline_median_delta_px)) > baseline_delta_threshold_px:
            baseline_robustness_flag = "suspect"
            baseline_robustness_message = (
                "Near-onset and long pre-motion baseline differ beyond tolerance "
                f"({float(baseline_median_delta_px):.4f}px > {baseline_delta_threshold_px:.4f}px)."
            )
            warnings.append(
                "PHYSICS_WARNING: baseline reference differs from near-onset baseline "
                f"by {float(baseline_median_delta_px):.4f} px (> {baseline_delta_threshold_px:.4f} px)."
            )

    # 6) Stage kinematics
    actual_travel_user = loaded.stage_meta.actual_travel_user
    actual_motion_duration_s = loaded.stage_meta.actual_motion_duration_s
    actual_speed_user_s = loaded.stage_meta.actual_speed_user_s

    stage_um_per_unit = config.stage_um_per_unit or loaded.stage_meta.stage_um_per_unit
    actual_travel_um = loaded.stage_meta.actual_travel_um
    actual_speed_um_s = loaded.stage_meta.actual_speed_um_s
    stage_meta_travel_um = loaded.stage_meta.actual_travel_um
    stage_meta_speed_um_s = loaded.stage_meta.actual_speed_um_s
    stage_um_per_unit_source_actual = config.stage_um_per_unit_source
    if config.stage_um_per_unit is None or not bool(config.stage_um_per_unit):
        stage_um_per_unit_source_actual = "stage_meta_fallback" if "stage_meta_path" in loaded.paths.used_fallbacks else "stage_meta"
    if stage_um_per_unit_source_actual is not None and (
        stage_um_per_unit_source_actual == "default"
        or "fallback" in str(stage_um_per_unit_source_actual)
        or stage_um_per_unit_source_actual == "ui_override"
    ):
        warnings.append(
            "PROVENANCE_WARNING: stage_um_per_unit derived from non-authoritative source "
            f"({stage_um_per_unit_source_actual!r}); absolute drag physics may be scientifically risky."
        )
    if actual_speed_um_s is None:
        if stage_um_per_unit is not None and stage_um_per_unit > 0:
            actual_travel_um = actual_travel_user * stage_um_per_unit
            actual_speed_um_s = actual_speed_user_s * stage_um_per_unit
        else:
            qc.stage_speed_available = True  # user-speed exists, but not in µm
            warnings.append("stage_um_per_unit not provided; absolute drag physics may be incomplete.")
    # If actual_speed_um_s is still missing, we can proceed with signal-level outputs
    # but physics requiring SI units will remain incomplete.

    # Export/provenance: make motion kinematics semantics explicit.
    motion_kinematics_source = loaded.stage_meta.kinematics_source
    if motion_kinematics_source == "legacy_user_units":
        if actual_speed_um_s is not None:
            non_authoritative = (
                stage_um_per_unit_source_actual is not None
                and (
                    stage_um_per_unit_source_actual == "default"
                    or stage_um_per_unit_source_actual == "ui_override"
                    or "fallback" in str(stage_um_per_unit_source_actual)
                )
            )
            motion_kinematics_source = (
                "legacy_user_units_via_stage_um_per_unit_non_authoritative"
                if non_authoritative
                else "legacy_user_units_via_stage_um_per_unit"
            )
    elif motion_kinematics_source == "actual_metric":
        # If only part of actual_metric was present, remaining parts may have been derived via legacy conversion.
        derived_any = (
            (stage_meta_travel_um is None and actual_travel_um is not None)
            or (stage_meta_speed_um_s is None and actual_speed_um_s is not None)
        )
        if derived_any:
            motion_kinematics_source = "actual_metric_partial_plus_legacy_conversion"

    stage_speed_from_trace_um_s = None
    stage_speed_relative_diff = None
    stage_speed_consistent = None
    kinematics_robustness_flag = "pass"
    kinematics_robustness_message = "Stage speed checks are within tolerance."
    if (
        loaded.stage_timing.motion_stop_stage_s is not None
        and loaded.stage_timing.motion_start_stage_s is not None
    ):
        trace_duration = float(loaded.stage_timing.motion_stop_stage_s) - float(loaded.stage_timing.motion_start_stage_s)
        if trace_duration > 0 and math.isfinite(trace_duration):
            trace_speed_user_s = float(actual_travel_user) / trace_duration
            if stage_um_per_unit is not None and stage_um_per_unit > 0:
                stage_speed_from_trace_um_s = trace_speed_user_s * float(stage_um_per_unit)
                if actual_speed_um_s is not None and actual_speed_um_s > 0:
                    stage_speed_relative_diff = abs(stage_speed_from_trace_um_s - actual_speed_um_s) / abs(actual_speed_um_s)
                    stage_speed_consistent = stage_speed_relative_diff <= 0.05
    if motion_kinematics_source is not None and "legacy_user_units" in str(motion_kinematics_source):
        kinematics_robustness_flag = "suspect"
        kinematics_robustness_message = (
            "Kinematics are derived via legacy_user_units_via_stage_um_per_unit mapping."
        )
        warnings.append(
            "PHYSICS_WARNING: kinematics use legacy user-units conversion via stage_um_per_unit."
        )
    if stage_speed_consistent is False:
        kinematics_robustness_flag = "fail"
        kinematics_robustness_message = (
            "Stage speed mismatch between stage.json and trace-derived estimate exceeds tolerance."
        )
        warnings.append(
            "PHYSICS_WARNING: speed from stage trace and summary speed differ by "
            f"{(stage_speed_relative_diff or 0.0) * 100:.2f}%."
        )

    # 7) Physics layer (optional)
    drag_force_n = kappa_n_per_m = kappa_pn_per_um = eta_pa_s = None
    drag_force_n_se = kappa_n_per_m_se = kappa_pn_per_um_se = eta_pa_s_se = None
    physics_status = "incomplete_inputs"

    radius_um = None
    if config.bead_radius_um is not None:
        radius_um = config.bead_radius_um
    elif config.bead_diameter_um is not None:
        radius_um = 0.5 * config.bead_diameter_um

    radius_m = radius_um * 1e-6 if radius_um is not None else None

    # Physics readiness check: all key inputs must be present and non-zero
    physics_inputs_ok = (
        radius_m is not None
        and actual_speed_um_s is not None
        and abs_offset_um is not None
        and abs_offset_um > 0
        and um_per_px is not None
        and um_per_px > 0
        and stage_um_per_unit is not None
        and stage_um_per_unit > 0
        and (
            (config.kappa_n_per_m is not None and config.kappa_n_per_m > 0)
            or (config.eta_pa_s is not None and config.eta_pa_s > 0)
        )
    )

    if physics_inputs_ok:
        v_m_s = actual_speed_um_s * 1e-6
        offset_m = offset_um_stage_signed * 1e-6 if offset_um_stage_signed is not None else None
        # Sign-safe inversion: velocity is treated as a positive magnitude and
        # displacement sign should not flip inferred viscosity/stiffness
        # magnitudes. Keep signed offsets only for reporting.
        offset_m_mag = abs(offset_m) if offset_m is not None else None
        try:
            if offset_m_mag is not None and offset_m_mag != 0:
                if config.eta_pa_s is not None:
                    drag_force_n = compute_drag_force(config.eta_pa_s, radius_m, v_m_s)
                    kappa_n_per_m = compute_kappa_from_drag(
                        config.eta_pa_s,
                        radius_m,
                        v_m_s,
                        offset_m_mag,
                    )
                    # N/m -> pN/µm: 1 N = 1e12 pN and 1 m = 1e6 µm => 1 N/m = 1e6 pN/µm
                    kappa_pn_per_um = abs(kappa_n_per_m) * 1e6
                    eta_pa_s = config.eta_pa_s
                    physics_status = "ready"
                    qc.physics_ready = True
                elif config.kappa_n_per_m is not None and config.kappa_n_per_m > 0:
                    eta_pa_s = compute_eta_from_drag(
                        config.kappa_n_per_m,
                        radius_m,
                        v_m_s,
                        offset_m_mag,
                    )
                    drag_force_n = compute_drag_force(eta_pa_s, radius_m, v_m_s)
                    kappa_n_per_m = config.kappa_n_per_m
                    kappa_n_per_m_se = (
                        float(config.kappa_n_per_m_se)
                        if (config.kappa_n_per_m_se is not None and float(config.kappa_n_per_m_se) > 0)
                        else None
                    )
                    # N/m -> pN/µm: 1 N/m = 1e6 pN/µm
                    kappa_pn_per_um = abs(kappa_n_per_m) * 1e6
                    if kappa_n_per_m_se is not None:
                        kappa_pn_per_um_se = abs(kappa_n_per_m_se) * 1e6
                    physics_status = "ready"
                    qc.physics_ready = True
        except DragPhysicsError as e:
            warnings.append(f"Physics layer skipped due to invalid inputs: {e}")
            physics_status = "incomplete_inputs"

    eta_current_windows = eta_pa_s
    offset_current_windows_um = abs_offset_um
    if (
        config.kappa_n_per_m is not None
        and config.kappa_n_per_m > 0
        and offset_alt_baseline_um is not None
        and actual_speed_um_s is not None
        and actual_speed_um_s > 0
        and radius_m is not None
    ):
        try:
            eta_alt_baseline = compute_eta_from_drag(
                config.kappa_n_per_m,
                radius_m,
                actual_speed_um_s * 1e-6,
                abs(offset_alt_baseline_um) * 1e-6,
            )
        except Exception:  # noqa: BLE001
            eta_alt_baseline = None

    competing_candidates, onset_candidate_density, onset_ambiguity_score, onset_confidence_class = _classify_onset_ambiguity(
        candidate_count=len(alignment_diag.candidate_onset_times_s),
        candidate_durations=alignment_diag.candidate_durations_s,
        min_hold_s=alignment_diag.onset_min_hold_s,
        used_relaxed_onset=used_relaxed_onset,
    )
    onset_robustness_flag = "pass" if onset_confidence_class == "high" else ("suspect" if onset_confidence_class == "medium" else "fail")
    onset_robustness_message = (
        "Onset candidate set is clean and stable."
        if onset_robustness_flag == "pass"
        else (
            "Onset has ambiguity but remains usable."
            if onset_robustness_flag == "suspect"
            else "Onset ambiguity is high; motion partition may be unreliable."
        )
    )
    if onset_robustness_flag != "pass":
        warnings.append(
            "PHYSICS_WARNING: onset ambiguity classified as "
            f"{onset_confidence_class} (score={onset_ambiguity_score:.2f})."
        )
    alignment_diag = type(alignment_diag)(
        baseline_end_s=alignment_diag.baseline_end_s,
        baseline_median=alignment_diag.baseline_median,
        baseline_mad=alignment_diag.baseline_mad,
        baseline_sigma=alignment_diag.baseline_sigma,
        onset_threshold_sigma=alignment_diag.onset_threshold_sigma,
        onset_threshold_abs=alignment_diag.onset_threshold_abs,
        onset_min_hold_s=alignment_diag.onset_min_hold_s,
        n_baseline_samples=alignment_diag.n_baseline_samples,
        n_total_samples=alignment_diag.n_total_samples,
        n_frames_outside_baseline=alignment_diag.n_frames_outside_baseline,
        candidate_onset_times_s=alignment_diag.candidate_onset_times_s,
        candidate_durations_s=alignment_diag.candidate_durations_s,
        failure_reason=alignment_diag.failure_reason,
        message=alignment_diag.message,
        onset_relaxed_used=used_relaxed_onset,
        onset_competing_durable_candidates=competing_candidates,
        onset_ambiguity_score=onset_ambiguity_score,
        onset_confidence_class=onset_confidence_class,
        onset_candidate_density=onset_candidate_density,
    )

    detected_onset_consistency_flag = True
    detected_onset_consistency_message = "detected timing agrees with stage expectation."
    if start_delta_abs is not None and stop_delta_abs is not None:
        worst_delta = max(start_delta_abs, stop_delta_abs)
    elif start_delta_abs is not None:
        worst_delta = start_delta_abs
    else:
        worst_delta = stop_delta_abs
    if _raw_detected_onset_s is None:
        detected_onset_consistency_flag = False
        detected_onset_consistency_message = (
            "detected onset unavailable; stage timing used as primary anchor."
            if use_stage_validated_anchor
            else "trajectory onset unavailable; alignment uses expected stage timing fallback."
        )
    elif worst_delta is not None:
        if worst_delta > 2.0:
            detected_onset_consistency_flag = False
            detected_onset_consistency_message = (
                f"detected timing strongly differs from expected stage timing (max_delta={worst_delta:.3f}s)."
            )
        elif worst_delta > 0.5:
            detected_onset_consistency_message = (
                f"detected timing moderately differs from expected stage timing (max_delta={worst_delta:.3f}s)."
            )

    # Stage-anchor *messaging* must not treat expected-stage time as a surrogate "detected"
    # onset when no independent trajectory onset exists (worst_delta can be 0 from that tautology).
    _independent_detected_onset = (
        _raw_detected_onset_s is not None and math.isfinite(float(_raw_detected_onset_s))
    )
    if stage_anchor_available:
        if not _independent_detected_onset:
            stage_anchor_reason = "stage timing available; detected onset missing."
            stage_anchor_confidence = "high" if not stage_anchor_breaking_reasons else "medium"
        elif worst_delta is None:
            stage_anchor_confidence = "medium"
            stage_anchor_reason = "stage timing available; detected onset missing."
        elif worst_delta <= 0.5:
            stage_anchor_confidence = "high"
            stage_anchor_reason = "stage and detected timing are consistent."
        elif worst_delta <= 2.0:
            stage_anchor_confidence = "medium"
            stage_anchor_reason = "stage truth retained as primary; detected timing only partially consistent."
        else:
            stage_anchor_confidence = "high"
            stage_anchor_reason = (
                "stage truth retained as primary because detected timing is strongly inconsistent."
            )
    else:
        stage_anchor_confidence = "low"
        stage_anchor_reason = "validated stage anchors are unavailable."

    alignment_sanity_flag = len(stage_anchor_breaking_reasons) == 0
    alignment_sanity_message = (
        "alignment_sanity_ok"
        if alignment_sanity_flag
        else ", ".join(stage_anchor_breaking_reasons)
    )
    if not alignment_sanity_flag:
        warnings.append(f"PHYSICS_WARNING: alignment sanity failed: {alignment_sanity_message}.")
        qc.physics_ready = False
        if physics_status == "ready":
            physics_status = "suspect_alignment_sanity"
    warnings_phys = []
    if baseline_robustness_flag != "pass":
        warnings_phys.append("baseline sensitivity")
    if onset_robustness_flag != "pass":
        warnings_phys.append("onset ambiguity")
    if kinematics_robustness_flag != "pass":
        warnings_phys.append("kinematics source/risk")
    drag_physics_warning = ", ".join(warnings_phys) if warnings_phys else None

    baseline_strategy_primary = (
        "near_onset_baseline"
        if drag_anchor_mode == "detected_onset"
        else "stage_validated_baseline"
    )
    baseline_strategy_alt = "long_premotion_baseline_reference"
    baseline_position_primary_px = baseline_px
    baseline_position_primary_um = baseline_um
    baseline_position_alt_px = baseline_reference_px if math.isfinite(baseline_reference_px) else None
    baseline_position_alt_um = (
        baseline_position_alt_px * um_per_px
        if (baseline_position_alt_px is not None and um_per_px is not None and um_per_px > 0)
        else None
    )
    offset_primary_um = abs_offset_um
    offset_alt_um = offset_alt_baseline_um
    eta_primary_pa_s = eta_current_windows
    eta_alt_pa_s = eta_alt_baseline
    baseline_strategy_difference_ratio = None
    if eta_primary_pa_s is not None and eta_primary_pa_s > 0 and eta_alt_pa_s is not None and eta_alt_pa_s > 0:
        baseline_strategy_difference_ratio = max(eta_primary_pa_s, eta_alt_pa_s) / min(eta_primary_pa_s, eta_alt_pa_s)
        if baseline_strategy_difference_ratio > 1.5 and baseline_robustness_flag == "pass":
            baseline_robustness_flag = "suspect"
            baseline_robustness_message = (
                "Eta differs strongly between baseline strategies "
                f"(ratio={baseline_strategy_difference_ratio:.3f})."
            )

    speed_stage_json = actual_speed_um_s
    speed_trace_derived = stage_speed_from_trace_um_s
    speed_used_for_physics = actual_speed_um_s
    actual_speed_um_s_se = None
    if (
        actual_speed_um_s is not None
        and stage_speed_from_trace_um_s is not None
        and math.isfinite(actual_speed_um_s)
        and math.isfinite(stage_speed_from_trace_um_s)
    ):
        actual_speed_um_s_se = abs(float(actual_speed_um_s) - float(stage_speed_from_trace_um_s))
    elif (
        actual_speed_um_s is not None
        and stage_speed_relative_diff is not None
        and math.isfinite(actual_speed_um_s)
        and math.isfinite(stage_speed_relative_diff)
        and stage_speed_relative_diff >= 0
    ):
        actual_speed_um_s_se = abs(float(actual_speed_um_s) * float(stage_speed_relative_diff))
    speed_consistency_error_pct = (
        (stage_speed_relative_diff * 100.0)
        if stage_speed_relative_diff is not None
        else None
    )

    rel_terms_force: list[float] = []
    rel_terms_eta: list[float] = []
    if kappa_n_per_m is not None and kappa_n_per_m > 0 and kappa_n_per_m_se is not None and kappa_n_per_m_se > 0:
        rel_terms_force.append(abs(kappa_n_per_m_se) / abs(kappa_n_per_m))
        rel_terms_eta.append(abs(kappa_n_per_m_se) / abs(kappa_n_per_m))
    if abs_offset_um is not None and abs_offset_um > 0 and offset_um_se is not None and offset_um_se > 0:
        rel = abs(offset_um_se) / abs(abs_offset_um)
        rel_terms_force.append(rel)
        rel_terms_eta.append(rel)
    if actual_speed_um_s is not None and actual_speed_um_s > 0 and actual_speed_um_s_se is not None and actual_speed_um_s_se > 0:
        rel_terms_eta.append(abs(actual_speed_um_s_se) / abs(actual_speed_um_s))

    if drag_force_n is not None and rel_terms_force:
        drag_force_n_se = abs(float(drag_force_n)) * math.sqrt(sum(r * r for r in rel_terms_force))
    if eta_pa_s is not None and rel_terms_eta:
        eta_pa_s_se = abs(float(eta_pa_s)) * math.sqrt(sum(r * r for r in rel_terms_eta))

    expected_offset_if_eta_1mPas_um = None
    expected_offset_if_eta_from_baseline_um = None
    measured_offset_um = abs_offset_um
    offset_underestimation_ratio_vs_water = None
    offset_underestimation_ratio_vs_baseline = None
    if (
        config.kappa_n_per_m is not None
        and config.kappa_n_per_m > 0
        and actual_speed_um_s is not None
        and actual_speed_um_s > 0
        and radius_m is not None
    ):
        speed_m_s = actual_speed_um_s * 1e-6
        force_water = compute_drag_force(0.001, radius_m, speed_m_s)
        expected_offset_if_eta_1mPas_um = (force_water / config.kappa_n_per_m) * 1e6
        if measured_offset_um is not None and expected_offset_if_eta_1mPas_um > 0:
            offset_underestimation_ratio_vs_water = measured_offset_um / expected_offset_if_eta_1mPas_um
        if eta_alt_pa_s is not None and eta_alt_pa_s > 0:
            force_alt = compute_drag_force(eta_alt_pa_s, radius_m, speed_m_s)
            expected_offset_if_eta_from_baseline_um = (force_alt / config.kappa_n_per_m) * 1e6
            if measured_offset_um is not None and expected_offset_if_eta_from_baseline_um > 0:
                offset_underestimation_ratio_vs_baseline = measured_offset_um / expected_offset_if_eta_from_baseline_um

    plausibility_flag = "unknown"
    if offset_underestimation_ratio_vs_water is not None:
        ratio = float(offset_underestimation_ratio_vs_water)
        if 0.4 <= ratio <= 2.5:
            plausibility_flag = "pass"
        elif 0.25 <= ratio <= 4.0:
            plausibility_flag = "suspect"
        else:
            plausibility_flag = "fail"

    clipping_flag = "pass"
    baseline_duration_after_clip = windows.baseline_end_s - windows.baseline_start_s
    min_baseline_duration_s = max(0.1, float(config.window_params.min_baseline_duration_s))
    baseline_clip_hard_fail = baseline_duration_after_clip < min_baseline_duration_s
    if steady_clip_fraction > 0.35 or baseline_clip_hard_fail:
        clipping_flag = "fail"
    elif (
        steady_clip_fraction > 0.1
        or baseline_clip_fraction > 0.1
        or baseline_window_outside_video
        or steady_window_outside_video
    ):
        clipping_flag = "suspect"
    if baseline_clip_hard_fail:
        warnings.append(
            "PHYSICS_WARNING: baseline window after clipping is too short "
            f"({baseline_duration_after_clip:.3f}s < min_baseline_duration_s={min_baseline_duration_s:.3f}s)."
        )

    physics_primary_reasons: list[str] = []
    if not alignment_sanity_flag:
        physics_primary_reasons.extend(stage_anchor_breaking_reasons)
    if baseline_robustness_flag == "fail":
        physics_primary_reasons.append("baseline_fail")
    elif baseline_robustness_flag == "suspect":
        physics_primary_reasons.append("baseline_suspect")
    if kinematics_robustness_flag == "fail":
        physics_primary_reasons.append("kinematics_fail")
    elif kinematics_robustness_flag == "suspect":
        physics_primary_reasons.append("kinematics_suspect")
    if clipping_flag == "fail":
        physics_primary_reasons.append("window_clipping_severe")
    elif clipping_flag == "suspect":
        physics_primary_reasons.append("window_clipping_minor")
    if physics_status != "ready":
        physics_primary_reasons.append("physics_not_ready")
    if plausibility_flag == "fail":
        physics_primary_reasons.append("plausibility_fail")
    elif plausibility_flag == "suspect":
        physics_primary_reasons.append("plausibility_suspect")

    if any(
        reason in physics_primary_reasons
        for reason in (
            "physics_not_ready",
            "baseline_fail",
            "kinematics_fail",
            "window_clipping_severe",
            "plausibility_fail",
        )
    ) or not alignment_sanity_flag:
        physics_primary_gate = "fail"
    elif physics_primary_reasons:
        physics_primary_gate = "suspect"
    else:
        physics_primary_gate = "pass"

    detection_qc_reasons_final: list[str] = []
    if not detected_onset_consistency_flag:
        detection_qc_reasons_final.append("detected_onset_inconsistent_with_stage")
    detection_qc_reasons_final.extend(detected_qc_reasons)
    if onset_robustness_flag == "fail":
        detection_qc_reasons_final.append("onset_fail")
    elif onset_robustness_flag == "suspect":
        detection_qc_reasons_final.append("onset_suspect")
    if used_relaxed_onset:
        detection_qc_reasons_final.append("relaxed_onset_used")
    if any(
        reason in detection_qc_reasons_final
        for reason in ("detected_onset_inconsistent_with_stage", "onset_fail")
    ):
        detection_qc_gate = "fail"
    elif detection_qc_reasons_final:
        detection_qc_gate = "suspect"
    else:
        detection_qc_gate = "pass"

    if physics_primary_gate == "fail":
        final_drag_verdict = "fail"
    elif detection_qc_gate == "fail":
        final_drag_verdict = "suspect"
    elif physics_primary_gate == "pass" and detection_qc_gate == "pass":
        final_drag_verdict = "pass"
    else:
        final_drag_verdict = "suspect"
    final_reasons = [f"physics_primary={physics_primary_gate}", f"detection_qc={detection_qc_gate}"]
    final_reasons.extend(physics_primary_reasons)
    final_reasons.extend(detection_qc_reasons_final)
    final_drag_reason = ", ".join(dict.fromkeys(final_reasons))

    detected_onset_qc_only = (
        drag_anchor_mode == "stage_validated"
        and physics_primary_gate in {"pass", "suspect"}
        and detection_qc_gate == "fail"
    )
    detected_onset_veto_applied = (
        drag_anchor_mode == "stage_validated"
        and detection_qc_gate == "fail"
        and final_drag_verdict == "fail"
    )
    stage_validated_physics_acceptable = (
        drag_anchor_mode == "stage_validated"
        and physics_primary_gate in {"pass", "suspect"}
        and physics_status == "ready"
        and baseline_robustness_flag == "pass"
        and kinematics_robustness_flag in {"pass", "suspect"}
        and clipping_flag != "fail"
        and plausibility_flag in {"pass", "suspect", "unknown"}
    )

    if physics_primary_gate == "fail":
        drag_physics_confidence = "low"
    elif physics_primary_gate == "suspect" or detection_qc_gate == "fail":
        drag_physics_confidence = "medium"
    else:
        drag_physics_confidence = "high"

    drag_validation_gate = final_drag_verdict
    drag_validation_reason = final_drag_reason
    primary_timing_source_for_windows = (
        "expected_stage_start_stop"
        if drag_anchor_mode == "stage_validated"
        else "trajectory_detected_onset"
    )

    # Overall analysis status
    analysis_status = "ok"
    if (
        not qc.alignment_confident
        or not qc.sufficient_steady_duration
        or not qc.offset_detected
        or not alignment_sanity_flag
    ):
        analysis_status = "warning"

    commanded_travel_user_ref = None
    commanded_speed_user_s_ref = None
    commanded_metric = loaded.stage_meta.protocol_params.get("commanded_metric")
    if isinstance(commanded_metric, dict):
        try:
            if commanded_metric.get("commanded_travel_user") is not None:
                commanded_travel_user_ref = float(commanded_metric.get("commanded_travel_user"))
        except Exception:  # noqa: BLE001
            commanded_travel_user_ref = None
        try:
            if commanded_metric.get("commanded_speed_user_s") is not None:
                commanded_speed_user_s_ref = float(commanded_metric.get("commanded_speed_user_s"))
        except Exception:  # noqa: BLE001
            commanded_speed_user_s_ref = None

    return DragAnalysisResult(
        basename=loaded.paths.basename,
        axis=axis,
        analysis_axis=axis,
        stage_axis=stage_axis,
        alignment_offset_s=alignment.alignment_offset_s,
        motion_start_stage_s=alignment.motion_start_stage_s,
        motion_stop_stage_s=alignment.motion_stop_stage_s,
        motion_start_video_s_detected=alignment.motion_start_video_s_detected,
        motion_stop_video_s_stage_aligned=alignment.motion_stop_video_s_stage_aligned,
        windows=windows,
        baseline_position_px=baseline_px,
        steady_position_px=steady_px,
        baseline_position_um=baseline_um,
        steady_position_um=steady_um,
        offset_px_raw=offset_px_raw,
        offset_um_raw=offset_um_raw,
        offset_px_stage_signed=offset_px_stage_signed,
        offset_um_stage_signed=offset_um_stage_signed,
        abs_offset_um=abs_offset_um,
        actual_travel_user=actual_travel_user,
        actual_motion_duration_s=actual_motion_duration_s,
        actual_speed_user_s=actual_speed_user_s,
        actual_travel_um=actual_travel_um,
        actual_speed_um_s=actual_speed_um_s,
        drag_force_n=drag_force_n,
        drag_force_n_se=drag_force_n_se,
        kappa_n_per_m=kappa_n_per_m,
        kappa_n_per_m_se=kappa_n_per_m_se,
        kappa_pn_per_um=kappa_pn_per_um,
        kappa_pn_per_um_se=kappa_pn_per_um_se,
        eta_pa_s=eta_pa_s,
        eta_pa_s_se=eta_pa_s_se,
        offset_um_se=offset_um_se,
        actual_speed_um_s_se=actual_speed_um_s_se,
        analysis_status=analysis_status,
        alignment_status=alignment_status,
        physics_status=physics_status,
        qc_flags=qc,
        warnings=warnings,
        notes=[],
        alignment_diagnostics=(alignment_diag if config.export_alignment_diagnostics_json else None),
        # Provenance/auditability (paths resolved by DRAG loader + scale origins from pipeline).
        protocol_type="constant_velocity",
        um_per_px_source=config.um_per_px_source,
        stage_um_per_unit_source=stage_um_per_unit_source_actual,
        kappa_source=config.kappa_source,
        selected_calibration_path=config.selected_calibration_path,
        selected_stage_meta_path=str(loaded.paths.stage_meta_path),
        selected_stage_trace_path=str(loaded.paths.stage_trace_path),
        selected_timestamps_path=str(loaded.paths.timestamps_path),
        selected_trajectory_path=(
            str(loaded.paths.trajectory_path) if loaded.paths.trajectory_path is not None else None
        ),
        current_drag_input_path=config.current_drag_input_path,
        current_drag_item_root=config.current_drag_item_root,
        brownian_baseline_folder=config.brownian_baseline_folder,
        baseline_selection_mode=config.baseline_selection_mode,
        drag_preflight_status=config.drag_preflight_status,
        drag_preflight_message=config.drag_preflight_message,
        current_drag_output_root=config.current_drag_output_root,
        current_drag_report_path=None,
        current_drag_summary_json_path=None,
        current_drag_summary_csv_path=None,
        current_drag_diagnostic_png_path=None,
        current_drag_alignment_json_path=None,
        used_fallbacks=dict(loaded.paths.used_fallbacks),
        artifact_selection=dict(loaded.paths.artifact_selection),
        timing_source=(
            f"timestamps_csv:{loaded.paths.timestamps_path.name}"
            + (" (fallback)" if loaded.paths.used_fallbacks.get("timestamps_path") is not None else "")
            + f";stage_anchor={timing_anchor_used}"
        ),
        motion_kinematics_source=motion_kinematics_source,
        timestamp_validation_pass=bool(loaded.timestamp_validation_pass),
        timestamp_validation_message=str(loaded.timestamp_validation_message),
        report_source_kind="drag_summary",
        report_source_path=None,
        alignment_message=alignment_diag.message,
        commanded_travel_user_ref=commanded_travel_user_ref,
        commanded_speed_user_s_ref=commanded_speed_user_s_ref,
        offset_current_windows_um=offset_current_windows_um,
        offset_alt_baseline_um=offset_alt_baseline_um,
        eta_current_windows=eta_current_windows,
        eta_alt_baseline=eta_alt_baseline,
        baseline_reference_median_px=baseline_reference_px if math.isfinite(baseline_reference_px) else None,
        baseline_reference_window_start_s=baseline_reference_start_s if math.isfinite(baseline_reference_start_s) else None,
        baseline_reference_window_end_s=baseline_reference_end_s if math.isfinite(baseline_reference_end_s) else None,
        baseline_median_delta_px=baseline_median_delta_px if math.isfinite(baseline_median_delta_px) else None,
        baseline_median_delta_um=baseline_median_delta_um,
        stage_speed_from_trace_um_s=stage_speed_from_trace_um_s,
        stage_speed_relative_diff=stage_speed_relative_diff,
        stage_speed_consistent=stage_speed_consistent,
        drag_physics_confidence=drag_physics_confidence,
        drag_physics_warning=drag_physics_warning,
        baseline_robustness_flag=baseline_robustness_flag,
        onset_robustness_flag=onset_robustness_flag,
        kinematics_robustness_flag=kinematics_robustness_flag,
        baseline_robustness_message=baseline_robustness_message,
        onset_robustness_message=onset_robustness_message,
        kinematics_robustness_message=kinematics_robustness_message,
        baseline_strategy_primary=baseline_strategy_primary,
        baseline_strategy_alt=baseline_strategy_alt,
        baseline_position_primary_px=baseline_position_primary_px,
        baseline_position_primary_um=baseline_position_primary_um,
        baseline_position_alt_px=baseline_position_alt_px,
        baseline_position_alt_um=baseline_position_alt_um,
        offset_primary_um=offset_primary_um,
        offset_alt_um=offset_alt_um,
        eta_primary_pa_s=eta_primary_pa_s,
        eta_alt_pa_s=eta_alt_pa_s,
        baseline_strategy_difference_ratio=baseline_strategy_difference_ratio,
        relaxed_onset_used=used_relaxed_onset,
        competing_durable_candidates_count=competing_candidates,
        onset_candidate_density=onset_candidate_density,
        speed_stage_json=speed_stage_json,
        speed_trace_derived=speed_trace_derived,
        speed_used_for_physics=speed_used_for_physics,
        speed_consistency_error_pct=speed_consistency_error_pct,
        expected_offset_if_eta_1mPas_um=expected_offset_if_eta_1mPas_um,
        expected_offset_if_eta_from_baseline_um=expected_offset_if_eta_from_baseline_um,
        measured_offset_um=measured_offset_um,
        offset_underestimation_ratio_vs_water=offset_underestimation_ratio_vs_water,
        offset_underestimation_ratio_vs_baseline=offset_underestimation_ratio_vs_baseline,
        drag_validation_gate=drag_validation_gate,
        drag_validation_reason=drag_validation_reason,
        t_first_s=t_first_s if math.isfinite(t_first_s) else None,
        t_last_s=t_last_s if math.isfinite(t_last_s) else None,
        elapsed_time_s=elapsed_time_s if math.isfinite(elapsed_time_s) else None,
        expected_stage_start_video_s=expected_stage_start_video_s if math.isfinite(expected_stage_start_video_s) else None,
        expected_stage_stop_video_s=expected_stage_stop_video_s,
        detected_stage_start_video_s=detected_stage_start_for_export,
        detected_stage_stop_video_s=detected_stage_stop_video_s,
        stage_video_start_delta_s=stage_video_start_delta_s,
        stage_video_stop_delta_s=stage_video_stop_delta_s,
        alignment_sanity_flag=alignment_sanity_flag,
        alignment_sanity_message=alignment_sanity_message,
        baseline_window_original_start_s=baseline_window_original_start_s,
        baseline_window_original_end_s=baseline_window_original_end_s,
        steady_window_original_start_s=steady_window_original_start_s,
        steady_window_original_end_s=steady_window_original_end_s,
        baseline_window_clipped_start_s=baseline_window_clipped_start_s,
        baseline_window_clipped_end_s=baseline_window_clipped_end_s,
        steady_window_clipped_start_s=steady_window_clipped_start_s,
        steady_window_clipped_end_s=steady_window_clipped_end_s,
        window_clipping_applied=window_clipping_applied,
        window_clipping_message=window_clipping_message,
        drag_anchor_mode_requested=str(requested_anchor_mode),
        drag_anchor_mode=drag_anchor_mode,
        primary_timing_source_for_windows=primary_timing_source_for_windows,
        motion_timing_primary_source=motion_timing_primary_source,
        detected_onset_video_s=_raw_detected_onset_s,
        detected_onset_diagnostic_only=(drag_anchor_mode == "stage_validated"),
        detected_onset_consistency_flag=detected_onset_consistency_flag,
        detected_onset_consistency_message=detected_onset_consistency_message,
        stage_anchor_confidence=stage_anchor_confidence,
        stage_anchor_reason=stage_anchor_reason,
        steady_start_marker_source=steady_start_marker_source,
        steady_end_marker_source=(
            "deceleration_start_minus_guard"
            if deceleration_start_video_s is not None
            else "motion_stop_minus_guard"
        ),
        deceleration_start_stage_s=stage_deceleration_start_s,
        deceleration_start_video_s=deceleration_start_video_s,
        deceleration_start_source=deceleration_start_source,
        steady_state_start_stage_s=stage_steady_start_s,
        steady_state_start_video_s=steady_state_start_video_s,
        physics_primary_gate=physics_primary_gate,
        detection_qc_gate=detection_qc_gate,
        final_drag_verdict=final_drag_verdict,
        final_drag_reason=final_drag_reason,
        stage_validated_physics_acceptable=stage_validated_physics_acceptable,
        detected_onset_qc_only=detected_onset_qc_only,
        detected_onset_veto_applied=detected_onset_veto_applied,
        trajectory_source_kind=_traj_kind,
        trajectory_generated_in_this_workflow=_traj_gen,
    )

