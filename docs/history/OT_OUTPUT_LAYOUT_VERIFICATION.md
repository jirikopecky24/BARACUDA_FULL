# OT Output Layout Verification

## 1. PURPOSE

This document is an integration verification of the current OT (optical tweezers) output layout after the recent cleanup patches on branch `integration/ot-output-layout-simplification`. It records what a **fresh** OT run writes today, which legacy/root-level outputs (if any) remain in the OT analysis root, and the status of each cleanup target. It does not modify any runtime code.

---

## 2. COMMITS REVIEWED

Relevant commits on this branch (most recent first):

| Commit     | Description |
|-----------|-------------|
| `22de3ca` | fix: write new ot qc image under structured qc directory |
| `5f107f4` | fix: write new ot result summaries under structured summary directory |
| `5d242b8` | fix: write dataset-mode ot pipeline artifacts under pipeline directory |
| `2e65ea4` | fix: write new ot pipeline artifacts under pipeline directory |
| `ac90bae` | fix: support pipeline and ot_v2_shadow in ot manifest |
| `c3db219` | fix: resolve preview report from preview directory |
| `af6d7fa` | docs: audit ot_v2_shadow overlap and legacy ot outputs |
| `44e1b6b` | docs: audit ot output layout and preview storage |

Key runtime/audit changes:

- **Preview report manifest resolution** (`c3db219`): manifest resolves `preview_report.json` from `preview/preview_report.json`.
- **Pipeline + ot_v2_shadow manifest compatibility** (`ac90bae`): manifest resolution supports both `module/ot/pipeline/` and `module/ot/ot_v2_shadow/` for qc/trajectory and related paths.
- **Non-dataset pipeline write switch** (`2e65ea4`): new OT pipeline artifacts for non-dataset runs write to `run_dir/pipeline/` instead of `run_dir/ot_v2_shadow/`.
- **Dataset-mode pipeline write switch** (`5d242b8`): dataset-mode runs also write pipeline artifacts to `run_dir/pipeline/` (unified with non-dataset).
- **Summary results write move** (`5f107f4`): new `*_results.csv` and `*_results.xlsx` write to `run_dir/summary/` instead of analysis root.
- **QC image write move** (`22de3ca`): new `*_qc.png` writes to `run_dir/qc/` instead of analysis root.

---

## 3. FRESH-RUN OUTPUT SNAPSHOT

After a **fresh** OT run (dataset or non-dataset), the OT analysis directory layout is as follows.

**Analysis root** (`run_dir`):

- **Dataset mode:** `item_root/analysis/`
- **Non-dataset mode:** `item_root/module/ot/`

**Root-level file (only one):**

- `run.json` — run metadata and config (canonical; remains in root by design).

**Structured subdirectories:**

| Path (under run_dir) | Contents |
|----------------------|----------|
| `preview/` | `preview_report.json` (copy from gate), `{stem}_preview_tracking.png` |
| `pipeline/` | OT pipeline outputs: `*_camera_meta.json`, `*_qc.json`, `*_trajectory.csv`, `*_derived.csv`, `results.csv`, `*_ot_summary.json`, `run_manifest.json`, strategy artifacts (e.g. PSD/drag plots) |
| `tracking/` | `{stem}_trajectory.csv`, `{stem}_after.png`, `{stem}_after_raw.png` |
| `audit/` | `{stem}_postprocess.json`, `{stem}_psd_fit.json`, `{stem}_calibration.json` (latter two moved from tracking after postprocess) |
| `physics/` | `{stem}_msd.csv`, `{stem}_psd_x.csv`, `{stem}_psd_y.csv`, `{stem}_calibration.csv`, `{stem}_hist_*.csv`, `{stem}_derived.csv`; plus pairing artifacts when applicable: `{stem}_compare.csv`, `{stem}_compare.json`, `{stem}_drag.json` |
| `summary/` | `{stem}_results.csv`, `{stem}_results.xlsx` |
| `qc/` | `{stem}_qc.png` (moved from tracking after postprocess) |

**Absent for a fresh run:**

- `ot_v2_shadow/` — **not created**. New runs write only to `pipeline/`.

---

## 4. TARGET CHECKLIST

| Item | Status |
|------|--------|
| preview report is resolvable from preview/preview_report.json | **PASS** |
| new pipeline artifacts are written under pipeline/ | **PASS** |
| new runs do not create fresh ot_v2_shadow/ | **PASS** |
| new result summaries are written under summary/ | **PASS** |
| new QC image is written under qc/ | **PASS** |
| old datasets with ot_v2_shadow still load | **NOT VERIFIED** (manual test with legacy dataset required) |
| no passive export-only clutter remains from recent result/qc writes | **PASS** |
| remaining root-level files are limited and identifiable | **PASS** |
| fresh run still loads correctly through OT manifest resolution | **NOT VERIFIED** (manual test after fresh run required) |

---

## 5. REMAINING ROOT-LEVEL LEGACY OUTPUTS

After a **fresh** OT run, the only file remaining directly in the OT analysis root is:

| File       | Classification |
|------------|----------------|
| `run.json` | **ACCEPTABLE CANONICAL ROOT FILE** — run identity and config; kept in root by current design. |

No other root-level files are written by the current OT run path. Legacy datasets may still contain root-level `*_results.csv`, `*_results.xlsx`, or `*_qc.png`; those remain readable via manifest/fallbacks and are not modified by this verification.

---

## 6. REMAINING GAPS

| Gap | Status |
|-----|--------|
| Manifest does not explicitly point at `qc/` for QC image path (manifest’s `qc_json_path` is for `*_qc.json`, which lives in `pipeline/`; `*_qc.png` is display-only) | **POSSIBLE** — only relevant if UI or export discovery needs to resolve the QC PNG from manifest. |
| Root-level `run.json` placement (canonical; no change requested in this cleanup) | **CONFIRMED** — intentional. |
| Old-dataset migration not yet addressed (legacy root-level result/qc files left on disk) | **CONFIRMED** — by design; no migration in this step. |
| Manual verification of “old dataset with ot_v2_shadow still loads” and “fresh run loads via manifest” not yet run | **NOT VERIFIED** — requires manual run. |

---

## 7. EXACT NEXT SAFE STEP

**No runtime patch needed; branch is ready for merge review.**

Current behavior matches the stated cleanup goals:

- New pipeline outputs → `pipeline/`
- New result summaries → `summary/`
- New QC image → `qc/`
- Only `run.json` remains in the analysis root for new runs
- No new `ot_v2_shadow/` directory is created

Optional follow-ups (out of scope for this verification):

- If product requires it: add manifest/export support for resolving the QC image under `qc/` (e.g. for “open QC image” or export discovery).
- Manual regression: run one fresh OT analysis and one load of an old dataset with `ot_v2_shadow/` and confirm manifest resolution and UI behavior.

---

## 8. VERIFY PLAN

**For final merge review (no further runtime patch in this step):**

1. Checkout branch `integration/ot-output-layout-simplification`.
2. Run a **fresh** OT analysis (dataset mode) on a real dataset:
   - Confirm `run_dir/summary/` contains `*_results.csv` and `*_results.xlsx`.
   - Confirm `run_dir/qc/` contains `*_qc.png`.
   - Confirm `run_dir/pipeline/` contains pipeline artifacts (e.g. `*_qc.json`, `*_trajectory.csv`, `*_ot_summary.json`).
   - Confirm **no** `ot_v2_shadow/` under the run directory.
   - Confirm analysis root contains only `run.json` (no `*_results.*`, no `*_qc.png`).
3. Open the same dataset in the app and confirm it still loads (OT manifest resolution, export, preview).
4. If available, open an **older** dataset that still has `module/ot/ot_v2_shadow/` (or root-level result/qc files) and confirm it still loads and behaves correctly.
5. Confirm no runtime source files were modified in the commit that added this verification document.

**If a future patch adds manifest/export support for `qc/`:**

- Add resolution for QC image under `analysis_dir/qc/` (or equivalent) in manifest and/or export discovery; then re-run the same verification steps and update this doc if layout or checklist changes.
