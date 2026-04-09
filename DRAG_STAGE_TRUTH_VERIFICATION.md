# Drag stage-truth verification (modern `analyze_drag_run` path)

## 1. Scope

- **In scope**: `barakuda/devices/optical_tweezers/drag/analysis.py` (timing, windows, kinematics, physics, gates), `alignment.py`, `windows.py`, `io.py` stage load, `export.py` summary fields, and focused tests in `tests/test_drag_stage_truth_verification.py`.
- **Out of scope**: Brownian, legacy `DragConstantVelocityStrategy`, oscillatory/viscoelastic umbrellas, PDF layout beyond diagnostics already wired from summary JSON.

## 2. What was verified

End-to-end tracing of:

| Decision | Where |
|----------|--------|
| **A. Requested anchor** | `config.drag_anchor_mode` → `requested_anchor_mode` (`analysis.py`) |
| **B. Effective anchor** | `use_stage_validated_anchor` + `drag_anchor_mode`; `drag_anchor_mode_requested` / effective in result + export |
| **C. Window motion start/stop** | `primary_motion_start_video_s` / `primary_motion_stop_video_s` → `compute_windows` (`analysis.py` ~439–455) |
| **D. Detected onset** | `detect_motion_onset` → alignment offset + QC deltas + `detection_qc_gate` |
| **E. Physics speed** | `actual_speed_um_s` (from `stage_meta`, including `actual_metric`) → `v_m_s` in physics block (`analysis.py` ~741–742, 934–936) |
| **F. Gates / verdict** | `physics_primary_gate`, `detection_qc_gate`, `final_drag_verdict` (`analysis.py` ~1004–1051) |
| **G. Saved fields** | `drag_result_to_dict` / `pipeline._update_run_protocol_with_drag_analysis` |

## 3. Actual current behavior

### Windows vs stage timing

When `stage_anchor_available` is true (validated timestamps **and** finite expected start **and** stop in video time) **and** `use_stage_validated_anchor` is true:

- `primary_motion_start_video_s = expected_stage_start_video_s` (= `t_first_s + motion_start_stage_s` from trace priority: `motion_running_confirmed` → `motion_start` → `motion_command_issued`).
- `primary_motion_stop_video_s = expected_stage_stop_video_s` (= `t_first_s + motion_stop_stage_s` when stop exists).
- `compute_windows` uses those values directly — **not** `alignment.motion_start_video_s_detected` for window bounds.

When `use_stage_validated_anchor` is false, windows use `alignment.motion_start_video_s_detected` and `alignment.motion_stop_video_s_stage_aligned` (offset derived from detected onset vs stage start).

### Trajectory onset: not “QC only” for all purposes

- **Windows (stage-validated path)**: Onset does **not** move baseline/steady boundaries; stage-expected video times do.
- **Alignment / reporting**: Onset still drives `alignment_offset_s = onset_video_s - motion_start_stage_s` (unless manual offset), `motion_start_video_s_detected`, and comparison to expected (`detection_qc_gate`, `detected_onset_consistency_*`). So onset is **secondary for window placement** but **still used** for alignment metadata and detection QC.

### Speed for physics

- **`v` in Stokes formulas** uses `actual_speed_um_s` after stage-meta load (including optional `actual_metric.actual_speed_um_s`), with legacy fallback `actual_speed_user_s * stage_um_per_unit` when metric µm/s is absent (`analysis.py`, `io._load_stage_meta`).
- **`speed_used_for_physics`** and **`speed_stage_json`** on the result both mirror that same `actual_speed_um_s` value (not trace-derived speed).
- **`stage_speed_from_trace_um_s`** is computed from `actual_travel_user / trace_duration * stage_um_per_unit` and used for **consistency QC** (`stage_speed_consistent`, `kinematics_robustness_flag`), not as `v` in the main drag force path.
- **`commanded_metric`** in `*_stage.json` is intended as provenance only for `commanded_travel_user_ref` / `commanded_speed_user_s_ref`. **Fix in this round**: `commanded_metric` was removed from the `known_keys` filter in `io._load_stage_meta` so it is stored under `protocol_params` and is visible to `analysis.py` (previously it was dropped on load).

### Fallback / degraded timing

- If validated stage stop is missing (e.g. trace without `motion_stop`), `stage_anchor_available` is false → effective mode is `detected_onset` even when `drag_anchor_mode_requested` is `auto` or `stage_validated`.
- When **`stage_validated` is requested** but unavailable, a **`PHYSICS_WARNING`** is appended and summary fields still show `drag_anchor_mode_requested` vs effective `detected_onset`.

### Gates

- **`physics_primary_gate`**: alignment sanity, baseline/kinematics/clipping/plausibility, physics readiness.
- **`detection_qc_gate`**: onset vs stage consistency, onset robustness, relaxed onset, etc.
- **`final_drag_verdict`**: combines both (e.g. physics fail → fail; detection fail alone can yield suspect while numbers exist).

## 4. Confirmed correct behaviors

1. With valid stage start/stop and timestamps, **steady/baseline windows are anchored to expected stage video times**, even if bead onset is late (`test_stage_validated_windows_use_expected_stage_time_not_detected_onset`).
2. **Trajectory onset does not override** those window boundaries in the stage-validated path.
3. **Physics `v` uses `actual_speed_um_s`** from stage metadata; trace-derived speed is QC; **`speed_used_for_physics`** matches that (`test_physics_speed_uses_actual_metric_not_trace_derived`).
4. **Commanded speed does not replace physics `v`** when `commanded_metric` is present; refs are exposed separately (`test_commanded_speed_is_provenance_only_not_physics_v` + `commanded_metric` load fix).
5. **Requested vs effective** anchor modes are stored in summary JSON (`test_no_motion_stop_degrades_to_detected_onset_honest_summary`).
6. **Computed physics** (`physics_status == "ready"`) can coexist with **`detection_qc_gate == "fail"`** and **`final_drag_verdict == "suspect"`** (`test_gates_remain_separate_from_numeric_physics_ready`).

## 5. Mismatches or caveats

1. **“Onset QC only”** is accurate for **window placement** in stage-validated mode, **not** for the whole pipeline: alignment offset and detected video times still come from onset (or expected fallback when onset missing).
2. **`actual_speed_um_s` is “realized” only insofern stage.json / `actual_metric` say so** — it is not independently measured from the trajectory; trace disagreement is flagged, not auto-correcting `v`.
3. **Legacy `Drag_ConstantVelocity` strategy** remains a separate code path (not verified here).
4. **Stage-validated mode requires a full stop time** in the trace; partial traces always fall back to onset-driven windows.

## 6. Is Drag truly stage-truth-first today?

**Partially.** For the modern `analyze_drag_run` path:

- **Yes** for **which video times define baseline/steady windows** when validated stage bounds exist.
- **Yes** for **which scalar speed enters Stokes physics** (`actual_speed_um_s`, not trace-derived, not commanded).
- **No** if “stage-truth-first” is read as “trajectory onset plays no role anywhere”: onset still feeds alignment and detection QC.

## 7. Recommended next step

**Single next step**: Document (or optionally refactor in a later round) whether **`alignment_offset_s` / detected video times** should eventually be **purely diagnostic** when `drag_anchor_mode == stage_validated"`, so “stage-truth-first” is unambiguous across alignment + windows + exports.

---

## Tests

Run:

`python -m pytest tests/test_drag_stage_truth_verification.py -q`

Primary file: `tests/test_drag_stage_truth_verification.py`.
