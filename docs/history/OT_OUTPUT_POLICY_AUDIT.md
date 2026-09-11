# OT Output Generation and Storage Policy — Diagnostic Audit

**Date:** 2026-03-09  
**Branch:** integration/export-policy-simplification  
**Scope:** Map current OT pipeline output generation and storage; no runtime code changes.

---

## 1. PURPOSE

This audit documents current BARAKUDA OT (optical tweezers) output generation and storage so that the next runtime step for canonical-output policy can be applied safely without breaking the deterministic workflow. It identifies what is produced by RUN, where it is stored, how it is classified (canonical vs optional export), and where behavior still diverges from the target policy (no proactive or empty `exports/`; JSON/XLSX canonical; CSV/PNG optional export).

---

## 2. CURRENT OUTPUT GENERATION

What the OT pipeline produces after RUN, by artifact type and producing code path.

### `.json`

| Artifact | Producing code path | Where written |
|----------|---------------------|----------------|
| `run.json` | `batch_controller.py`: `(run_dir / "run.json").write_text(...)` (dataset: ~794; legacy batch: ~818) | `item_root/analysis/` (dataset) or `item_root/module/ot/` (legacy batch) |
| `*_camera_meta.json` | `export/exporter.py` OTExporter.write_all: `meta_path = self.output_dir / f"{video_stem}_camera_meta.json"` | `output_dir` (= analysis/ or module/ot/ot_v2_shadow) |
| `*_qc.json` | `export/exporter.py` OTExporter.write_all: `qc_path = self.output_dir / f"{video_stem}_qc.json"` | same |
| `*_ot_summary.json` | `export/exporter.py` OTExporter.write_all: `summary_path = self.output_dir / f"{video_stem}_ot_summary.json"` | same |
| `run_manifest.json` | `export/exporter.py` OTExporter.write_all: `manifest_path = self.output_dir / "run_manifest.json"` | same |
| `*_postprocess.json`, `*_psd_fit.json`, `*_calibration.json` | `batch_controller.py` / `core/postprocess_ot.py` (fit_path, cal_json.write_text) | run_dir (then moved to run_dir/audit/) |
| `*_compare.json`, `*_drag.json` | `batch_controller.py`: drag_json.write_text, compare_json (e.g. ~1134, ~1183) | run_dir (then moved to physics/ or audit) |
| Strategy dict JSONs | `export/exporter.py` OTExporter.write_all: `fpath = self.output_dir / fname` (export_prefix+key+.json) | output_dir |
| `item.json` | `manifest.py` build_item_manifest_payload; `batch_controller.py` dataset mode update | item_root |
| `batch.json` | `batch_controller.py` | batch root |

### `.xlsx`

| Artifact | Producing code path | Where written |
|----------|---------------------|----------------|
| `*_results.xlsx` | `core/export_xlsx.py` `export_ot_results_xlsx(output_dir=run_dir, base_name=stem, ...)`; called from `batch_controller.py` ~1255 | run_dir (analysis/ or module/ot/) |

### `.csv`

| Artifact | Producing code path | Where written |
|----------|---------------------|----------------|
| `*_trajectory.csv` | `batch_controller.py`: `traj_path.open("w", ...)` ~914; also OTExporter.write_all `traj_path` | run_dir (batch) or output_dir (OTExporter); batch then moves to run_dir/tracking/ |
| `results.csv` (canonical) | `export/exporter.py` OTExporter.write_all: `canonical_path = self.output_dir / "results.csv"` | output_dir |
| `*_derived.csv` | `export/exporter.py` OTExporter.write_all: `results_path = self.output_dir / f"{video_stem}_derived.csv"` | output_dir |
| `*_results.csv` (bundle) | `batch_controller.py`: `results_csv = run_dir / f"{stem}_results.csv"` ~1265 | run_dir |
| `*_msd*.csv`, `*_psd*.csv`, `*_calibration.csv`, `*_hist_*.csv`, `*_compare.csv` | batch_controller / pipeline steps | run_dir then moved to physics/ or audit/ |

### `.png`

| Artifact | Producing code path | Where written |
|----------|---------------------|----------------|
| PSD/Drag strategy plots | `export/exporter.py` OTExporter.write_all: `_render_psd_plot`, `_render_drag_plot` → `plot_path = self.output_dir / plot_name` (.png) | output_dir |
| `*_after.png`, `*_after_raw.png`, `*_preview_tracking.png`, `*_qc.png` | batch_controller / pipeline | run_dir then moved to tracking/ or left in root |

### Other

- No other extension types are systematically produced by the OT pipeline in the code paths audited. Manifest and schema files (e.g. `item.json`) are covered above.

---

## 3. CURRENT STORAGE LAYOUT

- **Item root:** `item_root` = directory containing `item.json` (e.g. `runs/.../item_id/`).
- **Analysis roots:** Resolved by `manifest.py` `_resolve_analysis_dir`: (1) `raw["analysis"]["dir"]`, (2) `item_root/analysis/`, (3) `item_root/module/ot/`, (4) absolute `run_dir` from manifest. Dataset mode uses `item_root/analysis/`; legacy batch uses `item_root/module/ot/`.
- **Subfolders under run_dir (batch):** `audit/`, `tracking/`, `physics/` (and in legacy batch also `raw/`, `results/`, `qc/`, `artifacts/`). Created in `batch_controller.py` (e.g. ~789–790 dataset, ~813–814 legacy; ~1294–1298 for audit/tracking/physics).
- **`exports/`:** Intended for explicit user export only. In code:
  - **batch_controller.py** (~791): In **dataset mode**, `( _item_root_for_run / "exports" ).mkdir(parents=True, exist_ok=True)` runs at RUN start → **`exports/` is created proactively (empty) during analysis.**
  - **panel.py** (~1245–1246): `exports_dir = item_root / "exports"` and `exports_dir.mkdir(...)` only when there is at least one selected artifact to copy → **Export tab creates `exports/` only on explicit export with selection.**
- **Empty placeholder folders:** In dataset mode, batch_controller creates `item_root/analysis/`, `analysis/audit/`, `analysis/tracking/`, `analysis/physics/`, and **`item_root/exports/`** up front. So **empty `exports/` is still created during RUN** in dataset mode.
- **Duplication:** No automatic copy from analysis to `exports/`. User export copies selected optional artifacts from analysis (or module/ot) into `exports/`. Duplication is “same logical file in analysis vs user-requested copy in exports,” not double-writing by the pipeline.

---

## 4. CLASSIFICATION

Based on current BARAKUDA behavior and the target policy (EXPORT_POLICY_SPEC.md):

| Artifact type / pattern | Classification | Notes |
|-------------------------|----------------|-------|
| `run.json` | **ALWAYS SAVE CANDIDATE** | Run manifest; written by RUN; required for manifest resolution and audit. |
| `*_camera_meta.json`, `*_qc.json`, `*_ot_summary.json`, `run_manifest.json` | **ALWAYS SAVE CANDIDATE** | OTExporter / pipeline audit; written by RUN. |
| `*_postprocess.json`, `*_psd_fit.json`, `*_calibration.json`, `*_compare.json`, `*_drag.json` | **ALWAYS SAVE CANDIDATE** | Audit/calibration; written by RUN. |
| `*_results.xlsx` | **ALWAYS SAVE CANDIDATE** | Human bundle; written by RUN via `export_ot_results_xlsx`. |
| `*_trajectory.csv`, `*_tracking*.csv`, `*_psd*.csv`, `*_results.csv`, `*_derived.csv`, other analysis CSVs | **OPTIONAL EXPORT CANDIDATE** | Generated by RUN; Export tab offers them for copy to `exports/`. |
| `*_after.png`, `*_after_raw.png`, `*_preview_tracking.png`, `*_qc.png`, strategy PSD/Drag .png | **OPTIONAL EXPORT CANDIDATE** | User may export to `exports/`. |
| `item.json`, `batch.json` | **ALWAYS SAVE CANDIDATE** | Dataset/batch manifest; not offered in Export tab. |
| Future / other modules | **NEEDS DECISION** | Classify per same rules when adding. |

Export discovery (`export/discovery.py`) already filters so the Export tab sees only **optional export** artifacts (suffixes `.json` and `.xlsx` excluded from the list returned). So run_json and xlsx are not shown as export checkboxes.

---

## 5. GAPS AGAINST TARGET POLICY

Target: (1) `.json` and `.xlsx` are canonical always-saved outputs; (2) other artifacts (e.g. `.csv`, `.png`) are optional export; (3) `exports/` exists only after explicit user export.

| Gap | Status | Detail |
|-----|--------|--------|
| `.json` canonical, not in Export tab | **CONFIRMED** | Discovery filters by suffix; Export tab does not list .json as exportable. |
| `.xlsx` canonical, not in Export tab | **CONFIRMED** | Same filter; .xlsx not listed. |
| `exports/` only on explicit export | **POSSIBLE** | Panel creates `exports/` only when at least one artifact is selected (step 4). **CONFIRMED:** `batch_controller.py` still creates `item_root/exports/` proactively in dataset mode at RUN start (line 791). So empty `exports/` is still created during analysis. |
| No proactive empty `exports/` | **CONFIRMED** | Proactive creation in batch_controller (dataset mode) is the remaining mismatch. |
| Duplicate storage (analysis vs exports) | **NOT FOUND** | No automatic duplication; only user-driven copy into `exports/`. |

---

## 6. EXACT NEXT SAFE PATCH

**Goal:** Stop creating `exports/` during RUN so that `exports/` exists only when the user runs Export and at least one artifact is selected.

- **Exact file(s):** `barakuda/shell/batch_controller.py`
- **Exact behavior to change:** Remove the line that creates `exports/` in dataset mode. At ~791 the code does:
  - `(_item_root_for_run / "exports").mkdir(parents=True, exist_ok=True)`  
  Remove this line so that RUN never creates `item_root/exports/`. The Export tab (panel) already creates `exports/` only when copying at least one selected artifact.
- **Why this is the next safest step:** It is a single deletion in one place; it does not change analysis output, manifest resolution (manifest only reads `exports_dir` if the directory already exists), or Export tab logic. Existing datasets that already have `exports/` keep it; new RUNs simply no longer create an empty `exports/` folder.

---

## 7. VERIFY PLAN

After applying the next runtime patch (remove proactive `exports/` creation in batch_controller dataset mode):

1. **Branch:** Confirm work is on `integration/export-policy-simplification`.
2. **Clean dataset (no `exports/`):** Use or create an OT dataset that has no `exports/` directory.
3. **RUN only:** Run the OT pipeline (RUN) for that dataset. Confirm **no** `exports/` directory is created under the item root.
4. **Export tab:** Open the Export section, select one or more optional export artifacts, click EXPORT. Confirm `exports/` is created at that moment and only the selected files appear under it.
5. **Existing `exports/`:** Use a dataset that already has `exports/` from a previous export. Run RUN again (no Export click). Confirm `exports/` still exists and its contents are unchanged. Then run Export with a selection; confirm new files are added as before.
6. **Legacy batch mode:** If possible, run in non-dataset (legacy batch) mode and confirm no regression (legacy path does not create `item_root/exports/` at RUN start; only dataset path did).
7. **No other behavior:** Confirm artifact discovery, Export UI, and analysis outputs are unchanged.

---

*End of audit. No runtime code was modified in this step.*
