# Drag own-tracking workflow contract

## 1. Scope

This note documents the **default Drag analysis chain** in BARAKUDA after the “own tracking before Brown baseline” redesign. It covers **execution and provenance**, not Drag report PDF/HTML layout.

Grounding: `barakuda/devices/optical_tweezers/drag/io.py`, `analysis.py`, `pipeline.py`, `export.py`, `schema.py`, and the Drag branch in `barakuda/shell/batch_controller.py`.

## 2. Previous behavior (summary)

Previously, discovery could treat an **on-disk `*_trajectory.csv`** as the primary input: preflight could surface a current trajectory path, and `analyze_drag_run` could load via trajectory discovery when no explicit path was passed. Brown calibration was tightly coupled to the batch Drag path in a way that did not enforce **tracking first** as the default thesis-safe contract.

## 3. New default behavior

**A. Input / preflight**

- Inputs are the **Drag RAW** file plus **Drag sidecars** (meta, timestamps, stage JSON, stage trace, etc.).
- `evaluate_drag_preflight` calls `discover_drag_run_paths(..., include_trajectory_discovery=False)`. It **does not** treat an existing trajectory CSV as the normal readiness gate; `current_drag_trajectory_path` is **always `None`** at preflight.
- Status strings include `ready_drag_sidecars_item` and `ready_drag_sidecars_standalone`.

**B. Tracking**

- `generate_drag_trajectory_from_raw(run_dir, output_csv_dir, ...)` runs **OT tracking on the Drag RAW** only (via `_run_tracking_to_trajectory`). It does **not** discover/reuse an existing trajectory and does **not** use Brownian calibration.
- The batch Drag path calls this **before** loading Brownian calibration, writing under the run’s `csv/` folder.

**C. Postprocess / physics**

- `finalize_drag_run_from_trajectory(run_dir, trajectory_path, drag_config, output_root)` runs `analyze_drag_run` with an **explicit** trajectory path and `trajectory_source_kind="generated_from_drag_raw"`.
- `drag_config` is built **after** tracking, including **κ / scale from the paired Brown folder** (`load_brownian_calibration_from_folder`) where required.

**D. Report readiness (data only)**

- Exports (`export_drag_summary_json`, CSV, alignment diagnostics, diagnostic plot, windows/trace CSVs) and `drag_result_to_dict` include trajectory provenance fields so a **future** Drag report can be driven from Drag-owned artefacts without implying Brown “presentation” ownership of the trajectory chain.

## 4. Where Brown enters the chain

- **Not** in tracking: `generate_drag_trajectory_from_raw` has no Brown import or calibration load.
- **After** Drag-owned trajectory exists: batch code loads `load_brownian_calibration_from_folder`, builds `DragAnalysisConfig`, then calls `finalize_drag_run_from_trajectory`.
- Brown remains **baseline / calibration context** (e.g. κ, `um_per_px` sourcing), not the source of the Drag trajectory for the default path.

**Pairing / Auto-pair (OT shell):** `is_ot_drag_baseline_pairing_target` in `barakuda/devices/optical_tweezers/ui/batch_tools.py` treats a dataset path as a Drag↔Brown pairing target if either stored `postprocess.calibration_mode == "Drag"` or on-disk layout passes `evaluate_drag_preflight` (`ready_drag_sidecars_*`). Pairing assigns `brownian_baseline_folder` **before** batch tracking/postprocess; it does **not** imply Brown owns the Drag trajectory. Auto-pair normalizes stored postprocess to Drag mode when linking so batch Run uses the Drag pipeline.

## 5. Explicit reuse / debug fallback

- `analyze_drag_run(..., allow_discovered_trajectory=True)` with `trajectory_path=None` reloads an on-disk trajectory via `load_drag_run(..., allow_discover_trajectory=True)`.
- Default for `allow_discovered_trajectory` is **`False`**; missing `trajectory_path` then raises `DragIoError` with an explicit message.
- Provenance for that path: `trajectory_source_kind` defaults to **`reused_existing_trajectory`**, `trajectory_generated_in_this_workflow` **`False`**.
- **CLI debug** (`cli_debug.py`): if `--trajectory` is omitted, **`allow_discovered_trajectory=True`** is used so local debugging can still reuse a file without silently pretending it was generated in this workflow.

## 6. Saved provenance semantics

| Field | Typical default-path values |
|--------|-----------------------------|
| `trajectory_source_kind` | `generated_from_drag_raw` after `finalize_drag_run_from_trajectory` |
| `trajectory_generated_in_this_workflow` | `True` on that path |
| `selected_trajectory_path` | Resolved path to the CSV used in analysis |
| `reused_existing_trajectory` | Only when `allow_discovered_trajectory=True` (or explicit kind override) |

Other existing fields (`selected_timestamps_path`, `selected_stage_meta_path`, `brownian_baseline_folder`, `drag_preflight_status`, etc.) continue to record sidecar and baseline context.

## 7. Remaining caveats

- **Batch vs CLI**: Batch follows generate → Brown → finalize. Standalone `run_drag_from_raw` / CLI may still combine steps differently; any divergence is in the caller, not in the core “finalize expects explicit trajectory + config” API.
- **Legacy reuse** remains available and must stay **opt-in** (`allow_discovered_trajectory` or CLI without `--trajectory`).
- A **larger cleanup** (e.g. unifying every entry point behind one orchestrator) is intentionally **out of scope** for this change set.

## 8. Recommended next step

Implement or wire the **Drag report** to read **only** from Drag export paths and `drag_result_to_dict` / saved JSON (trajectory + summary + diagnostics), and assert in tests that report generation does not depend on Brown trajectory presentation.
