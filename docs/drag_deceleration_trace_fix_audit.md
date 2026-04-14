# Drag Deceleration Source Audit (pre trace-priority fix)

## Scope

- Repo state: branch `fix/drag-windowing-stage-motion-anchors` before this fix
- Representative runs:
  - `Gly20_drag_rep01`
  - `Gly40_drag_rep01`
- Dataset root:
  - `C:/BARAKUDA_THESIS_2026/runs/2026-04-08_DAY05`

## Current behavior before this fix

- `deceleration_start_source` resolves to `estimated_from_commanded_speed_decel`.
- `steady_end_marker_source` resolves to `deceleration_start_minus_guard`.
- Therefore steady-end timing still depends on the commanded model estimate when no
  explicit deceleration event is present.

## Stage trace availability check

For `Gly20_drag_rep01` and `Gly40_drag_rep01`, `*_stage_trace.csv` contains only sparse
events (start/stop markers) and does not include a dense velocity profile in
`velocity_user_s` or sampled position telemetry rows suitable for direct deceleration
edge detection.

This means the fix must:

1. Prefer real trace velocity-profile detection when telemetry exists.
2. Keep explicit `deceleration_start` event as secondary trace fallback.
3. Use commanded estimate only as last fallback.
