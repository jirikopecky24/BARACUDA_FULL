# DRAG system audit — current state (code-grounded)

## 1. Scope of the audit

- **In scope**: Constant-velocity drag analysis as implemented under `barakuda/devices/optical_tweezers/drag/` (I/O, alignment, windows, physics, export, pipeline → `run_protocol` updates), integration via `barakuda/shell/batch_controller.py`, and report/XLSX consumption in `barakuda/core/ot_report.py` (and related tests). Legacy `DragConstantVelocityStrategy` is noted only as a parallel path.
- **Explicitly out of scope for detail**: Active umbrella oscillatory / step-response flows (`drag/active_umbrella/`), viscoelastic submodule, and Brownian analysis internals (except how Brownian calibration is **wired into** Drag).
- **Method**: Read-through of the modules and tests listed in section 7; no behavioral changes were made for this document.

## 2. Current Drag architecture

| Layer | Role | Primary modules |
|--------|------|-----------------|
| **Discovery / load** | Resolve `.raw`, sidecars, trajectory; load stage meta + trace; validate timestamps | `drag/io.py` (`discover_drag_run_paths`, `load_drag_run`, `evaluate_drag_preflight`) |
| **Analysis** | Frame→video time, onset detection, stage-vs-video alignment, windows, medians, kinematics, physics, QC gates | `drag/analysis.py`, `drag/alignment.py`, `drag/windows.py`, `drag/physics.py` |
| **End-to-end from RAW** | Tracking → trajectory CSV → `analyze_drag_run` → exports + protocol | `drag/pipeline.py` (`run_drag_from_raw`) |
| **Schema / summary** | Config, result dataclass, flat export dict | `drag/schema.py`, `drag/export.py` |
| **Orchestration** | Brownian κ / scale injection, `DragAnalysisConfig` population, call to `run_drag_from_raw` | `shell/batch_controller.py` |
| **Reporting** | Prefers `*_drag_summary.json` over legacy drag blobs | `core/ot_report.py` (`build_ot_item_summary`, drag diagnostics) |
| **Legacy parallel** | Time-only heuristic (second half of trace), not stage-aware | `strategies/drag_constant_velocity.py` |

Data flow (modern path): **acquisition folder** (or item-scoped dirs) → **discovered artifacts** → **`DragRunLoaded`** → **`DragAnalysisResult`** → **`export_drag_summary_json/csv`** + **`run_protocol.json`** merge in `pipeline._update_run_protocol_with_drag_analysis`.

## 3. Current strengths

- **Structured discovery with provenance**: `discover_drag_run_paths` records per-artifact selection mode, warnings, candidates, and searched directories; `used_fallbacks` flags non-exact matches (`io.py`).
- **Strict timestamps ↔ trajectory frames**: `_interp_time_for_frames` refuses silent missing frames (`analysis.py`).
- **Stage-validated mode when prerequisites hold**: If timestamps validate and expected stage start/stop in video time are finite, `drag_anchor_mode` becomes `stage_validated` and **baseline/steady windows** are driven by **expected stage boundaries**, not by detected onset (`analysis.py`).
- **Separation of physics vs detection QC**: `physics_primary_gate`, `detection_qc_gate`, and `final_drag_verdict` (pass / suspect / fail) are computed and exported; stage timing can remain primary while detection is flagged (`analysis.py`, `export.py`).
- **Rich saved summary**: `drag_result_to_dict` / `*_drag_summary.json` carry gates, speeds, baseline strategies, alignment sanity, and provenance fields suitable for batch/report (`export.py`).
- **Report layer consumes saved truth**: `ot_report` reads `*_drag_summary.json` for drag metrics and diagnostics rather than recomputing physics (see tests in `test_truth_resolvers_and_report.py`).
- **Synthetic + integration tests** cover discovery, preflight, output routing, validation gates, and report wiring (`tests/test_drag_*.py`, `test_truth_resolvers_and_report.py`).

## 4. Current weaknesses / risks

- **Physics speed is not trace-derived**: `speed_used_for_physics` is set to `actual_speed_um_s` from stage metadata (with legacy conversion when needed). Trace-derived speed exists as **`stage_speed_from_trace_um_s`** for consistency QC only, not for `v` in Stokes/drag formulas (`analysis.py`).
- **Stage-validated anchor requires full stop time**: `stage_anchor_available` needs **both** start and stop expected in video time plus timestamp validation. If stop is missing or invalid, the pipeline falls back to **detected-onset-driven windows** even when stage start is trustworthy (`analysis.py`).
- **Sidecar pattern fallbacks can be wrong in messy folders**: Non-exact matches use glob patterns (e.g. `*stage*.json`, `*_trajectory.csv`); ambiguity raises errors, but a **single wrong file** matching the pattern could still be selected (`io.py`).
- **Two drag philosophies coexist**: `DragConstantVelocityStrategy` remains a **different** algorithm and input shape (`x_corr_um`, second-half steady); risk of confusion if any UI or export path still mixes it with the modern `drag/` pipeline (`strategies/drag_constant_velocity.py`).
- **Brownian baseline is orchestration-level**: κ and preferred `um_per_px` are passed into `DragAnalysisConfig` from the batch layer; `analyze_drag_run` does not re-read Brownian audit files. Pairing correctness depends on **UI/batch** choosing the right calibration folder, not on drag analysis enforcing many-to-one rules internally.
- **`drag_anchor_mode` not set from batch**: `batch_controller` builds `DragAnalysisConfig` without an explicit `drag_anchor_mode`, so behavior is **`auto`** unless changed elsewhere (`batch_controller.py` vs `schema.py` default).

## 5. Current source-of-truth situation

| Concern | Source of truth |
|---------|-----------------|
| **Numeric drag result for reports** | Saved `analysis/audit/<basename>_drag_summary.json` (and CSV mirror); `report_source_kind` / `report_source_path` on result point there (`pipeline.py`, `export.py`). |
| **Timing for window placement (when validated)** | Stage trace + stage meta, mapped to video via `t_first_s + motion_*_stage_s` with anchor priority `motion_running_confirmed` → `motion_start` → `motion_command_issued` (`analysis.py`). |
| **Trajectory positions** | `*_trajectory.csv` (generated by tracking in `run_drag_from_raw` or pre-existing). |
| **κ for physics** | Injected via config from Brownian calibration resolution in `batch_controller.py` (`kappa_source` string on result). |
| **Protocol / batch bookkeeping** | `run_protocol.json` under the analysis output root, merged with drag analysis + provenance blocks (`pipeline._update_run_protocol_with_drag_analysis`). |

The PDF/XLSX layers **should** treat the summary JSON as authoritative for drag-specific fields; legacy `*_drag.json` is secondary (`ot_report.py`, tests).

## 6. Gaps against intended direction

- **“Stage truth primary; onset QC only”**: Largely implemented when `stage_anchor_available` is true; gaps when stop time is absent or timestamps fail validation—then onset drives windows again.
- **“Actual realized speed for physics”**: Partially addressed by **`actual_metric`** in `stage.json` and legacy conversion; **not** by replacing physics `v` with trace-derived speed when they disagree (trace is QC, not the formula input today).
- **Explicit many-to-one baseline pairing at analysis time**: Not enforced inside `drag/`; relies on shell configuration and calibration loader.
- **Single unified drag entry**: Legacy strategy vs `drag/` pipeline still splits conceptual “drag” depending on call site.

## 7. Recommended next implementation order

1. **Clarify and harden anchor policy in the shell**: Expose `drag_anchor_mode` (or document `auto` rules) from postprocess params so operators can force `stage_validated` vs `detected_onset` without code changes; align defaults with lab policy.
2. **Reduce sidecar-selection risk**: Tighten discovery for `stage_meta` / `stage_trace` when multiple protocol types exist in one item (stricter naming or manifest precedence).
3. **Physics speed policy**: Decide whether trace-derived speed should ever override or bound `actual_speed_um_s` for physics; if yes, implement as an explicit branch with provenance fields (today only `speed_consistency_error_pct` warns).
4. **Deprecate or fence legacy `DragConstantVelocityStrategy`**: Ensure all primary OT drag workflows use `drag/analyze_drag_run` so results and gates are comparable.
5. **Extend tests** for real folder layouts with imperfect filenames and for batch-level `DragAnalysisConfig` (including `drag_anchor_mode`).

## 8. Suggested lowest-risk first implementation task

**Wire `drag_anchor_mode` from postprocess / UI into `DragAnalysisConfig` in `batch_controller.py` (defaulting to current `auto` behavior)** so behavior is explicit, reproducible, and testable without changing physics formulas or discovery logic.

---

## Appendix — Key file references

- Discovery: `barakuda/devices/optical_tweezers/drag/io.py`
- Analysis & gates: `barakuda/devices/optical_tweezers/drag/analysis.py`
- RAW pipeline & protocol merge: `barakuda/devices/optical_tweezers/drag/pipeline.py`
- Exports: `barakuda/devices/optical_tweezers/drag/export.py`
- Schema: `barakuda/devices/optical_tweezers/drag/schema.py`
- Batch wiring: `barakuda/shell/batch_controller.py` (drag block ~1570+)
- Report: `barakuda/core/ot_report.py`
- Tests: `tests/test_drag_artifact_discovery.py`, `tests/test_drag_preflight_workflow.py`, `tests/test_drag_output_routing.py`, `tests/test_drag_physics_validation_gate.py`, `tests/test_truth_resolvers_and_report.py`
