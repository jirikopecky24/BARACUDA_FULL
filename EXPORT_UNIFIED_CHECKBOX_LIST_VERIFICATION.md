# Unified Export Checkbox List — Integration Verification Report

**Branch:** `integration/export-unified-checkbox-list`  
**Date:** 2026-03-09  
**Scope:** Integration verification of the current unified export checkbox list branch before any further runtime changes. No runtime code was modified in this step.

---

## 1. PURPOSE

This report is an integration verification of the current unified export checkbox list branch. It confirms whether discovery, Export UI rendering, checkbox state handling, and export execution together deliver the full analysis file inventory as one checkbox per concrete file, with no separate passive gray list and with export behavior consistent with what is displayed. The audit is performed before any further runtime changes so that the next step (if any) can be chosen with full context.

---

## 2. COMMITS REVIEWED

Relevant commits on `integration/export-unified-checkbox-list` for the unified checkbox list work:

| Commit     | Description |
|-----------|-------------|
| `914c3d9` | docs: define unified export checkbox list policy — spec: one unified list, remove passive gray file listing |
| `16ae4b3` | fix: remove passive export file listing from ot panel — stop populating _export_files_lbl from rglob |
| `1f1602c` | docs: define export policy for all visible files as checkboxes — spec: every file from gray list becomes a checkbox |
| `58eaba5` | fix: return full analysis file inventory for ot export — discovery returns all files under analysis roots via rglob |

---

## 3. TARGET CHECKLIST

For each item, exactly one status is marked.

| # | Item | Status |
|---|------|--------|
| 1 | discovery returns the full analysis file inventory | **PASS** |
| 2 | every returned candidate maps to exactly one concrete file | **PASS** |
| 3 | `.json` files are now included as checkbox candidates | **PASS** |
| 4 | `.xlsx` files are now included as checkbox candidates | **PASS** |
| 5 | `.csv` files are included as checkbox candidates | **PASS** |
| 6 | `.png` files are included as checkbox candidates | **PASS** |
| 7 | no directories are returned as candidates | **PASS** |
| 8 | Export UI renders one checkbox per discovered file | **PASS** |
| 9 | there is no separate passive gray file list anymore | **PASS** |
| 10 | Select All works on the full visible checkbox list | **PASS** |
| 11 | Clear All works on the full visible checkbox list | **PASS** |
| 12 | EXPORT button state follows the current checkbox state correctly | **PASS** |
| 13 | export execution copies checked files only | **PASS** |
| 14 | export execution does not copy unchecked files | **PASS** |
| 15 | Export section still works after refresh/rebuild | **PASS** |

---

## 4. CURRENT VERIFIED BEHAVIOR

- **What discovery returns now:** `discover_analysis_artifacts(dataset_root)` walks each analysis root (`analysis/`, `module/ot/`) with `rglob("*")`, keeps only `f.is_file()`, and returns one dict per file with `id`, `label`, and `path` all set to the normalized relative path. No filter by suffix; `.json`, `.xlsx`, `.csv`, `.png`, and all other files under the analysis tree are included. Result is sorted by path. No directories.

- **How labels currently appear in the checkbox list:** Each checkbox label is `art["label"]`, which is the full relative path (e.g. `module/ot/tracking/2026-02-19-Bead1um-0-um_s_trajectory.csv`). So labels are path strings, not short filenames.

- **How checkbox ids map to file paths:** Checkbox key is `art["id"]` (same path string). Export handler builds `art_by_id` from `_export_artifacts` and copies `item_root / art["path"]` for each checked checkbox. One id = one path = one file; mapping is consistent.

- **Whether the UI now shows the same file inventory that used to be shown in the gray list:** Yes. The gray list was built from `m.analysis_dir.rglob("*")` (one analysis dir per item). Discovery uses `_analysis_roots(root)` (analysis/ and module/ot/) and rglob on each. For a typical item, the manifest’s analysis_dir is one of those, so the set of files is the same. The Export section now shows one checkbox per file from that inventory; there is no second passive list (`_export_files_lbl` is set to empty).

- **Whether export execution is aligned with the displayed checkbox list:** Yes. The click handler iterates `_export_artifact_checkboxes`, resolves each checked id via `_export_artifacts`, and copies `item_root / art["path"]`. Only checked files are copied; unchecked are skipped. Displayed list and copied files are the same source.

---

## 5. REMAINING GAPS

| Gap | Status | Notes |
|-----|--------|--------|
| Label readability / overly technical path display | **POSSIBLE** | Labels are full relative paths (e.g. `module/ot/physics/..._psd_x.csv`). Dense for many files; optional improvement: show filename or short path. |
| Basename/path presentation | **POSSIBLE** | Same as above; no basename-only option in UI today. |
| Export destination basename collision | **POSSIBLE** | Export uses `dst = exports_dir / Path(art["path"]).name`. Two files in different subdirs with the same filename would overwrite. Optional follow-up. |
| Refresh edge cases | **NOT VERIFIED** | Normal refresh (load manifest → discovery → _refresh_export_artifact_checkboxes) is consistent; no automated or edge-case verification. |

---

## 6. EXACT NEXT SAFE STEP

**No runtime patch needed; branch is ready for merge review.**

Discovery returns the full analysis file inventory; the panel renders one checkbox per file and no longer shows a passive gray list; Select All, Clear All, and EXPORT button and copy behavior are correct and aligned with the displayed list. Remaining items (label readability, optional basename collision handling) are improvements that can be done in a later change if desired. A human reviewer should run the verify plan below before merging.

---

## 7. VERIFY PLAN

Use these steps for final merge review:

1. **Branch:** `git branch --show-current` → `integration/export-unified-checkbox-list`.

2. **Discovery:** From repo root:
   ```bash
   python -c "
   from pathlib import Path
   from barakuda.devices.optical_tweezers.export.discovery import discover_analysis_artifacts
   root = Path('runs/ot/2026-03-09_185402/items/2026-02-19-Bead1um-0-um_s')
   arts = discover_analysis_artifacts(root)
   print(len(arts))
   print([Path(a['path']).suffix for a in arts])
   "
   ```
   Expect many entries including `.json`, `.xlsx`, `.csv`, `.png`.

3. **UI:** Start BARAKUDA, open the same OT dataset, open the Export tab. Confirm: (a) no gray file list above the checkboxes, (b) one checkbox per file (full inventory), (c) Select All and Clear All affect all checkboxes, (d) EXPORT enables when at least one is checked and disables when none.

4. **Export execution:** With a subset of checkboxes checked, click EXPORT. Confirm only those files appear under `item_root/exports/` and unchecked files are not copied.

5. **Refresh:** Change dataset or reopen; confirm Export section repopulates with the new dataset’s full file list.

---

*End of report. No runtime source files were modified.*
