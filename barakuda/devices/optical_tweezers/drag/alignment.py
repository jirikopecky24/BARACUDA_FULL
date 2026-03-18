from __future__ import annotations

import math
import statistics
from typing import Sequence

import numpy as np

from .schema import DragAlignmentResult, AlignmentDiagnostics


class DragAlignmentError(RuntimeError):
    """Raised when motion onset cannot be detected and no manual offset is provided."""

    def __init__(self, message: str, diagnostics: AlignmentDiagnostics | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics


def _boxcar_smooth(y: Sequence[float], window: int) -> list[float]:
    """Centered moving average; reduces high-FPS noise so onset segments last longer."""
    arr = np.asarray(y, dtype=np.float64)
    n = int(arr.size)
    w = max(1, min(window, n | 1))  # odd, at least 1
    if w <= 1 or n < 3:
        return list(arr)
    if w % 2 == 0:
        w += 1
    pad = w // 2
    xp = np.pad(arr, (pad, pad), mode="edge")
    k = np.ones(w, dtype=np.float64) / float(w)
    sm = np.convolve(xp, k, mode="valid")
    return [float(x) for x in sm[:n]]


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

    # High-FPS tracking: raw |x - baseline| flickers across threshold every few samples.
    # ~20–40 ms boxcar preserves real drift while merging noise spikes into longer runs.
    dt_med = float(np.median(np.diff(np.asarray(t_s[: min(n, 5000)], dtype=np.float64)))) if n > 2 else 1e-3
    if not math.isfinite(dt_med) or dt_med <= 0:
        dt_med = 1e-3
    win = int(round(0.035 / dt_med))  # ~35 ms boxcar @ FPS
    win = max(5, min(win, 401))
    if win % 2 == 0:
        win += 1
    signal_use = _boxcar_smooth(signal, win)

    i = 0
    chosen_onset: float | None = None
    while i < n:
        dt = abs(signal_use[i] - baseline_med)
        if dt > thresh_abs:
            n_outside += 1
            t_start = t_s[i]
            j = i
            while j < n and abs(signal_use[j] - baseline_med) > thresh_abs:
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

    # Merge micro-segments (noise flicker at high FPS) into bursts; then allow slightly
    # shorter hold than min_hold for merged-only acceptance.
    merged_pairs: list[tuple[float, float]] = []
    if chosen_onset is None and len(candidate_onset_times) >= 2:
        merge_gap = max(12.0 * dt_med, min(0.35, max(min_hold * 2.5, 0.2)))
        ms = float(candidate_onset_times[0])
        me = ms + float(candidate_durations[0])
        for k in range(1, len(candidate_onset_times)):
            ts = float(candidate_onset_times[k])
            te = ts + float(candidate_durations[k])
            if ts - me <= merge_gap:
                me = max(me, te)
            else:
                merged_pairs.append((ms, me))
                ms, me = ts, te
        merged_pairs.append((ms, me))
        merged_min = max(0.05, min_hold * 0.42)
        t_baseline = float(baseline_end_s)
        for ms_i, me_i in merged_pairs:
            dur = me_i - ms_i
            if dur >= min_hold and chosen_onset is None:
                chosen_onset = ms_i
            elif (
                chosen_onset is None
                and dur >= merged_min
                and ms_i >= t_baseline - 4 * dt_med
            ):
                chosen_onset = ms_i
        if merged_pairs:
            for ms_i, me_i in merged_pairs:
                candidate_onset_times.append(ms_i)
                candidate_durations.append(me_i - ms_i)

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
