# OT v2 Shadow — Diagnostic Audit Report

**Branch:** `integration/ot-output-layout-simplification`  
**Date:** 2026-03-09  
**Scope:** Focused diagnostic only. No runtime code modified in this step.

---

## 1. PURPOSE

This audit isolates the remaining OT layout clutter before any cleanup patch is attempted. It identifies exactly which files in `module/ot/ot_v2_shadow` are still required, which duplicate outputs elsewhere in the OT layout, which root-level `module/ot` files are legacy export-style clutter, and what the smallest safe de-duplication / cleanup path is. The goal is to prepare safe migration steps without breaking the deterministic workflow.

---

## 2. CURRENT CONTENT OF `ot_v2_shadow`

`ot_v2_shadow` is created **only in non-dataset mode** (legacy batch). In dataset mode, OTPipeline writes directly into `run_dir` (analysis/); no `ot_v2_shadow` subdirectory is used.

When present, `ot_v2_shadow/` is `run_dir/ot_v2_shadow/` where `run_dir` is `item_root/module/ot/`. Its contents are produced entirely by **OTExporter** (called from **OTPipeline**):

| File(s) | Semantic role | Written by |
|---------|---------------|------------|
| `{stem}_camera_meta.json` | Camera metadata (fps, exposure_ms, gain, roi, um_per_px) | OTExporter |
| `{stem}_qc.json` | QC audit dict from pipeline `compute_qc` | OTExporter |
| `{stem}_trajectory.csv` | Drift-corrected trajectory (t_s, x_px, y_px, confidence, x_um, y_um, x_corr_px, y_corr_px, lost, lost_reason) | OTExporter |
| `{stem}_derived.csv` | Derived physics per axis (mode, strategy, axis, fc_hz, k_pN_um, eta_Pa_s, etc.) | OTExporter |
| `results.csv` | Canonical Bible V3 results — single file for all axes | OTExporter |
| `{stem}_ot_summary.json` | Full audit summary: camera_meta, preprocess, qc, strategy, result_dict, artifacts | OTExporter |
| `run_manifest.json` | Index: video_file, summary_file, trajectory_file, results_file, camera_meta_file, qc_file, artifacts | OTExporter |
| `welch_psd_x.png`, `welch_psd_y.png` (or `{export_prefix}psd_*.png`) | Strategy PSD plots | OTExporter |
| `{export_prefix}drag_*.png` | Strategy drag plots (when applicable) | OTExporter |
| `{export_prefix}*.json` | Fallback JSON for strategy dicts (if not psd/drag plot) | OTExporter |

Source: `barakuda/devices/optical_tweezers/export/exporter.py` `write_all()`.

---

## 3. ROOT-LEVEL `module/ot` LEGACY OUTPUTS

Files written directly into `module/ot` root (not in subdirs):

| File | Writer | Legacy export-style? |
|------|--------|----------------------|
| `run.json` | batch_controller | No — canonical run metadata |
| `{stem}_qc.png` | Moved from tracking/ (postprocess_ot) | Yes — QC plot; could live in audit/ or tracking/ |
| `{stem}_results.csv` | Batch bundle write | Yes — combined trajectory/postprocess; could live in physics/ or results/ |
| `{stem}_results.xlsx` | Batch XLSX export | Yes — export bundle; could live in structured subdir |
| `{stem}_hist_r.png`, `_hist_x.png`, `_hist_y.png` | postprocess_ot (if at root) | Yes — histograms; batch path moves hist CSVs to physics/, hist PNGs stay in tracking/ per current code |

**Note:** In the current layout, postprocess_ot writes hist PNGs and qc.png to `tracking/`; the organize block moves `{stem}_qc.png` to root but does **not** move hist PNGs, so hist PNGs remain in `tracking/`. Root-level legacy clutter is primarily: `run.json` (canonical), `{stem}_qc.png`, `{stem}_results.csv`, `{stem}_results.xlsx`. In **dataset mode**, OTExporter also writes flat files into `run_dir` (analysis/) root: `{stem}_trajectory.csv`, `{stem}_qc.json`, `{stem}_camera_meta.json`, `{stem}_derived.csv`, `results.csv`, `{stem}_ot_summary.json`, `run_manifest.json`, strategy plots. Those are legacy export-style when they duplicate structured outputs.

---

## 4. OVERLAP WITH OTHER OT OUTPUTS

| Artifact | ot_v2_shadow | tracking | physics | audit | preview | root module/ot | Overlap type |
|----------|--------------|----------|---------|-------|---------|----------------|--------------|
| **Trajectory** | `{stem}_trajectory.csv` | `{stem}_trajectory.csv` | — | — | — | — (dataset) | **RELATED BUT NOT SAME** — different schema (drift-corrected vs raw; QC columns) |
| **QC** | `{stem}_qc.json` | — | — | — | — | `{stem}_qc.png` | **RELATED BUT NOT SAME** — JSON audit vs PNG plot |
| **Calibration** | Embedded in `{stem}_ot_summary.json` | — | `{stem}_calibration.csv` | `{stem}_calibration.json`, `_psd_fit.json` | — | — | **SAME LOGICAL ARTIFACT** — calibration data in multiple formats |
| **Derived physics** | `{stem}_derived.csv`, `results.csv` | — | `{stem}_derived.csv` | — | — | — | **SAME LOGICAL ARTIFACT** — derived physics duplicated |
| **Camera meta** | `{stem}_camera_meta.json` | — | — | Implicit in postprocess | — | — | **RELATED BUT NOT SAME** — explicit vs implicit in run.json |
| **Run index** | `run_manifest.json` | — | — | — | — | `run.json` | **RELATED BUT NOT SAME** — different index format |
| **Strategy plots** | `welch_psd_*.png` | — | — | — | — | — | **No overlap** — OTPipeline-only |
| **Preview** | — | — | — | — | `preview_report.json`, `{stem}_preview_tracking.png` | — | **No overlap** — preview is separate |

---

## 5. CURRENT CODE PATHS

### Write paths — ot_v2_shadow

| File / function | Location | Behavior |
|-----------------|----------|----------|
| `shadow_dir = run_dir / "ot_v2_shadow"` | `batch_controller.py` ~868–871 | When `_dataset_item_root is None`; else `shadow_dir = run_dir` |
| `shadow_dir.mkdir(parents=True, exist_ok=True)` | `batch_controller.py` ~873 | Creates ot_v2_shadow |
| `OTExporter(shadow_dir)` | `batch_controller.py` ~874 | Exporter writes into shadow_dir |
| `pipeline.run(str(file_path), shadow_config)` | `batch_controller.py` ~893 | OTPipeline invokes exporter |
| `OTExporter.write_all(...)` | `exporter.py` | Writes all artifact types into `self.output_dir` (shadow_dir) |
| `OTPipeline.run()` | `orchestrator.py` | Orchestrates load → track → preprocess → qc → strategy → export |

### Write paths — root-level module/ot

| File / function | Location | Behavior |
|-----------------|----------|----------|
| `(run_dir / "run.json").write_text(...)` | `batch_controller.py` ~793, 819 | Run metadata |
| `_move_to(_tracking / f"{stem}_qc.png", run_dir)` | `batch_controller.py` ~1338 | Organize moves QC plot from tracking/ to root |
| Bundle write (results.csv, results.xlsx) | `batch_controller.py` ~1218–1340 | Writes `{stem}_results.csv`, `{stem}_results.xlsx` to run_dir |
| `OTExporter(run_dir)` (dataset mode) | `batch_controller.py` ~869 | When `_dataset_item_root is not None`; exporter writes flat files to run_dir root |

### Read paths

| Consumer | Location | Reads |
|----------|----------|-------|
| `discover_analysis_artifacts()` | `export/discovery.py` | `rglob("*")` over `analysis/` and `module/ot/` — finds all files including ot_v2_shadow |
| `load_item_manifest()` | `manifest.py` | `qc_json_path` via `_first_existing` / `_glob_first`; `trajectory_path`; `*_ot_summary.json`; `preview_report_path` |
| `build_item_manifest_payload()` | `manifest.py` | `artifacts_inventory` via `item_root.rglob("*")` |
| `item.json` analysis field | Written by batch | Points trajectory, qc, summary to ot_v2_shadow paths when present |

---

## 6. CLASSIFICATION

| Artifact | Classification | Notes |
|----------|----------------|-------|
| `run.json` | **CANONICAL CANDIDATE** | Run metadata; required |
| `tracking/{stem}_trajectory.csv` | **CANONICAL CANDIDATE** | Batch trajectory; canonical for batch path |
| `physics/{stem}_derived.csv`, `_msd.csv`, `_psd_*.csv`, `_calibration.csv`, `_hist_*.csv` | **CANONICAL CANDIDATE** | Physics outputs |
| `audit/{stem}_postprocess.json`, `_psd_fit.json`, `_calibration.json` | **CANONICAL CANDIDATE** | Audit trail |
| `preview/preview_report.json`, `preview/{stem}_preview_tracking.png` | **CANONICAL CANDIDATE** | Preview outputs |
| `welch_psd_*.png` (strategy plots) | **CANONICAL CANDIDATE** | Only from OTPipeline; no batch equivalent |
| `{stem}_qc.png` at root | **LEGACY CANDIDATE** | Moved from tracking/; could live in audit/ |
| `{stem}_results.csv`, `{stem}_results.xlsx` at root | **LEGACY CANDIDATE** | Bundle outputs; could move to structured subdir |
| `ot_v2_shadow/{stem}_trajectory.csv`, `_qc.json`, `_derived.csv` | **DUPLICATE / TRANSITIONAL** | Overlap with batch path |
| `ot_v2_shadow/{stem}_camera_meta.json`, `_ot_summary.json`, `run_manifest.json` | **TRANSITIONAL** | OTPipeline-only; useful for pipeline consumers |
| `ot_v2_shadow/results.csv` | **DUPLICATE / TRANSITIONAL** | Bible V3; batch has `{stem}_results.csv` |
| Rename ot_v2_shadow → pipeline | **NEEDS DECISION** | Clarifies purpose; consumers must be updated |

---

## 7. RISKS OF CLEANUP

| Risk | Level | Notes |
|------|-------|-------|
| Breaking manifest resolution | **MEDIUM** | Manifest points trajectory, qc, summary to ot_v2_shadow paths. Renaming or removing requires updating manifest write logic and `_resolve_analysis_dir` / `_first_existing` / `_glob_first` usage. |
| Removing a still-read artifact | **MEDIUM** | Export discovery uses `rglob` over module/ot; any consumer expecting ot_v2_shadow paths would break. Strategy plots are read-only from OTPipeline. |
| Duplicating summary/result files | **LOW** | Cleanup would reduce duplication; risk is in *failing* to deduplicate consistently. |
| Breaking export checkbox inventory | **MEDIUM** | `discover_analysis_artifacts` finds files under module/ot (including ot_v2_shadow). Relocating would require discovery to scan new path. |
| Damaging OT reproducibility | **HIGH** | Changing write paths without updating all consumers (manifest, discovery, item.json build) could cause missing-artifact failures. Determinism requires consistent paths. |
| Skipping OTPipeline loses strategy plots | **MEDIUM** | If OTPipeline is disabled in non-dataset mode, welch_psd_*.png and other strategy plots would be lost. |
| Rename without consumer update | **LOW** | Renaming ot_v2_shadow to pipeline is low risk if discovery uses rglob (finds any subdir); manifest and item.json build must be checked. |

---

## 8. EXACT NEXT SAFE PATCH

**File:** `barakuda/shell/batch_controller.py`

**Change:** In non-dataset mode, set `shadow_dir = run_dir / "pipeline"` instead of `run_dir / "ot_v2_shadow"`. Create `run_dir/pipeline/` and pass it to OTExporter. No other changes.

**Code location:** Lines ~868–873:

```python
shadow_dir = (
    run_dir if _dataset_item_root is not None
    else run_dir / "pipeline"   # was: run_dir / "ot_v2_shadow"
)
```

**Required follow-up:** Update `manifest.py` and `build_item_manifest_payload` to resolve trajectory, qc, summary from `pipeline/` when present (e.g. add `pipeline/{stem}_trajectory.csv` etc. to resolution candidates, or ensure `_glob_first`/rglob finds files under pipeline/). Discovery already uses `rglob("*")` over `module/ot/`, so it will find `module/ot/pipeline/` files without change.

**Why smallest safe step:** (1) Renames output dir from `ot_v2_shadow` to `pipeline`, clarifying purpose. (2) Does not remove or skip OTPipeline; all outputs preserved. (3) Does not change dataset mode. (4) **Caveat:** item.json `build_item_manifest_payload` and manifest resolution may need to be updated so that trajectory/qc/summary paths point to `pipeline/` when that subdir exists; otherwise existing consumers (e.g. Export tab, manifest-based tools) may not find artifacts. The *minimal* patch that avoids breaking consumers is: rename + add `pipeline/` to manifest/discovery scan. If manifest currently uses `_glob_first(ad, "*_trajectory.csv")` etc., it may already find files under pipeline/ via rglob — verification needed.

**Simpler alternative (if manifest/build already scans subdirs):** Change only `shadow_dir` to `run_dir / "pipeline"` and verify that discovery and manifest resolution still find the files. If `analysis_dir` is `module/ot` and resolution uses patterns that match anywhere under it, no manifest change may be needed.

---

## 9. VERIFY PLAN

After applying the shadow_dir rename to `pipeline/`:

1. **Branch:** Confirm `integration/ot-output-layout-simplification`.
2. **Run OT batch** in non-dataset (legacy batch) mode on one or more files.
3. **Check layout:** Under `runs/ot/<batch_id>/<item_id>/module/ot/`:
   - `ot_v2_shadow/` should **not** exist.
   - `pipeline/` should exist and contain: `{stem}_camera_meta.json`, `{stem}_qc.json`, `{stem}_trajectory.csv`, `{stem}_derived.csv`, `results.csv`, `{stem}_ot_summary.json`, `run_manifest.json`, `welch_psd_*.png`.
4. **Manifest:** Load item via `load_item_manifest(item_json_path)`; confirm `m.trajectory_path`, `m.qc_json_path`, and summary path resolve correctly (either from `pipeline/` or via updated resolution).
5. **Export:** Open Export tab; confirm artifact discovery finds files under `pipeline/` and checkboxes appear.
6. **Dataset mode:** Run OT on a dataset item; confirm OTPipeline still writes into `analysis/` (run_dir) with no `pipeline/` or `ot_v2_shadow` subdir.
7. **Regression:** No dataset files moved or rewritten; only write destination changed for non-dataset mode.

---

*End of report. No runtime code was modified in this step.*
