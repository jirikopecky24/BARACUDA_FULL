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
    DragWindowParams,
)
from .windows import compute_windows, DragWindowError


def _interp_time_for_frames(
    frame_indices: Sequence[int],
    frame_times: Sequence[float],
    target_frames: Sequence[int],
) -> list[float]:
    """Map trajectory frame indices to video timestamps via nearest neighbor."""
    if not frame_indices or not frame_times or len(frame_indices) != len(frame_times):
        raise ValueError("Invalid frame_indices/frame_times inputs")
    index_to_time = {int(f): float(t) for f, t in zip(frame_indices, frame_times)}
    out: list[float] = []
    for fi in target_frames:
        t = index_to_time.get(int(fi))
        if t is None:
            # Fallback: use first or last known time
            if fi < min(index_to_time.keys()):
                t = frame_times[0]
            else:
                t = frame_times[-1]
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


def analyze_drag_run(
    run_dir: Path,
    config: DragAnalysisConfig,
    trajectory_path: Path | None = None,
) -> DragAnalysisResult:
    """High-level entry point: perform DRAG analysis for a single run folder."""
    loaded: DragRunLoaded = load_drag_run(Path(run_dir), trajectory_path=trajectory_path)

    axis = config.analysis_axis
    um_per_px = config.um_per_px

    # 1) Extract trajectory along requested axis
    traj_path = loaded.paths.trajectory_path
    assert traj_path is not None  # enforced by load_drag_run
    traj_frames, traj_px, traj_um = _extract_axis_series(traj_path, axis, um_per_px)

    # 2) Map trajectory frames to authoritative video timestamps
    t_video = _interp_time_for_frames(loaded.frame_indices, loaded.frame_timestamps_s, traj_frames)

    # 3) Alignment: detect onset
    motion_start_stage_s = float(loaded.stage_timing.motion_start_stage_s or 0.0)
    motion_stop_stage_s = (
        float(loaded.stage_timing.motion_stop_stage_s)
        if loaded.stage_timing.motion_stop_stage_s is not None
        else None
    )

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
    # Fallback: relax threshold and min_hold if first pass failed with recoverable reason
    used_relaxed_onset = False
    if (
        onset_video_s is None
        and alignment_diag.failure_reason in ("no_excursion_above_threshold", "no_segment_long_enough")
    ):
        relaxed_sigma = max(2.5, config.onset_threshold_sigma - 1.0)
        relaxed_hold = max(0.1, config.onset_min_hold_s * 0.5)
        onset_relaxed, diag_relaxed = detect_motion_onset(
            t_s=t_video,
            signal=traj_px,
            baseline_end_s=baseline_end_for_onset,
            onset_threshold_sigma=relaxed_sigma,
            onset_min_hold_s=relaxed_hold,
        )
        if onset_relaxed is not None:
            onset_video_s = onset_relaxed
            alignment_diag = diag_relaxed
            used_relaxed_onset = True

    qc = DragQCFlags()
    warnings: list[str] = []

    if used_relaxed_onset:
        warnings.append("Alignment used relaxed onset detection (lower threshold or shorter min_hold).")

    if onset_video_s is None and config.manual_offset_s is None:
        qc.alignment_confident = False
        run_dir_path = Path(loaded.paths.run_dir)
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
            failure_json = run_dir_path / f"{basename}_alignment_failure.json"
            failure_json.write_text(json.dumps(diag_dict, indent=2, ensure_ascii=False), encoding="utf-8")
            from .plotting import plot_alignment_debug
            debug_png = run_dir_path / f"{basename}_alignment_debug.png"
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

    if onset_video_s is None and config.manual_offset_s is not None:
        # Use stage timing with manual offset; synthetic onset at aligned stage time.
        onset_video_s = config.manual_offset_s + motion_start_stage_s
        qc.alignment_confident = False
        alignment_status = "manual_offset"
    else:
        alignment_status = "detected"

    alignment = build_alignment_result(
        motion_start_stage_s=motion_start_stage_s,
        motion_stop_stage_s=motion_stop_stage_s,
        onset_video_s=float(onset_video_s),
        manual_offset_s=config.manual_offset_s,
    )

    # 4) Windows
    try:
        windows = compute_windows(
            motion_start_video_s=alignment.motion_start_video_s_detected,
            motion_stop_video_s_stage_aligned=alignment.motion_stop_video_s_stage_aligned,
            params=config.window_params,
        )
        qc.baseline_window_ok = True
        qc.steady_window_ok = True
    except DragWindowError as e:
        qc.baseline_window_ok = False
        qc.steady_window_ok = False
        warnings.append(str(e))
        raise

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

    baseline_px = _median_in_window(t_video, traj_px, windows.baseline_start_s, windows.baseline_end_s)
    steady_px = _median_in_window(t_video, traj_px, windows.steady_start_s, windows.steady_end_s)

    if not (math.isfinite(baseline_px) and math.isfinite(steady_px)):
        qc.offset_detected = False
        warnings.append("Failed to compute baseline or steady median in px.")
        raise DragWindowError("Cannot compute baseline/steady medians.")

    offset_px_raw = steady_px - baseline_px

    # Convert to µm if possible
    baseline_um = steady_um = offset_um_raw = None
    if um_per_px is not None and um_per_px > 0:
        baseline_um = baseline_px * um_per_px
        steady_um = steady_px * um_per_px
        offset_um_raw = offset_px_raw * um_per_px
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

    # 6) Stage kinematics
    actual_travel_user = loaded.stage_meta.actual_travel_user
    actual_motion_duration_s = loaded.stage_meta.actual_motion_duration_s
    actual_speed_user_s = loaded.stage_meta.actual_speed_user_s

    stage_um_per_unit = config.stage_um_per_unit or loaded.stage_meta.stage_um_per_unit
    actual_travel_um = actual_speed_um_s = None
    if stage_um_per_unit is not None and stage_um_per_unit > 0:
        actual_travel_um = actual_travel_user * stage_um_per_unit
        actual_speed_um_s = actual_speed_user_s * stage_um_per_unit
    else:
        qc.stage_speed_available = True  # user-speed exists, but not in µm
        warnings.append("stage_um_per_unit not provided; absolute drag physics may be incomplete.")

    # 7) Physics layer (optional)
    drag_force_n = kappa_n_per_m = kappa_pn_per_um = eta_pa_s = None
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
        try:
            if offset_m is not None and offset_m != 0:
                if config.eta_pa_s is not None:
                    drag_force_n = compute_drag_force(config.eta_pa_s, radius_m, v_m_s)
                    kappa_n_per_m = compute_kappa_from_drag(
                        config.eta_pa_s,
                        radius_m,
                        v_m_s,
                        offset_m,
                    )
                    kappa_pn_per_um = kappa_n_per_m * 1e6 * 1e12
                    eta_pa_s = config.eta_pa_s
                    physics_status = "ready"
                    qc.physics_ready = True
                elif config.kappa_n_per_m is not None and config.kappa_n_per_m > 0:
                    eta_pa_s = compute_eta_from_drag(
                        config.kappa_n_per_m,
                        radius_m,
                        v_m_s,
                        offset_m,
                    )
                    drag_force_n = compute_drag_force(eta_pa_s, radius_m, v_m_s)
                    kappa_n_per_m = config.kappa_n_per_m
                    kappa_pn_per_um = kappa_n_per_m * 1e6 * 1e12
                    physics_status = "ready"
                    qc.physics_ready = True
        except DragPhysicsError as e:
            warnings.append(f"Physics layer skipped due to invalid inputs: {e}")
            physics_status = "incomplete_inputs"

    # Overall analysis status
    analysis_status = "ok"
    if not qc.alignment_confident or not qc.sufficient_steady_duration or not qc.offset_detected:
        analysis_status = "warning"

    return DragAnalysisResult(
        basename=loaded.paths.basename,
        axis=axis,
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
        kappa_n_per_m=kappa_n_per_m,
        kappa_pn_per_um=kappa_pn_per_um,
        eta_pa_s=eta_pa_s,
        analysis_status=analysis_status,
        alignment_status=alignment_status,
        physics_status=physics_status,
        qc_flags=qc,
        warnings=warnings,
        notes=[],
    )

