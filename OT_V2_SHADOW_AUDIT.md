# OT v2 Shadow Audit

## 1. PURPOSE

This audit documents the current `ot_v2_shadow` subdirectory in BARAKUDA's OT output layout. The goal is to identify which artifacts in `ot_v2_shadow` are still necessary, which duplicate artifacts elsewhere, and what the smallest safe de-duplication path is. This prepares safe migration steps without breaking the deterministic workflow. No runtime code is modified in this step.

---

## 2. CURRENT CONTENT OF `ot_v2_shadow`

`ot_v2_shadow` is created **only in non-dataset mode** (legacy batch). In dataset mode, OTPipeline writes directly into `run_dir` (analysis/); no `ot_v2_shadow` subdirectory is used.

When present, `ot_v2_shadow/` is `run_dir/ot_v2_shadow/` where `run_dir` is `item_root/module/ot/`. Its contents are produced entirely by **OTExporter** (called from **OTPipeline**):

| File(s) | Written by | Content |
|---------|------------|---------|
| `{stem}_camera_meta.json` | OTExporter | Camera metadata (fps, exposure_ms, gain, roi_w/h, timestamps, um_per_px). |
| `{stem}_qc.json` | OTExporter | QC audit dict from pipeline `compute_qc`. |
| `{stem}_trajectory.csv` | OTExporter | Trajectory with columns: t_s, x_px, y_px, confidence, x_um, y_um, x_corr_px, y_corr_px, lost, lost_reason (+ x_corr_um, y_corr_um if scaled). |
| `{stem}_derived.csv` | OTExporter | Derived physics per axis (mode, strategy, axis, fc_hz, k_pN_um, etc.). |
| `results.csv` | OTExporter | Canonical results.csv (Bible V3) — single file for all axes. |
| `{stem}_ot_summary.json` | OTExporter | Full audit summary: camera_meta, preprocess, qc, strategy, result_dict, artifacts, trajectory metadata. |
| `run_manifest.json` | OTExporter | Index: video_file, summary_file, trajectory_file, results_file, camera_meta_file, qc_file, artifacts. |
| `{export_prefix}psd_*.png`, `{export_prefix}drag_*.png` | OTExporter | Strategy plots (e.g. welch_psd_*.png, procfft_psd_*.png). |
| `{export_prefix}*.json` | OTExporter | Fallback JSON for strategy dicts (if not psd/drag plot). |

Source: `barakuda/devices/optical_tweezers/export/exporter.py` `write_all()`.

---

## 3. OVERLAP WITH OTHER OT OUTPUTS

The same run produces **two parallel pipelines**:

1. **Batch path**: `batch_controller` + `postprocess_ot` → `run_dir/audit/`, `run_dir/tracking/`, `run_dir/physics/`, root.
2. **OTPipeline path**: `OTPipeline` + `OTExporter` → `run_dir/ot_v2_shadow/` (non-dataset) or `run_dir/` (dataset).

Overlap matrix:

| Logical artifact | Batch path (audit/tracking/physics/root) | ot_v2_shadow |
|------------------|------------------------------------------|--------------|
| **Trajectory** | `tracking/{stem}_trajectory.csv` (frame, t_s, x_px, y_px, quality, peak, roi, …) | `{stem}_trajectory.csv` (t_s, x_px, y_px, confidence, x_um, y_um, x_corr_px, y_corr_px, lost, lost_reason) |
| **QC** | Root `{stem}_qc.png` (QC plot); audit has postprocess/psd_fit/calibration | `{stem}_qc.json` (QC audit dict) |
| **Calibration / fit** | `audit/{stem}_postprocess.json`, `_psd_fit.json`, `_calibration.json` | `*_ot_summary.json` (embeds strategy results, drift, qc) |
| **Camera meta** | Implicit in run.json, postprocess, calibration | `{stem}_camera_meta.json` |
| **Derived physics** | `physics/{stem}_derived.csv`, `_msd.csv`, `_psd_*.csv`, `_calibration.csv`, `_hist_*.csv` | `{stem}_derived.csv`, `results.csv` |
| **Strategy plots** | None (batch path uses postprocess_ot QC plot only) | `{export_prefix}psd_*.png`, `{export_prefix}drag_*.png` |
| **Run index** | Root `run.json` | `run_manifest.json` |

Same logical data (trajectory, physics, QC) exists in **two formats and two locations** in non-dataset mode. The OTPipeline uses different tracking/preprocess/qc modules than the batch path, so results can differ slightly.

---

## 4. DUPLICATE / TRANSITIONAL / CANONICAL CLASSIFICATION

| Artifact | Classification | Notes |
|----------|----------------|-------|
| `{stem}_trajectory.csv` | **DUPLICATE** | Same run; batch path has canonical trajectory in `tracking/`. Shadow has alternate schema (drift-corrected, QC columns). |
| `{stem}_qc.json` | **DUPLICATE** | Batch path has QC in postprocess summary and `{stem}_qc.png`; shadow has JSON QC audit. |
| `{stem}_camera_meta.json` | **TRANSITIONAL** | Not produced by batch path; useful for pipeline-only consumers. Overlaps with run.json + calibration. |
| `{stem}_derived.csv` | **DUPLICATE** | Batch path has `physics/{stem}_derived.csv`; same logical content, different format. |
| `results.csv` | **TRANSITIONAL** | Batch path has `{stem}_results.csv` (bundle) and `{stem}_results.xlsx`; shadow has canonical `results.csv` (Bible V3). |
| `{stem}_ot_summary.json` | **TRANSITIONAL** | Single-file audit; batch path has postprocess, psd_fit, calibration in audit/. |
| `run_manifest.json` | **TRANSITIONAL** | Index; batch path has `run.json`. |
| `{export_prefix}psd_*.png`, `{export_prefix}drag_*.png` | **CANONICAL** | Only produced by OTPipeline; batch path has `{stem}_qc.png` (PSD+MSD) but not strategy-specific plots. |
| `{export_prefix}*.json` (strategy fallback) | **TRANSITIONAL** | Strategy-specific; batch path does not emit these. |

---

## 5. CURRENT CODE PATHS WRITING INTO `ot_v2_shadow`

| Location | Behavior |
|----------|----------|
| `batch_controller.py` lines ~866–874 | `shadow_dir = run_dir / "ot_v2_shadow"` when `_dataset_item_root is None`; else `shadow_dir = run_dir`. |
| `batch_controller.py` lines ~849–895 | Import `OTPipeline`, `OTExporter`; create `OTExporter(shadow_dir)`; run `pipeline.run(str(file_path), shadow_config)`. |
| `orchestrator.py` | `OTPipeline.run()`: load video → track → preprocess → qc → strategy → `exporter.write_all()`. |
| `exporter.py` | `OTExporter.write_all()`: writes all 8 artifact types into `self.output_dir` (shadow_dir or run_dir). |

Invocation order: OTPipeline runs **before** the batch_controller tracking loop for the same video. So the same video is tracked and processed twice: once by OTPipeline (shadow), once by batch_controller (main path).

---

## 6. RISKS OF REMOVAL OR REDIRECTION

1. **Consumers of ot_v2_shadow**: `discover_analysis_artifacts()` uses `analysis_root.rglob("*")` over `analysis/` and `module/ot/`, so it finds files under `module/ot/ot_v2_shadow/`. Export and discovery would miss those files if `ot_v2_shadow` were removed or relocated.
2. **Manifest resolution**: `manifest.py` looks for `qc_json_path` and `*_ot_summary.json` under `analysis_dir` via `_first_existing` / `_glob_first`. In legacy layout, `analysis_dir` can resolve to `module/ot/`, so `module/ot/ot_v2_shadow/*_qc.json` and `*_ot_summary.json` are discoverable via rglob.
3. **Schema differences**: Shadow trajectory has drift-corrected columns and QC flags; batch trajectory has raw + postprocess. Any consumer expecting shadow schema would break if shadow were removed.
4. **Strategy plots**: PSD and drag plots exist only in ot_v2_shadow (or run_dir in dataset mode). Removing shadow without redirecting would lose these.
5. **Determinism**: Changing where OTPipeline writes without changing what it writes could affect downstream scripts or reports that hardcode paths.

---

## 7. EXACT NEXT SAFE PATCH

**Goal**: One smallest safe step to reduce duplication without breaking consumers.

**Suggested step**: In non-dataset mode, **redirect** OTPipeline output from `run_dir/ot_v2_shadow/` to `run_dir/` (i.e. write into the same root as dataset mode), but **keep a single consolidated OTPipeline output location** to avoid scattering files. Specifically:

- **Option A (minimal)**: Change `shadow_dir` in non-dataset mode from `run_dir / "ot_v2_shadow"` to `run_dir` (same as dataset mode). OTPipeline would then write into `run_dir/` directly: `{stem}_trajectory.csv`, `{stem}_qc.json`, etc. would appear alongside batch outputs. **Risk**: Name collisions (batch writes `tracking/{stem}_trajectory.csv`, OTPipeline would write `{stem}_trajectory.csv` to root — different paths, so no collision). But `results.csv` (OTExporter) vs `{stem}_results.csv` (batch) — different names. `{stem}_derived.csv` — OTPipeline writes to root; batch writes to `physics/`. So OTPipeline writing to root would create `run_dir/{stem}_derived.csv`, `run_dir/{stem}_trajectory.csv`, etc. The organize block does not move OTPipeline outputs; it only moves batch outputs. So we'd end up with OTPipeline files at root. That would **increase** root clutter, not reduce it. So Option A is not ideal.

- **Option B (structured redirect)**: Redirect OTPipeline to write into `run_dir/ot_v2_shadow/` but **do not run OTPipeline at all** in non-dataset mode when the batch path has already produced equivalent outputs. That would require skipping the OTPipeline call — a larger behavioral change.

- **Option C (consolidate, smallest)**: **Stop creating `ot_v2_shadow` in non-dataset mode** and instead pass `run_dir` as the exporter output (same as dataset mode). OTPipeline would write into `run_dir/` directly. The batch path writes into `run_dir/audit/`, `run_dir/tracking/`, `run_dir/physics/`. OTPipeline writes flat: `{stem}_trajectory.csv`, `{stem}_qc.json`, `{stem}_camera_meta.json`, `{stem}_derived.csv`, `results.csv`, `{stem}_ot_summary.json`, `run_manifest.json`, strategy plots. So we'd have both batch (structured) and OTPipeline (flat) files in/under run_dir. The organize block only moves batch outputs. OTPipeline outputs would remain where written. So we'd have:
  - `run_dir/{stem}_trajectory.csv` (OTPipeline) — **duplicate** of `run_dir/tracking/{stem}_trajectory.csv` (batch)
  - `run_dir/{stem}_qc.json` (OTPipeline)
  - `run_dir/{stem}_camera_meta.json`, `run_dir/{stem}_derived.csv`, `run_dir/results.csv`, `run_dir/{stem}_ot_summary.json`, `run_dir/run_manifest.json`, strategy plots

  That would **add** root-level clutter, not reduce it.

- **Option D (smallest safe de-duplication)**: **Disable the OTPipeline run** in non-dataset mode. The batch path already produces trajectory, physics, QC, calibration. The only unique OTPipeline artifacts are: strategy plots (psd_*, drag_*), ot_summary.json, run_manifest.json, and the alternate trajectory/qc/derived schema. If no consumer requires those in non-dataset mode, we could skip OTPipeline when `_dataset_item_root is None`. **Risk**: Strategy plots would be lost; any consumer of ot_summary or run_manifest would break.

Given the constraints (smallest safe step, no broad refactor), the **exact next safe patch** is:

- **File**: `barakuda/shell/batch_controller.py`
- **Change**: Add a **configurable kill switch** (e.g. env var or run_config flag) to **skip** the OTPipeline run in non-dataset mode when set. Default: keep current behavior (run OTPipeline, write to ot_v2_shadow). When the flag is enabled, skip the OTPipeline block entirely. This allows testing de-duplication without breaking existing runs.
- **Alternative (simpler, no new config)**: **Document** that the smallest safe runtime change is to redirect `shadow_dir` from `run_dir / "ot_v2_shadow"` to a **new** subdir `run_dir / "pipeline"` (or similar) so that OTPipeline outputs are grouped but not mixed with batch outputs, and so that `ot_v2_shadow` is no longer created. Consumers that scan for ot_v2_shadow would need to be updated to scan `pipeline/` instead. This is a rename, not a removal — lower risk.

**Recommended exact next safe patch** (minimal, no new config):

- **Change**: In non-dataset mode, set `shadow_dir = run_dir / "pipeline"` instead of `run_dir / "ot_v2_shadow"`. Create `run_dir/pipeline/` and pass it to OTExporter. No other changes.
- **Rationale**: (1) Renames the output dir from `ot_v2_shadow` to `pipeline`, clarifying that it holds OTPipeline outputs. (2) Does not remove or skip OTPipeline; all outputs are preserved. (3) Prepares for a future step where `pipeline/` can be deprecated or consolidated once consumers are updated. (4) No change to dataset mode.

---

## 8. VERIFY PLAN

1. **Branch**: Checkout `integration/ot-output-layout-simplification`.
2. **Apply patch**: Change `shadow_dir` from `run_dir / "ot_v2_shadow"` to `run_dir / "pipeline"` in non-dataset mode.
3. **Run OT batch** in legacy (non-dataset) mode on one or more files.
4. **Check layout**: Under `runs/ot/<batch_id>/<item_id>/module/ot/`:
   - `ot_v2_shadow/` should **not** exist.
   - `pipeline/` should exist and contain: `{stem}_camera_meta.json`, `{stem}_qc.json`, `{stem}_trajectory.csv`, `{stem}_derived.csv`, `results.csv`, `{stem}_ot_summary.json`, `run_manifest.json`, strategy plots.
5. **Dataset mode**: Run OT on a dataset item; confirm OTPipeline still writes into `analysis/` (run_dir) with no `pipeline/` or `ot_v2_shadow` subdir.
6. **Discovery**: Run artifact discovery on the item; confirm files under `pipeline/` are found (discovery uses rglob over module/ot).
