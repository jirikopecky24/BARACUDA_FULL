# OT Output Layout Merge Review

## 1. PURPOSE

This document performs the final merge-review audit for the `integration/ot-output-layout-simplification` branch. The goal is to prepare this branch for safe human-reviewed merge into `main`, without changing runtime code and without performing a merge. It summarizes functional changes, remaining risks, merge readiness, and recommended procedure.

---

## 2. BRANCH SUMMARY

**Branch**: `integration/ot-output-layout-simplification`

**Scope**: OT (Optical Tweezers) output layout simplification. The branch reduces clutter and clarifies where OT outputs are written:

- **Empty placeholders**: Stops creating unused `results/`, `qc/`, and `artifacts/` subdirectories under item root in legacy batch mode. Only `raw/` is created.
- **Preview unification**: Writes preview metadata (`preview_report.json`) and preview overlay image (`{stem}_preview_tracking.png`) into a single dedicated `run_dir/preview/` directory instead of splitting across `runs_folder/PREVIEW-{ts}/` and `run_dir/tracking/`.
- **Root-level cleanup**: Writes newly generated outputs directly into structured subdirectories (`audit/`, `tracking/`, `physics/`) instead of writing to run root and then moving. Reduces stray root-level files in `module/ot` and `analysis`.

**Note**: The branch may contain other commits (export, experiment registry, etc.) from earlier integration work. This review focuses on the OT output layout simplification commits (93f152c through 6d35ca7).

---

## 3. COMMIT CHAIN

OT output layout simplification commits (newest first):

| Commit | Message |
|--------|---------|
| `6d35ca7` | docs: audit ot_v2_shadow overlap and migration path |
| `b5d89e7` | fix: stop writing new legacy root-level ot outputs |
| `562233b` | fix: unify ot preview outputs under one preview directory |
| `3963db2` | fix: stop precreating empty ot placeholder directories |
| `93f152c` | docs: audit ot output layout and preview storage |

**Runtime changes**: 3 commits modify `barakuda/shell/batch_controller.py`.  
**Docs only**: 2 commits add audit reports (`OT_OUTPUT_LAYOUT_AUDIT.md`, `OT_V2_SHADOW_AUDIT.md`).

---

## 4. VERIFIED FUNCTIONAL CHANGES

| Change | File(s) | Behavior |
|--------|---------|----------|
| **Stop empty placeholders** | `batch_controller.py` | In legacy batch mode, creates only `item_root/raw/` instead of `raw`, `results`, `qc`, `artifacts`. |
| **Unify preview storage** | `batch_controller.py` | Creates `run_dir/preview/`; writes preview overlay to `run_dir/preview/`; copies `preview_report.json` from gate run into `run_dir/preview/` when processing each run. Preview image no longer moved to `tracking/`. |
| **Direct structured writes** | `batch_controller.py` | Creates `audit/`, `tracking/`, `physics/` at run start; writes trajectory to `tracking/`, postprocess to `audit/`, after overlays to `tracking/`, compare/drag to `physics/`. Postprocess_ot outputs go to `tracking/` (traj parent) then are moved to `audit/` and `physics/` in organize block. QC plot moved from `tracking/` to root. |

**Deterministic behavior**: Same inputs and config produce the same outputs; only file locations changed. No change to file contents or naming conventions beyond paths.

---

## 5. REMAINING RISKS

1. **ot_v2_shadow still present**: In non-dataset mode, OTPipeline still writes into `run_dir/ot_v2_shadow/`. This duplicates trajectory, derived, QC, and audit-style outputs. The audit (OT_V2_SHADOW_AUDIT.md) recommends a future step (rename to `pipeline/` or consolidate). No change in this branch.
2. **Preview report discovery**: `manifest.py` looks for `preview_report.json` under `analysis_dir`; it can now be found at `analysis/preview/preview_report.json` or `module/ot/preview/preview_report.json` when copied. Manifest uses `_first_existing(ad, ["preview_report.json"])` — it does not search `preview/` subdir. May need follow-up to add `preview/preview_report.json` to manifest resolution.
3. **Existing datasets**: Old datasets created before this branch will have the previous layout (preview in tracking/, root-level stray files, etc.). No migration is performed. New runs get the new layout.
4. **Consumer scripts**: Any external scripts that hardcode paths (e.g. `module/ot/{stem}_trajectory.csv` at root) would break. The canonical path is now `module/ot/tracking/{stem}_trajectory.csv`.

---

## 6. MERGE READINESS

**READY FOR MERGE REVIEW**

The branch is ready for human review and merge decision. The OT output layout changes are:

- **Self-contained**: Only `batch_controller.py` modified for runtime; no changes to manifest, discovery, or other modules.
- **Backward-compatible**: No schema changes; no migration required. Old datasets remain readable; new runs use the new layout.
- **Documented**: Audit reports describe current state, overlaps, and next steps (e.g. ot_v2_shadow).
- **Incremental**: Each commit is focused; no broad refactor.

**Recommended human checks before merge**:

- Run OT analysis on a dataset and confirm expected outputs.
- Run OT batch in legacy mode and confirm no empty `results/`, `qc/`, `artifacts/` under item root.
- Confirm preview metadata and image appear under `run_dir/preview/`.
- Confirm no stray root-level trajectory/postprocess/msd/psd/calibration files in new runs.

---

## 7. RECOMMENDED MERGE PROCEDURE

1. **Pre-merge**:
   - Ensure CI/tests pass (if any).
   - Perform manual verification per Section 8.
   - Resolve any conflicts with `main` if present.

2. **Merge**:
   - Merge `integration/ot-output-layout-simplification` into `main` via PR or direct merge.
   - Use a merge commit (no squash) if preserving the audit trail is desired; otherwise squash as per project policy.

3. **Post-merge**:
   - Run post-merge verification (Section 8).
   - Tag release if applicable.
   - Update any internal docs that reference OT output paths.

---

## 8. POST-MERGE VERIFY CHECKLIST

- [ ] Branch merged into `main` successfully.
- [ ] Run OT analysis on a **dataset** item; confirm:
  - [ ] `item_root/analysis/audit/`, `tracking/`, `physics/`, `preview/` exist.
  - [ ] `audit/` has postprocess, psd_fit, calibration JSONs.
  - [ ] `tracking/` has trajectory, after.png, after_raw.png.
  - [ ] `physics/` has msd, psd, calibration csv, hist, derived; compare/drag if applicable.
  - [ ] `preview/` has preview_report.json (if gate was run) and preview_tracking.png.
  - [ ] Root has only run.json, *_results.csv, *_results.xlsx, *_qc.png.
- [ ] Run OT batch in **legacy** mode; confirm:
  - [ ] `item_root/raw/` exists; `results/`, `qc/`, `artifacts/` do not.
  - [ ] `module/ot/` has same structure as above.
- [ ] Preview Gate: run gate then full analysis; confirm preview_report.json and preview_tracking.png under `run_dir/preview/`.
- [ ] No regression: same inputs produce same analysis results (only paths changed).
