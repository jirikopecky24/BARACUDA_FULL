from __future__ import annotations

import math
import statistics
from typing import Sequence

from .schema import DragAlignmentResult, AlignmentDiagnostics


class DragAlignmentError(RuntimeError):
    """Raised when motion onset cannot be detected and no manual offset is provided."""

    def __init__(self, message: str, diagnostics: AlignmentDiagnostics | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics


def _robust_sigma(values: Sequence[float]) -> tuple[float, float, float]:
    """Median, MAD, and approximate robust sigma (1.4826*MAD). Returns (median, mad, sigma)."""
    vals = [v for v in values if math.isfinite(v)]
    if len(vals) < 2:
        return (float("nan"), float("nan"), float("nan"))
    med = statistics.median(vals)
    mad = statistics.median(abs(v - med) for v in vals)
    if mad <= 0:
        sigma = statistics.pstdev(vals) if len(vals) >= 2 else float("nan")
        return (med, 0.0, sigma)
    sigma = 1.4826 * mad
    return (med, mad, sigma)


def detect_motion_onset(
    t_s: Sequence[float],
    signal: Sequence[float],
    baseline_end_s: float,
    onset_threshold_sigma: float,
    onset_min_hold_s: float,
) -> tuple[float | None, AlignmentDiagnostics]:
    """Detect motion onset from a 1D signal using a baseline segment.

    Baseline is defined as t <= baseline_end_s.
    Returns (onset_time_s or None, diagnostics).
    """
    if len(t_s) != len(signal):
        raise ValueError("t_s and signal must have the same length")
    n = len(t_s)
    t_s = list(t_s)
    signal = list(signal)

    baseline_values = [signal[i] for i in range(n) if t_s[i] <= baseline_end_s]
    n_baseline = len(baseline_values)
    n_outside = 0
    candidate_onset_times: list[float] = []
    candidate_durations: list[float] = []

    if n_baseline < 5:
        diag = AlignmentDiagnostics(
            baseline_end_s=float(baseline_end_s),
            baseline_median=float("nan"),
            baseline_mad=float("nan"),
            baseline_sigma=float("nan"),
            onset_threshold_sigma=float(onset_threshold_sigma),
            onset_threshold_abs=float("nan"),
            onset_min_hold_s=float(onset_min_hold_s),
            n_baseline_samples=n_baseline,
            n_total_samples=n,
            n_frames_outside_baseline=0,
            candidate_onset_times_s=(),
            candidate_durations_s=(),
            failure_reason="insufficient_baseline_samples",
            message=f"Baseline has only {n_baseline} samples (need at least 5). baseline_end_s={baseline_end_s}",
        )
        return (None, diag)

    baseline_med, mad, sigma = _robust_sigma(baseline_values)
    if not math.isfinite(sigma) or sigma <= 0:
        diag = AlignmentDiagnostics(
            baseline_end_s=float(baseline_end_s),
            baseline_median=baseline_med,
            baseline_mad=mad,
            baseline_sigma=sigma,
            onset_threshold_sigma=float(onset_threshold_sigma),
            onset_threshold_abs=float("nan"),
            onset_min_hold_s=float(onset_min_hold_s),
            n_baseline_samples=n_baseline,
            n_total_samples=n,
            n_frames_outside_baseline=0,
            candidate_onset_times_s=(),
            candidate_durations_s=(),
            failure_reason="baseline_sigma_zero_or_nan",
            message="Baseline variability (sigma) is zero or NaN; cannot set threshold.",
        )
        return (None, diag)

    thresh_abs = abs(float(onset_threshold_sigma)) * sigma
    min_hold = max(float(onset_min_hold_s), 0.0)

    i = 0
    chosen_onset: float | None = None
    while i < n:
        dt = abs(signal[i] - baseline_med)
        if dt > thresh_abs:
            n_outside += 1
            t_start = t_s[i]
            j = i
            while j < n and abs(signal[j] - baseline_med) > thresh_abs:
                n_outside += 1
                j += 1
            t_end = t_s[j - 1] if j > i else t_s[i]
            duration = t_end - t_start
            candidate_onset_times.append(t_start)
            candidate_durations.append(duration)
            if chosen_onset is None and duration >= min_hold:
                chosen_onset = t_start
            i = j
        else:
            i += 1

    if chosen_onset is not None:
        diag = AlignmentDiagnostics(
            baseline_end_s=float(baseline_end_s),
            baseline_median=baseline_med,
            baseline_mad=mad,
            baseline_sigma=sigma,
            onset_threshold_sigma=float(onset_threshold_sigma),
            onset_threshold_abs=thresh_abs,
            onset_min_hold_s=min_hold,
            n_baseline_samples=n_baseline,
            n_total_samples=n,
            n_frames_outside_baseline=n_outside,
            candidate_onset_times_s=tuple(candidate_onset_times),
            candidate_durations_s=tuple(candidate_durations),
            failure_reason="",
            message="Onset detected.",
        )
        return (chosen_onset, diag)

    if not candidate_onset_times:
        diag = AlignmentDiagnostics(
            baseline_end_s=float(baseline_end_s),
            baseline_median=baseline_med,
            baseline_mad=mad,
            baseline_sigma=sigma,
            onset_threshold_sigma=float(onset_threshold_sigma),
            onset_threshold_abs=thresh_abs,
            onset_min_hold_s=min_hold,
            n_baseline_samples=n_baseline,
            n_total_samples=n,
            n_frames_outside_baseline=0,
            candidate_onset_times_s=(),
            candidate_durations_s=(),
            failure_reason="no_excursion_above_threshold",
            message=f"No segment exceeded threshold ({thresh_abs:.4f} px, {onset_threshold_sigma} sigma). Try lower onset_threshold_sigma.",
        )
        return (None, diag)

    max_dur = max(candidate_durations) if candidate_durations else 0.0
    diag = AlignmentDiagnostics(
        baseline_end_s=float(baseline_end_s),
        baseline_median=baseline_med,
        baseline_mad=mad,
        baseline_sigma=sigma,
        onset_threshold_sigma=float(onset_threshold_sigma),
        onset_threshold_abs=thresh_abs,
        onset_min_hold_s=min_hold,
        n_baseline_samples=n_baseline,
        n_total_samples=n,
        n_frames_outside_baseline=n_outside,
        candidate_onset_times_s=tuple(candidate_onset_times),
        candidate_durations_s=tuple(candidate_durations),
        failure_reason="no_segment_long_enough",
        message=f"All {len(candidate_onset_times)} candidate onset(s) had duration < min_hold ({min_hold:.3f} s). Longest candidate: {max_dur:.3f} s. Try lower onset_min_hold_s or lower onset_threshold_sigma.",
    )
    return (None, diag)


def build_alignment_result(
    motion_start_stage_s: float,
    motion_stop_stage_s: float | None,
    onset_video_s: float,
    manual_offset_s: float | None = None,
) -> DragAlignmentResult:
    """Construct DragAlignmentResult from stage and detected onset times."""
    if manual_offset_s is not None:
        alignment_offset_s = float(manual_offset_s)
        method = "manual_offset"
    else:
        alignment_offset_s = float(onset_video_s) - float(motion_start_stage_s)
        method = "detected"

    motion_stop_video_s_stage_aligned = (
        alignment_offset_s + float(motion_stop_stage_s)
        if motion_stop_stage_s is not None
        else None
    )

    return DragAlignmentResult(
        alignment_offset_s=alignment_offset_s,
        motion_start_stage_s=float(motion_start_stage_s),
        motion_stop_stage_s=float(motion_stop_stage_s) if motion_stop_stage_s is not None else None,
        motion_start_video_s_detected=float(onset_video_s),
        motion_stop_video_s_stage_aligned=motion_stop_video_s_stage_aligned,
        method=method,  # type: ignore[arg-type]
        warnings=[],
    )
