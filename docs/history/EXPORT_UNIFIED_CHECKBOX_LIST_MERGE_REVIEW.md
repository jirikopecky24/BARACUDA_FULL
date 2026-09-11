# Unified Export Checkbox List Branch — Final Merge Review

**Branch:** `integration/export-unified-checkbox-list`  
**Date:** 2026-03-09  
**Scope:** Final merge-review audit to prepare this branch for safe human-reviewed merge into `main`. This step does **not** merge anything and does not modify runtime code.

---

## 1. PURPOSE

This document is the final merge-review audit for the BARAKUDA unified export checkbox list branch. It summarizes the branch goal, commit chain, verified functional changes, remaining risks, merge readiness, and recommended merge and post-merge verification steps. **This step does NOT merge anything;** it only produces the review report so a human developer can perform the merge with full context.

---

## 2. BRANCH SUMMARY

- **Current branch name:** `integration/export-unified-checkbox-list`
- **Branch goal:** Unify the OT Export section so that (1) the passive gray analysis file list is removed, and (2) every file that previously appeared in that list is shown as a selectable checkbox. One checkbox per concrete analysis file; discovery returns the full analysis file inventory; no separate read-only file list.
- **Merge target:** The branch is intended to merge directly into `main` after human review. If your process uses an intermediate integration branch, merge this branch there first, then integrate to `main` as usual.

---

## 3. COMMIT CHAIN

Relevant commits for the unified export checkbox list feature, in order (oldest first):

| Short SHA  | Commit message | Purpose |
|------------|----------------|---------|
| `914c3d9`  | docs: define unified export checkbox list policy | Spec: one unified list, remove passive gray file listing; no duplicate artifact representation. |
| `16ae4b3`  | fix: remove passive export file listing from ot panel | Stop populating _export_files_lbl from rglob; set to empty so only checkbox list remains. |
| `1f1602c`  | docs: define export policy for all visible files as checkboxes | Spec: every file from old gray list becomes a checkbox; .json/.xlsx included; full inventory as source of truth. |
| `58eaba5`  | fix: return full analysis file inventory for ot export | Discovery uses rglob on analysis roots; returns one candidate per file; includes .json, .xlsx, .csv, .png and all other files; no dirs. |
| `d3e3e41`  | docs: add unified export checkbox list verification report | Verification: checklist PASS, current behavior, gaps, next step (none); verify plan. |

---

## 4. VERIFIED FUNCTIONAL CHANGES

Concrete functional changes now present on the branch:

- **No passive gray file list:** The Export section no longer shows a read-only list of analysis files above the checkboxes. `_export_files_lbl` is set to empty; the only artifact list is the checkbox list.
- **One checkbox per concrete analysis file:** The Export UI builds one checkbox per entry returned by discovery; discovery returns one entry per file under the analysis directory(ies).
- **Discovery returns full analysis inventory:** `discover_analysis_artifacts(dataset_root)` walks `analysis/` and `module/ot/` with `rglob("*")`, keeps only files, and returns one candidate per file with `id`, `label`, and `path` (all the relative path).
- **`.json`, `.xlsx`, `.csv`, `.png`, and other real analysis files** can appear as checkbox candidates; no suffix-based exclusion.
- **Select All / Clear All** still work on the full visible checkbox list (all entries in `_export_artifact_checkboxes`).
- **EXPORT button state** still works: enabled when at least one checkbox is checked and discovery succeeded; disabled when none checked or no artifacts.
- **Export execution copies checked files only:** The click handler iterates checked checkboxes, resolves each by id from `_export_artifacts`, and copies `item_root / art["path"]` for each; unchecked files are not copied. Verified in code path and verification report.
- **Export section now reflects the same visible file inventory in one unified selectable list:** The set of files shown as checkboxes is the full analysis file tree (what the old gray list showed), in a single list with one checkbox per file.

---

## 5. REMAINING RISKS

| Risk | Level | Notes |
|------|--------|------|
| Label readability / technical path display | **LOW** | Checkbox labels are full relative paths (e.g. `module/ot/physics/..._psd_x.csv`). Dense but unambiguous; optional improvement later. |
| Basename collision risk in exports | **LOW** | Export uses `exports_dir / Path(art["path"]).name`. Two files in different subdirs with the same filename would overwrite. Optional follow-up. |
| UI refresh/rebuild behavior | **NONE** | Refresh path (load manifest → discovery → _refresh_export_artifact_checkboxes) is consistent; no known regressions. |
| Compatibility with current OT workflow | **NONE** | Discovery, UI, and export are aligned; no schema or pipeline change. |
| OT-only implementation vs future shared export system | **LOW** | Logic is under OT export/panel; a future shared export system would need the same one-checkbox-per-file and full-inventory contract. |

There is no confirmed code blocker for merge. Remaining items are optional improvements or future cross-cutting concerns.

---

## 6. MERGE READINESS

**READY FOR MERGE REVIEW**

The branch delivers the intended behavior: the passive gray file list is removed; discovery returns the full analysis file inventory; the Export section shows one checkbox per file in a single list; Select All, Clear All, and EXPORT button and copy behavior work and are aligned with the displayed list. The verification report marks all checklist items PASS and recommends no further runtime patch before merge. Remaining risks are low and do not block merge. A human reviewer should confirm the branch diff and run the post-merge verify checklist below.

---

## 7. RECOMMENDED MERGE PROCEDURE

Perform these steps as a human developer; do not auto-merge in this step.

1. **Clean working tree:**  
   `git status` — ensure no uncommitted changes (or stash them).  
   `git branch --show-current` — ensure you are on the target branch (e.g. `main`) before merging.

2. **Optional: note or tag current main:**  
   `git log -1 main --oneline` or `git tag pre-merge-unified-export main` (optional).

3. **Merge with review:**  
   `git checkout main`  
   `git pull origin main` (or your main upstream).  
   `git merge integration/export-unified-checkbox-list --no-ff -m "Merge branch 'integration/export-unified-checkbox-list'"`  
   Resolve any conflicts if they appear; do not merge if critical conflicts remain unresolved.

4. **Post-merge verification:**  
   Run the “Post-merge verify checklist” below (e.g. start app, open OT dataset, open Export, test checkboxes and EXPORT).

5. **Do not auto-merge:**  
   This document does not perform the merge; a human must execute the merge and verification.

---

## 8. POST-MERGE VERIFY CHECKLIST

After merging `integration/export-unified-checkbox-list` into `main`, run these checks:

- [ ] **Export section shows one checkbox per visible analysis file:** Open an OT dataset that has analysis outputs; confirm there is one checkbox per file under the analysis directory (e.g. many entries for .json, .xlsx, .csv, .png), not a subset.
- [ ] **No passive gray file list remains:** Confirm there is no read-only list of file paths above the checkboxes; only summary (Item, Analysis, Exports) and the checkbox list.
- [ ] **Select All:** Click “Select All” and confirm every visible export checkbox becomes checked.
- [ ] **Clear All:** Click “Clear All” and confirm every visible export checkbox becomes unchecked.
- [ ] **EXPORT button:** With no checkboxes checked, EXPORT is disabled; with at least one checked, EXPORT is enabled.
- [ ] **Checked files exported, unchecked not:** Select a subset of checkboxes, click EXPORT; confirm only the checked files appear under `item_root/exports/` and unchecked files are not copied.
- [ ] **`.json` / `.xlsx` / `.csv` / `.png` appear when present:** Confirm that analysis files of these types (when present in the analysis dir) appear as checkbox entries.
- [ ] **No obvious regression in OT workflow:** Load dataset, run pipeline if needed, open Export, export a few files; confirm no crash or obvious break in normal OT use.

---

*End of merge review. No merge was performed; no runtime code was modified.*
