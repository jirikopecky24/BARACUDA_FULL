# OT Output Layout Audit

## 1. PURPOSE

This audit documents how Optical Tweezers (OT) outputs are currently written to disk so that a later simplification of the OT output layout can be done safely. The goal is to prepare changes that do not break the deterministic workflow: same inputs and config must continue to produce the same outputs and pipeline behavior. No runtime code is modified in this step; this document is diagnostic only.

---

## 2. CURRENT OT OUTPUT ROOTS

Output roots depend on run mode:

| Mode | Output root | Code path |
|------|-------------|-----------|
| **Dataset mode** (item selected via item.json) | `item_root/analysis/` | `batch_controller.py`: `run_dir = _item_root_for_run / "analysis"` (line ~787). Subdirs created: `audit`, `tracking`, `physics`. |
| **Legacy batch mode** (OT batch, no dataset) | `item_root/module/ot/` | `batch_controller.py`: `run_dir = _item_root_for_run / "module" / "ot"` (line ~812). Item root is under `runs_folder/ot/<batch_id>/<item_id>/`. |
| **Ad-hoc run** (single file, no experiment) | `runs_folder/<run_id>/` | `RunManager.create_run()`: `run_dir = self.runs_folder / run_id` (e.g. `runs/20260309-120000-video_stem/`). |

Additional roots:

- **Preview Gate** (pre-run quality check): `runs_folder/PREVIEW-<timestamp>/` — single directory per gate run; not per-item. (`batch_controller.py` line ~236.)
- **OT pipeline shadow** (non-dataset only): `run_dir/ot_v2_shadow/` when `_dataset_item_root is None`. Used as `OTExporter` output_dir. (`batch_controller.py` lines ~864–869.)
- **Manifest resolution**: `manifest.py` resolves analysis dir as (in order) `analysis.dir` field, `item_root/analysis/`, `item_root/module/ot/`, or absolute `run_dir` from manifest.

---

## 3. PREVIEW STORAGE

### 3.1 Where preview metadata is written

- **Path**: `runs_folder/PREVIEW-<timestamp>/preview_report.json`
- **Code**: `batch_controller.py` line ~520: `(self._preview_dir / "preview_report.json").write_text(...)`
- **Content**: JSON with `results` (per-file pass/fail, details), `config` (gate params, preview_roi_rect, preview_frame_index), `ok_all`.

### 3.2 Where preview image outputs are written

- **Path**: Per-run directory, not under PREVIEW. For each run, the first-frame overlay is written to **run_dir** as `{stem}_preview_tracking.png`, then (when “Organize Outputs” runs) moved to **run_dir/tracking/**.
- **Code**: `batch_controller.py`: `save_overlay_png(..., name=f"{stem}_preview_tracking.png")` (line ~1007); later `_move_to(run_dir / f"{stem}_preview_tracking.png", dir_tracking)` (line ~1316).

### 3.3 Split preview storage

Yes. Preview artifacts are split:

1. **Preview Gate report** (metadata only): `runs_folder/PREVIEW-<timestamp>/preview_report.json` — transient; not under any item or run dir.
2. **Preview overlay image**: written under the **run** output root (`run_dir`), then moved to `run_dir/tracking/`. So it lives under `item_root/analysis/tracking/` (dataset) or `item_root/module/ot/tracking/` (legacy) or `runs_folder/<run_id>/tracking/` (ad-hoc).

The manifest looks for `preview_report.json` only under the analysis dir (`manifest.py` line ~111: `_first_existing(ad, ["preview_report.json"])`). So for dataset items, the report is not under the item; it is under `runs/PREVIEW-*`, and thus not discoverable via `analysis_dir`.

### 3.4 Relevant code paths

- `batch_controller.run_preview_gate`: sets `_preview_dir = runs_folder / f"PREVIEW-{ts}"`, writes `preview_report.json` there.
- `batch_controller` run loop: `save_overlay_png(..., name=f"{stem}_preview_tracking.png")` into `run_dir`; later move to `run_dir/tracking/`.
- `manifest.load_item_manifest`: `m.preview_report_path = _first_existing(ad, ["preview_report.json"])` — only finds it if it were under analysis dir (currently it is not).

---

## 4. LEGACY ROOT-LEVEL OUTPUTS

When the run directory is `module/ot/` (legacy batch mode) or after “Organize Outputs” in any mode, the following are written or remain at **run_dir root** (i.e. directly in `module/ot/` or `analysis/`):

| File(s) | Written by | Classification |
|---------|------------|----------------|
| `run.json` | `batch_controller` (STEP A + run_id/config) | Structured (run metadata). |
| `{stem}_trajectory.csv` | `batch_controller` (then moved to `tracking/`) | Structured. |
| `{stem}_postprocess.json` | `batch_controller` (then moved to `audit/`) | Structured. |
| `{stem}_psd_fit.json` | `postprocess_ot` (then moved to `audit/`) | Structured. |
| `{stem}_calibration.json` | `postprocess_ot` (then moved to `audit/`) | Structured. |
| `{stem}_preview_tracking.png` | `batch_controller` (then moved to `tracking/`) | Structured. |
| `{stem}_after.png`, `{stem}_after_raw.png` | `batch_controller` (then moved to `tracking/`) | Structured. |
| `{stem}_msd.csv`, `{stem}_psd_*.csv`, `{stem}_calibration.csv`, `{stem}_hist_*.csv`, `{stem}_derived.csv` | `postprocess_ot` (then moved to `physics/`) | Structured. |
| `{stem}_compare.csv`, `{stem}_drag.json` | `batch_controller` (then moved to `physics/`) | Structured. |
| **Remain in root after organize** | | |
| `run.json` | (unchanged) | Canonical run metadata. |
| `{stem}_results.csv` | `batch_controller` (single-file bundle) | Legacy export-style bundle. |
| `{stem}_results.xlsx` | `export_ot_results_xlsx` | Legacy export-style (human bundle). |
| `{stem}_qc.png` | `postprocess_ot` (QC plot) | Structured QC artifact; left in root by design (comment line ~1334). |

So the root-level legacy export-style outputs that stay in the run root are: `*_results.csv`, `*_results.xlsx`, and `*_qc.png`. The rest are moved into `audit/`, `tracking/`, or `physics/`.

---

## 5. DUPLICATES / PARALLEL TRUTH

### 5.1 `tracking` vs root vs `ot_v2_shadow`

- **Trajectory**: Written once as `run_dir/{stem}_trajectory.csv`, then moved to `run_dir/tracking/`. So there is a single trajectory file per run (no duplicate).
- **In non-dataset mode**, `OTExporter` (OTPipeline) also writes a trajectory to **ot_v2_shadow**: `ot_v2_shadow/{stem}_trajectory.csv` (different schema: t_s, x_px, y_px, confidence, x_um, y_um, x_corr_px, y_corr_px, lost, lost_reason). So for the same run we have:
  - **Batch path**: `run_dir/tracking/{stem}_trajectory.csv` (batch_controller + postprocess_ot format).
  - **Shadow path**: `run_dir/ot_v2_shadow/{stem}_trajectory.csv` (OT pipeline format).
  Same logical result (positions), two formats and two locations.

### 5.2 `physics` vs root vs `ot_v2_shadow`

- MSD, PSD, calibration, derived, etc. are written by `postprocess_ot` to `run_dir`, then moved to `run_dir/physics/`. No second copy in root after organize.
- **ot_v2_shadow** contains: `*_derived.csv`, `results.csv` (canonical), strategy plots, and (via `ot_summary.json`) references to the same logical results. So derived/physics-style results exist in both `physics/` (batch) and `ot_v2_shadow/` (pipeline).

### 5.3 `audit` vs root vs `ot_v2_shadow`

- Postprocess and calibration JSONs are written to root, then moved to `run_dir/audit/`. Single copy after organize.
- **ot_v2_shadow** has: `*_camera_meta.json`, `*_qc.json`, `*_ot_summary.json`, `run_manifest.json`. So audit-style metadata exists in both `audit/` (batch: postprocess, psd_fit, calibration) and `ot_v2_shadow/` (pipeline: camera_meta, qc, ot_summary, run_manifest).

### 5.4 Summary of parallel truth

| Logical artifact | Batch location (after organize) | ot_v2_shadow (non-dataset only) |
|------------------|---------------------------------|----------------------------------|
| Trajectory | `tracking/{stem}_trajectory.csv` | `{stem}_trajectory.csv` (different columns) |
| QC | root `{stem}_qc.png`; postprocess in audit | `{stem}_qc.json` |
| Calibration / fit | `audit/{stem}_postprocess.json`, `_psd_fit.json`, `_calibration.json` | `*_ot_summary.json`, strategy results in summary |
| Derived physics | `physics/{stem}_derived.csv`, etc. | `{stem}_derived.csv`, `results.csv` |
| Run index | `run.json` (root) | `run_manifest.json` |

The same run therefore has two parallel representations in non-dataset mode: batch_controller + postprocess_ot (root + audit/tracking/physics) and OTPipeline + OTExporter (ot_v2_shadow).

---

## 6. EMPTY PLACEHOLDER DIRECTORIES

### 6.1 Under item root (legacy batch mode only)

When `run_dir = _item_root_for_run / "module" / "ot"`, the code creates subdirs under **item root** (not under `module/ot`):

- `item_root/raw/` — used; video (and optional meta) is copied here (batch_controller step E).
- `item_root/results/` — created, **never populated** by current code. Placeholder.
- `item_root/qc/` — created, **never populated**. Placeholder.
- `item_root/artifacts/` — created, **never populated**. Placeholder.

Code: `batch_controller.py` lines ~814–815: `for _sd in ("raw", "results", "qc", "artifacts"): (_item_root_for_run / _sd).mkdir(parents=True, exist_ok=True)`.

### 6.2 Under run_dir (dataset and legacy)

- `run_dir/audit/`, `run_dir/tracking/`, `run_dir/physics/` — created and then populated by moves; not empty after a full run.
- Dataset mode: only `audit`, `tracking`, `physics` are created under `analysis/` (line ~789). No `raw`, `results`, `qc`, `artifacts` at item root in dataset mode.

---

## 7. CLASSIFICATION

| Artifact / location | Classification | Notes |
|---------------------|----------------|--------|
| `run_dir/run.json` | **CANONICAL CANDIDATE** | Single source of run identity and config. |
| `run_dir/tracking/{stem}_trajectory.csv` | **CANONICAL CANDIDATE** | Primary trajectory after organize. |
| `run_dir/audit/` (postprocess, psd_fit, calibration JSONs) | **CANONICAL CANDIDATE** | Structured audit trail. |
| `run_dir/physics/` (MSD, PSD, calibration CSV, derived, etc.) | **CANONICAL CANDIDATE** | Primary physics outputs. |
| `run_dir/{stem}_qc.png` | **CANONICAL CANDIDATE** | Single QC plot; currently left in root by design. |
| `run_dir/{stem}_results.csv`, `run_dir/{stem}_results.xlsx` | **LEGACY CANDIDATE** | Export-style bundles; could be moved or phased out. |
| `runs_folder/PREVIEW-{ts}/preview_report.json` | **LEGACY CANDIDATE** | Preview metadata not under item; split from item. |
| `run_dir/ot_v2_shadow/` (entire tree) | **DUPLICATE / TRANSITIONAL** | Parallel pipeline output; overlaps with audit/tracking/physics and root. |
| `item_root/results/`, `item_root/qc/`, `item_root/artifacts/` | **NEEDS DECISION** | Empty placeholders; either remove creation or start using. |
| `run_dir/{stem}_preview_tracking.png` → `tracking/` | **CANONICAL CANDIDATE** | Preview image per run; already under tracking. |
| Manifest `preview_report_path` | **NEEDS DECISION** | Currently looks under analysis dir; report is under PREVIEW-* so not found. |

---

## 8. EXACT NEXT SAFE PATCH

**Goal**: One smallest safe runtime change after this audit.

- **Suggested step**: Stop creating the unused placeholder directories under item root in legacy batch mode, so that `results/`, `qc/`, and `artifacts/` are no longer created. Keep creating `raw/` (still used for video copy).
- **Exact file(s)**: `barakuda/shell/batch_controller.py`
- **Exact behavior**: In the block where `run_dir = _item_root_for_run / "module" / "ot"` (around lines 812–816), change the loop that creates subdirs from `("raw", "results", "qc", "artifacts")` to `("raw",)` only. So: create only `item_root/raw/`; do not create `item_root/results/`, `item_root/qc/`, `item_root/artifacts/`.
- **Why smallest safe step**: (1) No reader code in the codebase currently reads from `item_root/results/`, `qc/`, or `artifacts/`. (2) Deterministic behavior is unchanged: same inputs still produce the same files under `run_dir` and `run_dir/audit`, `run_dir/tracking`, `run_dir/physics`. (3) Reduces clutter and makes it clear that the canonical outputs live under `module/ot/` (and its subdirs), not in those item-level folders.

---

## 9. VERIFY PLAN

Use these steps to verify the next runtime patch (stop creating `results/`, `qc/`, `artifacts/` under item root):

1. **Branch**: Checkout `integration/ot-output-layout-simplification` and apply the patch.
2. **Clean run**: Remove or rename an existing OT batch item dir (e.g. under `runs/ot/<batch_id>/`) so the next run creates a new item.
3. **Run OT batch**: Run the OT pipeline on one or more files in non-dataset (legacy batch) mode so that a new item dir is created under `runs/ot/<batch_id>/<item_id>/`.
4. **Check item root**: Under `runs/ot/<batch_id>/<item_id>/` confirm:
   - `raw/` exists (and contains the copied video if applicable).
   - `results/`, `qc/`, and `artifacts/` do **not** exist.
5. **Check run_dir**: Under `runs/ot/<batch_id>/<item_id>/module/ot/` confirm:
   - `run.json`, `*_results.csv`, `*_results.xlsx`, `*_qc.png` exist at root;
   - `audit/`, `tracking/`, `physics/` exist and contain the expected moved files.
6. **Determinism**: Run the same batch again (same input list and config) and confirm the same set of files and directory layout (no new placeholder dirs, same outputs under `module/ot/`).
