# Drag stage-truth verification (modern `analyze_drag_run` path)

## 1. Scope

- **In scope**: `barakuda/devices/optical_tweezers/drag/analysis.py` (timing, windows, kinematics, physics, gates), `alignment.py`, `windows.py`, `io.py` stage load, `export.py` / `pipeline.py` summary fields, OT report diagnostics (`ot_report.py`), and focused tests in `tests/test_drag_stage_truth_verification.py`, `tests/test_drag_physics_validation_gate.py`, `tests/test_drag_output_routing.py`.
- **Out of scope**: Brownian, legacy `DragConstantVelocityStrategy`, oscillatory/viscoelastic umbrellas, wholesale PDF redesign.

## 2. Contract: `stage_validated` (effective mode)

When **`drag_anchor_mode` is effectively `stage_validated`** (requested `stage_validated` or `auto` with a **validated** stage window: timestamps OK, finite expected start **and** stop in video time):

1. **Primary timing truth** for windows, alignment anchor passed to `build_alignment_result`, and the **primary** video motion-start field on the result (`motion_start_video_s_detected` after alignment) is **stage-derived expected** video time (`expected_stage_start_video_s` = `t_first_s + motion_start_stage_s` from trace priority: `motion_running_confirmed` → `motion_start` → `motion_command_issued`). Stop alignment uses the same stage-first policy via `build_alignment_result` with that primary anchor.
2. **`motion_timing_primary_source`** is `expected_stage_timing` (unless `manual_offset_s` is set → `manual_offset`).
3. **`primary_timing_source_for_windows`** remains `expected_stage_start_stop` for window construction (`compute_windows` uses expected start/stop in video time, not raw onset).
4. **Trajectory-detected onset** is still computed and exposed as **`detected_onset_video_s`** (raw detector output before any manual-offset synthetic path). In this mode **`detected_onset_diagnostic_only` is `true`**: onset must **not** replace primary timing, redefine the alignment anchor, or silently steer physics-facing primary motion times.
5. **QC / disagreement**: `stage_video_start_delta_s` (and related gates) compare **diagnostic** onset vs expected. **`detection_qc_gate`**, warnings, and verdicts may reflect disagreement; they do **not** change the primary stage-truth windows or the primary aligned motion-start time used for the stage-validated path.

## 3. What detected onset is still allowed to do

- Populate **`detected_onset_video_s`**, alignment diagnostics (`alignment_diagnostics`), and **delta / consistency** fields vs expected stage times.
- Influence **`detection_qc_gate`**, **`detected_onset_consistency_*`**, **`final_drag_verdict`** when inconsistent, and human-readable reasons in summary output.
- Remain visible in exports and OT report rows (**motion timing primary source**, **detected onset (diagnostic)**, **diagnostic-only flag**).

## 4. What detected onset must not do (in effective `stage_validated`)

- Act as a **second primary** timing authority: it does **not** drive `build_alignment_result(..., onset_video_s=...)` (that uses **`primary_video_anchor_s`** = expected when stage-validated).
- Move **baseline/steady window** boundaries (those follow expected stage video start/stop).
- Overwrite **`motion_start_video_s_detected`** with the raw detector time when stage-validated; that field reflects the **primary anchor** after alignment (stage-expected), while **`detected_onset_video_s`** holds the raw diagnostic.

## 5. Degraded fallback

- If validated stage stop is missing or timestamps/trace do not yield a finite expected window, **`stage_anchor_available`** is false → effective mode becomes **`detected_onset`** even when `stage_validated` or `auto` was requested.
- A **`PHYSICS_WARNING`** is recorded when **`stage_validated` was requested** but unavailable. Summary keeps **`drag_anchor_mode_requested`** vs **`drag_anchor_mode_effective`** / **`drag_anchor_mode`** honest.
- In degraded mode, onset may again drive windows and alignment; **`detected_onset_diagnostic_only`** is **`false`**, and **`motion_timing_primary_source`** is **`trajectory_detected_onset`** (unless manual offset).

## 6. Speed for physics (unchanged)

- **`v` in Stokes** uses **`actual_speed_um_s`** from stage metadata (including optional `actual_metric.actual_speed_um_s`), not trace-derived speed, not commanded speed.
- Trace-derived speed remains **QC** (`stage_speed_from_trace_um_s`, consistency flags).

## 7. Field semantics (summary / export)

| Field | Meaning in effective `stage_validated` |
|--------|----------------------------------------|
| `primary_timing_source_for_windows` | `expected_stage_start_stop` |
| `motion_timing_primary_source` | `expected_stage_timing` (or `manual_offset`) |
| `motion_start_video_s_detected` | Primary aligned motion start in video time (**stage-anchored**) |
| `detected_onset_video_s` | Raw trajectory onset for diagnostics / QC |
| `detected_onset_diagnostic_only` | `true` |
| `detected_stage_start_video_s` | Same role as diagnostic export companion to onset (see `analysis.py`; not the primary motion-start authority) |
| `stage_video_start_delta_s` | `detected_onset_video_s - expected_stage_start_video_s` when raw onset exists |

## 8. Is modern Drag stage-truth-first in practice?

**Yes**, for the modern `analyze_drag_run` path when **effective** mode is **`stage_validated`**: expected stage timing in video coordinates is the **sole primary** authority for windows, alignment anchor, and the primary motion-start field used downstream; detected onset is **diagnostic/QC only** in that mode. Residual nuance: if onset detection **fails** entirely, the run can still proceed in `stage_validated` without a raw diagnostic onset (`detected_onset_video_s` may be `null`); primary timing remains stage-based.

## 9. Tests

```bash
python -m pytest tests/test_drag_stage_truth_verification.py tests/test_drag_physics_validation_gate.py tests/test_drag_output_routing.py -q
```

Primary files: `tests/test_drag_stage_truth_verification.py`, `tests/test_drag_physics_validation_gate.py`.
