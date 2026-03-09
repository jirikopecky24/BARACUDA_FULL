# OT Output Layout — Diagnostic Audit Report

**Branch:** `integration/ot-output-layout-simplification`  
**Date:** 2026-03-09  
**Scope:** Focused diagnostic only. No runtime code modified in this step.

---

## 1. PURPOSE

This audit maps exactly how OT (Optical Tweezers) preview, tracking, physics, QC, summary, audit, and legacy export-style outputs are currently written to disk. The goal is to prepare safe OT output layout simplification without breaking the deterministic workflow. The audit identifies split preview storage, root-level legacy output clutter, `ot_v2_shadow` duplication, empty placeholder directories, and classifies current outputs for subsequent minimal, safe patches.

---

## 2. CURRENT OT OUTPUT ROOTS

| Output root | Mode | Path | Created by |
|-------------|------|------|------------|
| **run_dir (dataset)** | Dataset | `item_root/analysis/` | `batch_controller.py` ~787–790: `run_dir = _item_root_for_run / "analysis"`; creates `audit/`, `tracking/`, `physics/` |
| **run_dir (new batch)** | Non-dataset | `item_root/module/ot/` | `batch_controller.py` ~812–817: `run_dir = _item_root_for_run / "module" / "ot"`; creates `audit/`, `tracking/`, `physics/` |
| **run_dir (standalone)** | Non-dataset | `runs_folder/<run_id>/` | `run_manager.create_run()`; `batch_controller` creates `audit/`, `tracking/`, `physics/` |
| **ot_v2_shadow** | Non-dataset only | `run_dir/ot_v2_shadow/` | `batch_controller.py` ~868–873: `shadow_dir = run_dir / "ot_v2_shadow"` when `_dataset_item_root is None` |
| **preview** | All OT runs | `run_dir/preview/` | `batch_controller.py` ~1006–1007: `dir_preview = run_dir / "preview"`; created when first overlay saved |
| **gate preview** | Gate run | `runs_folder/PREVIEW-<ts>/` | `batch_controller.py` ~236–237: `self._preview_dir = self.run_manager.runs_folder / f"PREVIEW-{ts}"` |
| **raw** | New batch only | `item_root/raw/` | `batch_controller.py` ~815: `(_item_root_for_run / "raw").mkdir(...)` |

---

## 3. PREVIEW STORAGE

### 3.1 Preview metadata

| Location | Path | Written by | Code path |
|----------|------|------------|-----------|
| **Gate run (temporary)** | `runs_folder/PREVIEW-<ts>/preview_report.json` | `run_preview_gate` | `batch_controller.py` ~520–522: `(self._preview_dir / "preview_report.json").write_text(...)` |
| **Per-run (copy)** | `run_dir/preview/preview_report.json` | Copy from gate | `batch_controller.py` ~1008–1012: `shutil.copy2(self._preview_dir / "preview_report.json", dir_preview / "preview_report.json")` |

### 3.2 Preview image outputs

| Location | Path | Written by | Code path |
|----------|------|------------|-----------|
| **Per-run** | `run_dir/preview/{stem}_preview_tracking.png` | `run_manager.save_overlay_png` | `batch_controller.py` ~1013–1020: `run_manager.save_overlay_png(run_dir=dir_preview, ..., name=f"{stem}_preview_tracking.png")` |

### 3.3 Split preview storage

**Yes.** Preview artifacts are split across two locations:

1. **Gate run (`PREVIEW-<ts>/`)**: The Preview Gate writes `preview_report.json` into a timestamped folder under `runs_folder/`. This folder is **outside** any item or run directory. It holds the gate report for all gate-checked files.
2. **Per-run (`run_dir/preview/`)**: When processing each run, the batch controller copies `preview_report.json` from the gate folder into `run_dir/preview/` and writes `{stem}_preview_tracking.png` there. So each run has its own copy of the gate report plus the overlay image.

**Manifest resolution gap**: `manifest.py` line 111 uses `_first_existing(ad, ["preview_report.json"])`, which looks only for `preview_report.json` directly under `analysis_dir`. It does **not** check `preview/preview_report.json`. When the report is stored at `run_dir/preview/preview_report.json` (e.g. `module/ot/preview/preview_report.json` or `analysis/preview/preview_report.json`), the manifest does **not** find it.

---

## 4. LEGACY ROOT-LEVEL OUTPUTS

Root-level files written directly into `run_dir` (i.e. `module/ot/` or `analysis/`):

| File | Writer | Purpose |
|------|--------|---------|
| `run.json` | `batch_controller` | Run metadata (run_id, created_at, input_path, config) |
| `{stem}_qc.png` | Moved from `tracking/` | QC plot (PSD + MSD); postprocess_ot writes to tracking/, organize moves to root |
| `{stem}_results.csv` | Batch bundle write | Combined trajectory/postprocess sections |
| `{stem}_results.xlsx` | Batch bundle write | XLSX export of results |
| **OTExporter (ot_v2_shadow / dataset run_dir)** | | |
| `{stem}_camera_meta.json` | OTExporter | Camera metadata |
| `{stem}_qc.json` | OTExporter | QC audit dict |
| `{stem}_trajectory.csv` | OTExporter | Drift-corrected trajectory |
| `{stem}_derived.csv` | OTExporter | Derived physics per axis |
| `results.csv` | OTExporter | Canonical Bible V3 results |
| `{stem}_ot_summary.json` | OTExporter | Full audit summary |
| `run_manifest.json` | OTExporter | Index of pipeline outputs |
| `{export_prefix}psd_*.png`, `welch_psd_*.png` | OTExporter | Strategy PSD plots |

**Classification**: `run.json` is canonical. `{stem}_qc.png`, `_results.csv`, `_results.xlsx` are batch-path outputs kept at root by design. OTExporter outputs in root (or `ot_v2_shadow`) are **legacy export-style** when they duplicate structured outputs in `tracking/`, `physics/`, `audit/`.

---

## 5. DUPLICATES / PARALLEL TRUTH

| Logical artifact | Batch path | ot_v2_shadow (or run_dir in dataset mode) | Same content? |
|------------------|------------|-------------------------------------------|---------------|
| **Trajectory** | `tracking/{stem}_trajectory.csv` (frame, t_s, x_px, y_px, quality, peak, roi…) | `{stem}_trajectory.csv` (t_s, x_px, y_px, confidence, x_um, y_um, x_corr_px, y_corr_px, lost, lost_reason) | No — different schema |
| **QC** | Root `{stem}_qc.png`; audit has postprocess/psd_fit/calibration | `{stem}_qc.json` | No — PNG vs JSON |
| **Derived physics** | `physics/{stem}_derived.csv` | `{stem}_derived.csv` | Similar — same logical data |
| **Calibration** | `audit/{stem}_calibration.json`, `physics/{stem}_calibration.csv` | Embedded in `{stem}_ot_summary.json` | Overlap |
| **MSD/PSD CSVs** | `physics/{stem}_msd.csv`, `{stem}_psd_x.csv`, `{stem}_psd_y.csv` | Not in ot_v2_shadow | — |
| **Strategy plots** | None | `welch_psd_*.png`, etc. | OTPipeline-only |
| **Run index** | Root `run.json` | `run_manifest.json` | Different format |

**Parallel pipelines**: The same run is processed by (1) **OTPipeline + OTExporter** (runs first, writes to `shadow_dir` or `run_dir`), and (2) **batch path** (tracking loop + postprocess_ot + organize). Both produce trajectory, QC, and physics artifacts; OTPipeline uses different modules and schema.

---

## 6. EMPTY PLACEHOLDER DIRECTORIES

| Directory | Created | Populated | Source |
|-----------|---------|-----------|--------|
| `audit/` | Always | Yes — postprocess JSONs, psd_fit, calibration | `batch_controller` ~790, 817, 836 |
| `tracking/` | Always | Yes — trajectory, after.png, after_raw.png, hist PNGs | `batch_controller` |
| `physics/` | Always | Yes — msd, psd, calibration CSV, hist CSVs, derived, compare | `batch_controller` organize |
| `preview/` | On first overlay save | Yes — preview_report.json, {stem}_preview_tracking.png | `batch_controller` ~1006–1020 |
| `raw/` | New-batch mode only | Yes — archived video | `batch_controller` ~815 |
| `ot_v2_shadow/` | Non-dataset mode only | Yes — OTExporter outputs | `batch_controller` ~871–873 |

**No empty placeholder directories** are created in the current OT flow. All created subdirs are populated by the same run. The merge review (OT_OUTPUT_LAYOUT_MERGE_REVIEW) mentions that an earlier change stopped creating `results/`, `qc/`, and `artifacts/` under item root in legacy batch mode; the current code creates only `raw/` at item level in new-batch mode.

---

## 7. CLASSIFICATION

| Output | Classification | Notes |
|--------|----------------|-------|
| `run.json` | **CANONICAL CANDIDATE** | Run metadata; required |
| `tracking/{stem}_trajectory.csv` | **CANONICAL CANDIDATE** | Batch trajectory; canonical for batch path |
| `tracking/{stem}_after.png`, `_after_raw.png` | **CANONICAL CANDIDATE** | Overlay images |
| `audit/{stem}_postprocess.json`, `_psd_fit.json`, `_calibration.json` | **CANONICAL CANDIDATE** | Audit trail |
| `physics/{stem}_msd.csv`, `_psd_*.csv`, `_calibration.csv`, `_hist_*.csv`, `_derived.csv` | **CANONICAL CANDIDATE** | Physics outputs |
| `preview/preview_report.json`, `preview/{stem}_preview_tracking.png` | **CANONICAL CANDIDATE** | Preview outputs; manifest should resolve `preview/preview_report.json` |
| `{stem}_qc.png` at root | **LEGACY CANDIDATE** | Moved from tracking/; could live in audit/ or tracking/ |
| `{stem}_results.csv`, `{stem}_results.xlsx` | **LEGACY CANDIDATE** | Bundle outputs; could move to structured subdir |
| **ot_v2_shadow contents** | **DUPLICATE / TRANSITIONAL** | Parallel to batch path; trajectory, derived, QC overlap |
| `{stem}_camera_meta.json`, `{stem}_ot_summary.json`, `run_manifest.json` | **TRANSITIONAL** | OTPipeline-only; useful for pipeline consumers |
| `welch_psd_*.png` (strategy plots) | **CANONICAL CANDIDATE** | Only from OTPipeline; no batch equivalent |
| `{stem}_trajectory.csv`, `{stem}_qc.json`, `{stem}_derived.csv` in ot_v2_shadow | **DUPLICATE / TRANSITIONAL** | Overlap with batch path |
| Manifest `preview_report_path` resolution | **NEEDS DECISION** | Add `preview/preview_report.json` to manifest candidates |

---

## 8. EXACT NEXT SAFE PATCH

**File:** `barakuda/devices/optical_tweezers/manifest.py`

**Change:** Add `preview/preview_report.json` to the list of candidates when resolving `preview_report_path`. Currently line 111 uses:

```python
m.preview_report_path = _first_existing(ad, ["preview_report.json"])
```

Change to:

```python
m.preview_report_path = _first_existing(ad, ["preview_report.json", "preview/preview_report.json"])
```

**Why smallest safe step:** (1) Preview metadata and image are already written to `run_dir/preview/`; the manifest simply does not look there. (2) One-line change; no schema or layout change. (3) Enables manifest-based consumers (e.g. Export tab, discovery) to find the preview report when it lives in `preview/`. (4) No change to write paths, OTPipeline, batch controller, or experiment registry.

---

## 9. VERIFY PLAN

After applying the manifest fix:

1. **Branch:** Confirm `integration/ot-output-layout-simplification`.
2. **Run OT** on a dataset or batch item that produces preview outputs (gate run + normal run).
3. **Check layout:** Confirm `run_dir/preview/preview_report.json` and `run_dir/preview/{stem}_preview_tracking.png` exist.
4. **Manifest:** Load `item.json` via `load_item_manifest`; confirm `m.preview_report_path` resolves to `.../preview/preview_report.json` (not None).
5. **Regression:** For items without `preview/` (e.g. old runs), confirm manifest still works and `preview_report_path` is None when neither candidate exists.
6. **No other changes:** Confirm only `manifest.py` was modified; no batch_controller, exporter, or discovery changes.

---

*End of report. No runtime code was modified in this step.*
