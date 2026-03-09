# Per-File Export Checkbox Branch — Final Merge Review

**Branch:** `integration/export-per-file-checkboxes`  
**Date:** 2026-03-09  
**Scope:** Final merge-review audit to prepare this branch for safe human-reviewed merge into `main`. This step does **not** merge anything and does not modify runtime code.

---

## 1. PURPOSE

This document is the final merge-review audit for the BARAKUDA per-file export checkbox branch. It summarizes the branch’s goal, commit chain, verified functional changes, remaining risks, merge readiness, and recommended merge and post-merge verification steps. **This step does NOT merge anything;** it only produces the review report so a human developer can perform the merge with full context.

---

## 2. BRANCH SUMMARY

- **Current branch name:** `integration/export-per-file-checkboxes`
- **Branch goal:** Change Export behavior from grouped logical checkboxes (e.g. one “Trajectory CSV” per type) to one checkbox per concrete exportable file, so users can select or deselect individual files. Discovery, Export UI, and export execution are aligned on per-file candidates with path-based unique ids.
- **Merge target:** The branch is intended to merge directly into `main` after human review. If your process uses an intermediate integration branch, merge this branch there first, then integrate to `main` as usual.

---

## 3. COMMIT CHAIN

Relevant commits for the per-file export checkbox feature, in order (oldest first):

| Short SHA  | Commit message | Purpose |
|------------|-----------------|---------|
| `6632a56`  | docs: define per-file export checkbox policy | Spec document (EXPORT_PER_FILE_CHECKBOX_SPEC.md): target behavior, current vs target, UI/backend rules, risks, roadmap, first runtime step. |
| `d81f591`  | fix: return per-file export candidates from ot discovery | Discovery returns one candidate per concrete file with path-based unique `id`, one `path` per candidate; canonical `.json`/`.xlsx` excluded. |
| `526fe5d`  | fix: render per-file export checkboxes in ot panel | Export UI builds one checkbox per discovered candidate, keyed by candidate `id`, label from discovery; flat list, no group-ID filtering. |
| `ac13a2d`  | docs: add per-file export verification report | Verification report (EXPORT_PER_FILE_VERIFICATION_REPORT.md): checklist, current behavior, gaps, next-step recommendation. |

---

## 4. VERIFIED FUNCTIONAL CHANGES

Concrete functional changes now present on the branch:

- **One checkbox per concrete exportable file:** The Export section shows one checkbox per discovered file; no checkbox represents multiple files.
- **Discovery returns one candidate per file:** `discover_analysis_artifacts()` enumerates all matching files per optional-export type and returns one dict per file with unique path-based `id`, `label`, and `path`.
- **Path-based unique ids:** Each candidate’s `id` is the normalized relative path; it is unique per file within a dataset and is used as the checkbox key and for export lookup.
- **Canonical `.json` / `.xlsx` excluded:** Export discovery still filters out these suffixes so they are not offered as export candidates.
- **Select All / Clear All:** Both operate on the full per-file checkbox list (all entries in `_export_artifact_checkboxes`).
- **EXPORT button state:** Enabled when there is at least one checkbox and at least one is checked; disabled otherwise.
- **Export execution copies checked per-file candidates only:** The click handler iterates checked checkboxes, resolves each by `id` from `_export_artifacts`, and copies `item_root / art["path"]` for each; unchecked candidates are not copied. Verified in code path and in verification report.
- **Flat-list rendering:** The previous DATA/REPORTS/PLOTS grouping and filtering by logical ids (`trajectory_csv`, etc.) was removed; the UI now renders a flat list of one checkbox per discovered candidate.

---

## 5. REMAINING RISKS

| Risk | Level | Notes |
|------|--------|--------|
| Label readability / long or technical filenames in UI | **LOW** | Labels are `"{prefix} — {filename}"`. Dense or similar filenames may be hard to distinguish; no reported blocker. |
| Basename collision when exporting multiple files with same name from different subdirs | **LOW** | Export uses `exports_dir / Path(art["path"]).name`; two selected files with the same basename would overwrite. Optional follow-up; not a merge blocker for per-file checkbox behavior. |
| UI refresh/rebuild behavior | **NONE** | Refresh path (manifest load → discovery → _refresh_export_artifact_checkboxes) is consistent; no known regressions. |
| Compatibility with current OT workflow | **NONE** | Discovery, UI, and export execution are aligned; no schema or pipeline change. |
| OT-only implementation vs future shared export system | **LOW** | Logic is under OT export/panel; a future shared export system would need to follow the same one-checkbox-per-file contract. |

There is no confirmed code blocker for merge. Remaining items are optional improvements or future cross-cutting concerns.

---

## 6. MERGE READINESS

**READY FOR MERGE REVIEW**

The branch delivers the intended behavior: discovery returns one candidate per file with path-based ids; the Export UI renders one checkbox per candidate and uses those ids; Select All, Clear All, and EXPORT button state work; export execution copies only the checked per-file candidates. The verification report marks all checklist items PASS and recommends no further runtime patch before merge. Remaining risks are low and do not block merge. A human reviewer should confirm the branch diff and run the post-merge verify checklist below.

---

## 7. RECOMMENDED MERGE PROCEDURE

Perform these steps as a human developer; do not auto-merge in this step.

1. **Clean working tree:**  
   `git status` — ensure no uncommitted changes (or stash them).  
   `git branch --show-current` — ensure you are on the target branch (e.g. `main`) before merging.

2. **Optional: note or tag current main:**  
   `git log -1 main --oneline` or `git tag pre-merge-export-per-file main` (optional).

3. **Merge with review:**  
   `git checkout main`  
   `git pull origin main` (or your main upstream).  
   `git merge integration/export-per-file-checkboxes --no-ff -m "Merge branch 'integration/export-per-file-checkboxes'"`  
   Resolve any conflicts if they appear; do not merge if critical conflicts remain unresolved.

4. **Post-merge verification:**  
   Run the “Post-merge verify checklist” below (e.g. start app, open OT dataset, open Export, test checkboxes and EXPORT).

5. **Do not auto-merge:**  
   This document does not perform the merge; a human must execute the merge and verification.

---

## 8. POST-MERGE VERIFY CHECKLIST

After merging `integration/export-per-file-checkboxes` into `main`, run these checks:

- [ ] **Export section shows one checkbox per concrete file:** Open an OT dataset that has multiple exportable files (e.g. several CSVs); confirm there is one checkbox per file, not one per type.
- [ ] **No checkbox represents multiple files:** No single checkbox label or id corresponds to more than one file on disk.
- [ ] **Select All:** Clicks “Select All” and confirms every visible export checkbox becomes checked.
- [ ] **Clear All:** Clicks “Clear All” and confirms every visible export checkbox becomes unchecked.
- [ ] **EXPORT button:** With no checkboxes checked, EXPORT is disabled; with at least one checked, EXPORT is enabled.
- [ ] **Checked files exported, unchecked not:** Select a subset of checkboxes, click EXPORT; confirm only the checked files appear under `item_root/exports/` and unchecked ones do not.
- [ ] **`.json` / `.xlsx` not shown as export checkboxes:** Export candidate list does not include run.json, qc.json, or results.xlsx (or other canonical JSON/XLSX).
- [ ] **No obvious regression in OT workflow:** Load dataset, run pipeline if needed, open Export, export a few files; confirm no crash or obvious break in normal OT use.

---

*End of merge review. No merge was performed; no runtime code was modified.*
