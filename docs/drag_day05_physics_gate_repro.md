# Drag Day05 Reproduction Audit (2026-04-14_090043)

This note captures reproducible evidence for DRAG primary-gate failures before the
windowing fix.

## Scope

- Dataset root: `C:/BARAKUDA_THESIS_2026/runs/2026-04-08_DAY05`
- Batch analyzed: `analysis/2026-04-14_090043`
- Representative runs:
  - `Gly20_drag_rep01` (pass)
  - `Gly40_drag_rep01` (fail)

## Current windowing behavior (pre-fix)

- Baseline:
  - `baseline_start = motion_start - baseline_duration`
  - `baseline_end = motion_start - baseline_guard`
- Steady:
  - `steady_start = motion_start + steady_start_delay`
  - `steady_end = motion_stop - steady_end_guard`
- Defaults:
  - `baseline_duration_s = 3.0`
  - `baseline_guard_s = 0.5`
  - `steady_start_delay_s = 2.0`
  - `steady_end_guard_s = 1.0`

## Representative evidence

### Gly20_drag_rep01

- Stage events:
  - `motion_running_confirmed = 3.203664`
  - `motion_stop = 10.983841`
- Expected stage anchors in video time:
  - `expected_stage_start_video_s = 272014.7575433`
  - `expected_stage_stop_video_s = 272022.5377203`
- Used windows:
  - baseline: `272011.7575433 -> 272014.2575433` (guard to start: `0.5 s`)
  - steady: `272016.7575433 -> 272021.5377203` (start delay: `2.0 s`, end guard: `1.0 s`)
- Verdict:
  - `final_drag_verdict = pass`
  - `final_drag_reason = physics_primary=pass, detection_qc=pass`

### Gly40_drag_rep01

- Stage events:
  - `motion_running_confirmed = 1.219258`
  - `motion_stop = 14.222879`
- Expected stage anchors in video time:
  - `expected_stage_start_video_s = 273370.34221020003`
  - `expected_stage_stop_video_s = 273383.3458312`
- Used windows:
  - baseline original: `273367.34221020003 -> 273369.84221020003`
  - baseline clipped: `273369.1229522 -> 273369.84221020003`
  - steady: `273372.34221020003 -> 273382.3458312`
- Verdict:
  - `final_drag_verdict = fail`
  - `final_drag_reason = physics_primary=fail, detection_qc=suspect, window_clipping_severe, plausibility_suspect, relaxed_onset_used`
- Key finding:
  - Baseline clipping dominates the gate reason even though offset/speed/diagnostics are present.

## Across-series summary (same batch)

- Total DRAG runs: `13`
- Verdict counts:
  - `fail = 8`
  - `pass = 3`
  - `suspect = 2`
- Guard consistency (when not hard-clipped by invalid stop range):
  - baseline end guard is fixed at `0.5 s`
  - steady start delay is fixed at `2.0 s`
  - steady end guard is fixed at `1.0 s`

## Pre-fix conclusion

Primary fails in this series are not solely explained by raw signal quality. Current
windowing/gate behavior is overly rigid when baseline clipping occurs and does not use
an explicit or derived deceleration-start marker for steady-window end selection.
