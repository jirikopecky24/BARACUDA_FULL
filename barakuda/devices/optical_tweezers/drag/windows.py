from __future__ import annotations

from .schema import DragWindowParams, DragWindows


class DragWindowError(ValueError):
    """Error raised when baseline/steady windows cannot be constructed."""


def compute_windows(
    motion_start_video_s: float,
    motion_stop_video_s_stage_aligned: float | None,
    params: DragWindowParams,
) -> DragWindows:
    """Compute baseline and steady-state windows on the video time axis.

    The windows follow:
      baseline: [motion_start - baseline_duration, motion_start - baseline_guard]
      steady:   [motion_start + steady_start_delay, motion_stop - steady_end_guard]
    """
    ms = float(motion_start_video_s)
    me = float(motion_stop_video_s_stage_aligned) if motion_stop_video_s_stage_aligned is not None else float(
        "nan"
    )

    b_dur = float(params.baseline_duration_s)
    b_guard = float(params.baseline_guard_s)
    s_delay = float(params.steady_start_delay_s)
    s_guard = float(params.steady_end_guard_s)

    baseline_start = ms - b_dur
    baseline_end = ms - b_guard

    if baseline_end <= baseline_start:
        raise DragWindowError("Baseline window has non-positive length.")

    if not (baseline_end <= ms):
        raise DragWindowError("Baseline window must end before motion_start_video_s.")

    if motion_stop_video_s_stage_aligned is None:
        # We still define a nominal steady window relative to start only.
        steady_start = ms + s_delay
        steady_end = steady_start + params.min_steady_duration_s
    else:
        steady_start = ms + s_delay
        steady_end = me - s_guard

    if steady_end <= steady_start:
        raise DragWindowError("Steady window has non-positive length.")

    return DragWindows(
        baseline_start_s=baseline_start,
        baseline_end_s=baseline_end,
        steady_start_s=steady_start,
        steady_end_s=steady_end,
    )

