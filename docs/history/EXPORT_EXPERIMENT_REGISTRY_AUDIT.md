# Export & Experiment Registry — Diagnostic Audit

**Date:** 2026-03-09  
**Scope:** Export dataset workflow and Experiment Registry only. No runtime code modified in this step.

---

## 1. Relevant Implementation Locations

### Export

| Area | Location |
|------|----------|
| **Artifact discovery** | `barakuda/devices/optical_tweezers/export/discovery.py` — `discover_analysis_artifacts(dataset_root)`; looks under `dataset_root/analysis/` for fixed filenames (trajectory.csv, tracking.csv, psd.csv, qc.json, run.json). |
| **Export pipeline writer** | `barakuda/devices/optical_tweezers/export/exporter.py` — `OTExporter` writes pipeline outputs (e.g. `{video_stem}_trajectory.csv`, `{video_stem}_qc.json`) to a given output_dir. Used by OTPipeline during run. |
| **Export package** | `barakuda/devices/optical_tweezers/export/__init__.py` — exports `discover_analysis_artifacts`, `OTExporter`. |
| **Export tab UI** | `barakuda/devices/optical_tweezers/ui/panel.py` — Export tab: `set_dataset_path`, `set_export_paths`, `_refresh_export_status`, `_refresh_export_artifact_checkboxes`, `_on_export_all_clicked`. |
| **Dataset selection → Export** | `barakuda/shell/main_window.py` — `_on_item_selected` calls `_device_panel.set_dataset_path(str(path))` and `_device_panel.set_export_paths(self.dataset.get_selected_paths())`. |
| **Post-run refresh** | `barakuda/shell/main_window.py` — In `_on_ot_done`, calls `_device_panel.set_dataset_path(str(paths[0]))` to refresh Export tab after batch run. |
| **Export execution** | `barakuda/devices/optical_tweezers/ui/panel.py` — `_on_export_all_clicked` copies selected artifacts from item_root/art["path"] to item_root/exports/ (uses discovery result paths). |

### Experiment Registry

| Area | Location |
|------|----------|
| **Core registry** | `barakuda/core/experiment_registry.py` — `create_experiment`, `load_experiment`, `list_experiments`, `discover_experiments`, `list_datasets`, `get_dataset_artifacts`, `get_experiment_summary`, `compare_datasets`, `export_experiment`, `register_dataset_to_experiment`. |
| **Experiment creation** | `barakuda/core/experiment_registry.py` — `create_experiment(runs_folder, experiment_id)`. |
| **Dataset registration** | `barakuda/core/experiment_registry.py` — `register_dataset_to_experiment(runs_folder, dataset_path, experiment_id, copy=...)`. |
| **Discovery** | `barakuda/core/experiment_registry.py` — `discover_experiments(runs_folder)`; scans `runs/experiments/`, loads each `experiment.json`. |
| **Experiment summary** | `barakuda/core/experiment_registry.py` — `get_experiment_summary(experiment_path)`. |
| **Dataset artifacts** | `barakuda/core/experiment_registry.py` — `get_dataset_artifacts(dataset_path)`; inspects `dataset_path/analysis/` and `dataset_path/exports/` using fixed filenames in `_ANALYSIS_FILE_TO_ARTIFACT`. |
| **Dataset comparison** | `barakuda/core/experiment_registry.py` — `compare_datasets(dataset_paths)`; uses `_read_trajectory_stats(analysis_dir)` which expects `analysis_dir/trajectory.csv`, `_read_psd_curves(analysis_dir)` expects `psd.csv`, `_read_drift_stats(analysis_dir)` expects `run.json`. |
| **Experiment export** | `barakuda/core/experiment_registry.py` — `export_experiment(experiment_path, output_dir, include_artifacts=...)`. |

**UI wiring for Experiment Registry:** No UI found that calls `discover_experiments`, `create_experiment`, `register_dataset_to_experiment`, `get_experiment_summary`, `compare_datasets`, or `export_experiment`. The registry is backend-only.

---

## 2. Checklist Status

### PART 1 — EXPORT

| Item | Status | Notes |
|------|--------|--------|
| **Export 1.1 Artifact discovery** | **PARTIAL** | `discover_analysis_artifacts` exists and is used, but looks for fixed names (`trajectory.csv`, etc.) under `dataset_root/analysis/`. Pipeline writes stem-prefixed names (e.g. `{stem}_trajectory.csv`) and may write under `module/ot/` or `module/ot/ot_v2_shadow/`. Discovery returns empty for current layout. |
| **Export 1.2 Dynamic Export tab checkboxes** | **PARTIAL** | Checkboxes are built from discovery result and grouped (DATA / REPORTS / PLOTS). Because discovery often returns no artifacts, checkboxes are often empty. |
| **Export 1.3 Auto refresh** | **PASS** | On item selection and after OT run completion, main_window calls `set_dataset_path` so Export tab status and checkboxes are refreshed. |
| **Export 1.4 Export execution** | **PARTIAL** | `_on_export_all_clicked` copies selected artifacts to `item_root/exports/`. Uses paths from discovery; when discovery returns wrong/empty paths, execution does nothing or copies wrong files. |
| **Export 1.5 Batch export** | **PASS** | `set_export_paths` receives multiple selected paths; `_on_export_all_clicked` iterates `paths_to_export` (from `_export_paths` or single dataset). |
| **Export 1.6 Checkbox groups** | **PASS** | DATA (trajectory_csv, tracking_csv, psd_csv), REPORTS (qc_report, run_json), PLOTS (empty). Implemented in `_refresh_export_artifact_checkboxes`. |

### PART 2 — EXPERIMENT REGISTRY

| Item | Status | Notes |
|------|--------|--------|
| **Experiment 2.1 Core registry** | **PASS** | create_experiment, load_experiment, list_experiments, discover_experiments, list_datasets implemented and operate on `runs/experiments/`. |
| **Experiment 2.2 Dataset registration** | **PARTIAL** | Backend: `register_dataset_to_experiment` implemented. UI: no screen or action to register a dataset to an experiment. |
| **Experiment 2.3 Discovery** | **PARTIAL** | Backend: `discover_experiments` implemented. UI: no experiment list, no discovery call from shell. |
| **Experiment 2.4 Experiment summary** | **PARTIAL** | Backend: `get_experiment_summary` implemented. UI: no experiment summary view. |
| **Experiment 2.5 Dataset artifacts** | **PARTIAL** | `get_dataset_artifacts` looks at `dataset_path/analysis/` for fixed filenames (trajectory.csv, tracking.csv, psd.csv, qc.json, run.json). Same filename/layout mismatch as Export discovery; stem-prefixed and subdir layouts not matched. |
| **Experiment 2.6 Dataset comparison** | **PARTIAL** | Backend: `compare_datasets` and helpers (`_read_trajectory_stats`, `_read_psd_curves`, `_read_drift_stats`) implemented but expect `analysis_dir/trajectory.csv`, `analysis_dir/psd.csv`, `analysis_dir/run.json`. UI: no comparison view. |
| **Experiment 2.7 Experiment export** | **PARTIAL** | Backend: `export_experiment` implemented. UI: no action to trigger experiment export. |

---

## 3. FAIL / PARTIAL — Details

### Export

| Item | Affected function/class/file | Reason | Category |
|------|------------------------------|--------|----------|
| **1.1 Artifact discovery** | `discover_analysis_artifacts` / `discovery.py` | Expects `dataset_root/analysis/<fixed_name>` (e.g. `trajectory.csv`). Pipeline writes `{video_stem}_trajectory.csv` and may write under `analysis/` or `module/ot/ot_v2_shadow/`. No glob or manifest-based resolution. | **Data model / export path handling** |
| **1.2 Dynamic checkboxes** | `_refresh_export_artifact_checkboxes` / `panel.py` | Checkboxes are correct but fed by discovery; when discovery returns [], checkboxes are empty. | **UI wiring (depends on discovery)** |
| **1.4 Export execution** | `_on_export_all_clicked` / `panel.py` | Uses `art["path"]` from discovery (e.g. `analysis/trajectory.csv`). Actual files are stem-prefixed and possibly in subdirs; copy source path wrong or missing. | **Export path handling** |

### Experiment Registry

| Item | Affected function/class/file | Reason | Category |
|------|------------------------------|--------|----------|
| **2.2 Dataset registration** | (no UI) | `register_dataset_to_experiment` exists but no menu/tool/dialog to call it. | **UI wiring** |
| **2.3 Discovery** | (no UI) | `discover_experiments` not called from shell; no experiment list in UI. | **UI wiring** |
| **2.4 Experiment summary** | (no UI) | `get_experiment_summary` not exposed in UI. | **UI wiring** |
| **2.5 Dataset artifacts** | `get_dataset_artifacts` / `experiment_registry.py` | Uses `_ANALYSIS_FILE_TO_ARTIFACT` with fixed filenames; does not account for stem-prefixed or legacy layout. | **Data model mismatch** |
| **2.6 Dataset comparison** | `_read_trajectory_stats`, `_read_psd_curves`, `_read_drift_stats` / `experiment_registry.py` | Expect `analysis_dir/trajectory.csv`, `analysis_dir/psd.csv`, `analysis_dir/run.json`. Real layout uses stem-prefixed and/or subdirs. No UI to run comparison. | **Backend path handling + UI wiring** |
| **2.7 Experiment export** | (no UI) | `export_experiment` exists; no UI to choose experiment and run export. | **UI wiring** |

---

## 4. Final Section

### Smallest safe first repair step

- **Align artifact discovery with actual layout.** In `discovery.py`, do not assume only `dataset_root/analysis/` with fixed filenames. Either:
  - Resolve analysis dir via manifest (e.g. use OT manifest’s `analysis_dir` when `item.json` is present), and discover artifacts by pattern (e.g. `*_trajectory.csv`, `*_qc.json`, `run.json`, etc.) under that dir and any known subdirs (e.g. `tracking/`, `physics/`, `ot_v2_shadow/`), or
  - Add a small adapter that maps manifest `analysis` paths (from `build_item_manifest_payload` / item.json) to the list of artifacts with id/label/path for the Export tab.
- Keep discovery output shape (id, label, path) so Export tab and export execution need no UI changes. No schema renames or dataset layout changes.

### Recommended repair order for remaining steps

1. **Fix Export artifact discovery** (path + naming) so Export tab shows real artifacts and export execution copies the correct files.
2. **Unify experiment_registry artifact resolution** with the same rules (manifest + patterns / subdirs) so `get_dataset_artifacts`, `_read_trajectory_stats`, `_read_psd_curves`, `_read_drift_stats` work on current layout.
3. **Wire Experiment Registry into UI**: discovery (experiment list), create, register dataset, summary, compare, export (one small step at a time, one commit per step).

### Branch and partial implementation note

- **Current branch at audit time:** `ot-dataset-integration`. Task requested branch: `integration/export-experiment-registry-fix`. If you create/use `integration/export-experiment-registry-fix`, ensure no unfinished partial change is left on that branch (e.g. half-renamed fields or half-switched discovery) before applying the first repair step above.

---

*End of audit. No runtime code was modified; this file is documentation only.*
