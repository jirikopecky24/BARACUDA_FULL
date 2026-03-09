# Per-File Export Integration Verification Report

**Branch:** `integration/export-per-file-checkboxes`  
**Date:** 2026-03-09  
**Scope:** Integration verification of the current per-file export branch before any further runtime changes. No runtime code was modified in this step.

---

## 1. PURPOSE

This report is an integration verification of the current per-file export checkbox branch. It confirms whether discovery, Export UI rendering, checkbox state handling, and export execution together correctly support one checkbox per concrete exportable file. The audit is performed before any further runtime changes so that the next step (if any) can be chosen with full context.

---

## 2. COMMITS REVIEWED

Relevant commits on `integration/export-per-file-checkboxes`:

| Commit     | Description |
|-----------|-------------|
| `6632a56` | docs: define per-file export checkbox policy — spec document (EXPORT_PER_FILE_CHECKBOX_SPEC.md) |
| `d81f591` | fix: return per-file export candidates from ot discovery — discovery returns one candidate per file with path-based id |
| `526fe5d` | fix: render per-file export checkboxes in ot panel — Export UI builds one checkbox per discovered candidate |

---

## 3. TARGET CHECKLIST

For each item, exactly one status is marked.

| # | Item | Status |
|---|------|--------|
| 1 | discovery returns one candidate per concrete exportable file | **PASS** |
| 2 | every candidate has unique `id`, `label`, and `path` | **PASS** |
| 3 | no candidate represents multiple files | **PASS** |
| 4 | `.json` files are excluded from export candidates | **PASS** |
| 5 | `.xlsx` files are excluded from export candidates | **PASS** |
| 6 | Export UI renders one checkbox per discovered candidate | **PASS** |
| 7 | checkbox labels correspond to concrete files | **PASS** |
| 8 | Select All works on the per-file checkbox list | **PASS** |
| 9 | Clear All works on the per-file checkbox list | **PASS** |
| 10 | EXPORT button state follows current checkbox state correctly | **PASS** |
| 11 | export execution copies only the checked per-file candidates | **PASS** |
| 12 | export execution does not copy unchecked candidates | **PASS** |
| 13 | Export section still works after refresh/rebuild | **PASS** |

---

## 4. CURRENT VERIFIED BEHAVIOR

- **What discovery returns now:** `discover_analysis_artifacts(dataset_root)` enumerates all matching files per optional-export type (trajectory, tracking, psd, plus run_json/qc_report which are then filtered out). It returns a list of dicts; each dict has `id` = normalized relative path, `label` = `"{prefix} — {filename}"`, and `path` = same relative path. One entry per file; `.json` and `.xlsx` are excluded after collection. Order is stable (type priority, then path).

- **How the UI renders:** `_refresh_export_artifact_checkboxes(artifacts)` iterates over the full `artifacts` list (no group-ID filtering). For each artifact it creates one `QCheckBox` with `art["label"]` and stores it in `_export_artifact_checkboxes[art["id"]]`. So there is exactly one checkbox per discovered candidate, in a flat list.

- **How checkbox ids map to exported files:** Each checkbox is keyed by the candidate’s `id` (the path string). `self._export_artifacts` holds the same list from discovery; the click handler builds `art_by_id = {a["id"]: a for a in self._export_artifacts}`. For each checked checkbox, `aid` is the path-based id, so `art = art_by_id.get(aid)` yields the artifact and `art["path"]` is the file to copy. One checkbox → one file.

- **Whether export execution works with the new ids:** Yes. The handler only uses `aid` to look up `art` and then `item_root / art["path"]` for the source and `exports_dir / Path(art["path"]).name` for the destination. No dependency on old logical ids.

- **Flat-list vs grouped-list tradeoff:** The previous DATA/REPORTS/PLOTS grouping was removed so that the UI could show every discovered file without being tied to logical ids. The current behavior is a flat per-file checkbox list. Reintroducing grouping (e.g. by type or folder) would be a separate, optional UI improvement and would need to group individual file checkboxes, not merge them.

---

## 5. REMAINING GAPS

| Gap | Status | Notes |
|-----|--------|--------|
| Destination basename collision when multiple selected files share the same filename (e.g. two `*_trajectory.csv` from different subdirs) | **POSSIBLE** | Export uses `dst = exports_dir / Path(art["path"]).name`; the second file would overwrite the first. Spec roadmap step 3 mentioned avoiding collisions when multiple files share the same basename. |
| Label readability / internal filename exposure | **POSSIBLE** | Labels are `"{prefix} — {filename}"`; long or technical filenames may be hard to distinguish. No user feedback in codebase. |
| Refresh/rebuild edge cases (e.g. discovery run during folder change) | **NOT VERIFIED** | Normal refresh path (manifest load → discovery → _refresh_export_artifact_checkboxes) is consistent; no automated tests or edge-case verification. |
| Export execution mismatch (wrong or missing files copied) | **NOT VERIFIED** | Code path is consistent; manual run on a real dataset was not repeated in this audit. |

---

## 6. EXACT NEXT SAFE STEP

**No runtime patch needed; branch is ready for merge review.**

The per-file checkbox goal is met: discovery returns one candidate per file, the UI shows one checkbox per candidate keyed by path-based id, and export copies only the checked files using those ids. Optional follow-ups (e.g. destination naming to avoid basename overwrite, or improved labels/grouping) can be done in later steps if desired; they are not required for the current integration verification.

---

## 7. VERIFY PLAN

Use these steps for final merge review (no further runtime work required for the per-file checkbox feature):

1. **Branch:** `git branch --show-current` → `integration/export-per-file-checkboxes`.
2. **Discovery:** From repo root run:
   ```bash
   python -c "
   from pathlib import Path
   from barakuda.devices.optical_tweezers.export.discovery import discover_analysis_artifacts
   root = Path('runs/ot/2026-03-09_185402/items/2026-02-19-Bead1um-0-um_s')
   arts = discover_analysis_artifacts(root)
   print(len(arts)); print([a['id'] for a in arts])
   "
   ```
   Expect multiple entries (e.g. 4), each with unique id and path; no `.json`/`.xlsx`.
3. **UI:** Start BARAKUDA, open the same OT dataset, open Export. Confirm one checkbox per discovered file, labels like `Trajectory CSV — …` / `PSD spectrum CSV — …`. Use Select All then Clear All; confirm EXPORT enables when at least one is checked and disables when none.
4. **Export execution:** With one or two checkboxes checked, click EXPORT. Confirm only those files appear under `item_root/exports/` and match the checked candidates.
5. **Refresh:** Change dataset or reload; confirm Export section repopulates with the new dataset’s per-file list.

---

*End of report. No runtime source files were modified.*
