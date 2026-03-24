from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from ...analysis import analyze_drag_run
from ...io import load_drag_run
from ...schema import Axis, DragAnalysisConfig, DragRunLoaded
from ..trajectory_helpers import _extract_axis_series, _interp_time_for_frames


@dataclass(frozen=True)
class StepResponseProtocolConfig:
    """Step-response active drag validation scaffold."""

    # Fraction of step amplitude used to estimate time constant (default 63.2% for exp rise).
    tau_fraction: float = 0.632

    # Settling criterion: time when response is within +/- settle_fraction_tol of final amplitude.
    settle_fraction_tol: float = 0.05

    baseline_subtract: Literal["baseline_median", "none"] = "baseline_median"

    require_min_samples_after_onset: int = 20


@dataclass(frozen=True)
class StepResponseAnalysisResult:
    basename: str
    axis: Axis

    step_amplitude_um: float | None
    tau_est_s: float | None
    t_settle_s: float | None

    motion_start_stage_s: float
    motion_start_video_s_detected: float
    alignment_offset_s: float

    analysis_status: str = "ok"
    warnings: list[str] = field(default_factory=list)


def analyze_step_response_drag_run(
    run_dir,
    drag_config: DragAnalysisConfig,
    step_config: StepResponseProtocolConfig,
    trajectory_path=None,
) -> StepResponseAnalysisResult:
    drag_result = analyze_drag_run(run_dir, drag_config, trajectory_path=trajectory_path)

    loaded: DragRunLoaded = load_drag_run(run_dir, trajectory_path=trajectory_path)
    assert loaded.paths.trajectory_path is not None

    axis = drag_result.axis
    um_per_px = drag_config.um_per_px

    traj_frames, traj_px, traj_um = _extract_axis_series(
        loaded.paths.trajectory_path, axis=axis, um_per_px=um_per_px
    )
    t_video = _interp_time_for_frames(loaded.frame_indices, loaded.frame_timestamps_s, traj_frames)

    # Use µm if available, else fallback to px.
    if traj_um is not None:
        y = np.asarray(traj_um, dtype=np.float64)
        units = "um"
    else:
        y = np.asarray(traj_px, dtype=np.float64)
        units = "px"

    t_video = np.asarray(t_video, dtype=np.float64)

    # Filter finite values to avoid broken comparisons.
    mask = np.isfinite(y) & np.isfinite(t_video)
    y = y[mask]
    t_video = t_video[mask]

    if y.size < 2:
        return StepResponseAnalysisResult(
            basename=drag_result.basename,
            axis=axis,
            step_amplitude_um=None,
            tau_est_s=None,
            t_settle_s=None,
            motion_start_stage_s=drag_result.motion_start_stage_s,
            motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
            alignment_offset_s=drag_result.alignment_offset_s,
            analysis_status="warning",
            warnings=["Not enough finite samples for step-response analysis."],
        )

    t0 = float(drag_result.motion_start_video_s_detected)

    x0 = float(drag_result.baseline_position_um) if (step_config.baseline_subtract == "baseline_median" and drag_result.baseline_position_um is not None) else 0.0
    x_final = (
        float(drag_result.steady_position_um)
        if drag_result.steady_position_um is not None
        else float(drag_result.steady_position_px)
    )
    y2 = y - x0
    step_amp = x_final - x0 if (drag_result.steady_position_um is not None and drag_result.baseline_position_um is not None) else float(np.max(y2) - np.min(y2))

    if abs(step_amp) <= 0:
        return StepResponseAnalysisResult(
            basename=drag_result.basename,
            axis=axis,
            step_amplitude_um=float(step_amp),
            tau_est_s=None,
            t_settle_s=None,
            motion_start_stage_s=drag_result.motion_start_stage_s,
            motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
            alignment_offset_s=drag_result.alignment_offset_s,
            analysis_status="warning",
            warnings=["Step amplitude is ~0; tau estimate not meaningful."],
        )

    # Work only on samples after onset to avoid baseline crossings.
    mask_after = t_video >= t0
    t_after = t_video[mask_after]
    y_after = y2[mask_after]

    if y_after.size < step_config.require_min_samples_after_onset:
        return StepResponseAnalysisResult(
            basename=drag_result.basename,
            axis=axis,
            step_amplitude_um=float(step_amp),
            tau_est_s=None,
            t_settle_s=None,
            motion_start_stage_s=drag_result.motion_start_stage_s,
            motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
            alignment_offset_s=drag_result.alignment_offset_s,
            analysis_status="warning",
            warnings=["Not enough post-onset samples to estimate tau/t_settle."],
        )

    # Tau crossing (63.2%)
    target_tau = step_config.tau_fraction * step_amp
    if step_amp > 0:
        idx_tau = np.argmax(y_after >= target_tau)
        if y_after[idx_tau] < target_tau:
            tau_est = None
        else:
            tau_est = float(t_after[idx_tau] - t0)
    else:
        idx_tau = np.argmax(y_after <= target_tau)
        if y_after[idx_tau] > target_tau:
            tau_est = None
        else:
            tau_est = float(t_after[idx_tau] - t0)

    # Settling time: within +/- settle_fraction_tol * final amplitude
    tol = abs(step_amp) * step_config.settle_fraction_tol
    final_level = step_amp
    # y2 is baseline-subtracted, so final_level is step_amp.
    within = np.abs(y_after - final_level) <= tol
    # Find first time index from which it stays within tolerance.
    t_settle = None
    if np.any(within):
        idxs = np.where(within)[0]
        # Choose earliest index after which the remainder mostly stays within (robust).
        for idx in idxs:
            if np.mean(within[idx:]) > 0.95:
                t_settle = float(t_after[idx] - t0)
                break

    warnings: list[str] = []
    if units == "px":
        warnings.append("um_per_px not provided; step_amplitude/tau are in px-domain, not µm.")

    return StepResponseAnalysisResult(
        basename=drag_result.basename,
        axis=axis,
        step_amplitude_um=float(step_amp),
        tau_est_s=tau_est,
        t_settle_s=t_settle,
        motion_start_stage_s=drag_result.motion_start_stage_s,
        motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
        alignment_offset_s=drag_result.alignment_offset_s,
        analysis_status="ok" if tau_est is not None else "warning",
        warnings=warnings + ([] if tau_est is not None else ["tau_est_s not found using tau_fraction crossing."]),
    )

