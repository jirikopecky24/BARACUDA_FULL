# Export All Visible Files as Checkboxes — Specification

**Branch:** `integration/export-unified-checkbox-list`  
**Scope:** Define the policy change so that every file previously shown in the old gray analysis-file list becomes a selectable checkbox entry in the unified Export list. No runtime code changes in this step.

---

## 1. PURPOSE

- **New target:** Every file that previously appeared in the old gray file list must now appear as a selectable checkbox entry. The gray list showed a full recursive inventory of files under the analysis directory; that same inventory must become the checkbox list so users can select any of those files for export.
- **Passive file display is no longer acceptable.** There must be no read-only list of files. Every displayed file must have a checkbox and be selectable. What is shown must match what can be exported; one list, one checkbox per file.

---

## 2. CURRENT BEHAVIOR

- **Where the old gray file list came from:** The gray list was built in `_refresh_export_status()` (OT panel) and populated `_export_files_lbl`. Its data source was the manifest’s `m.analysis_dir` (resolved from `item.json` — e.g. `analysis/`, `module/ot/`, or `run_dir`). The list was built with `m.analysis_dir.rglob("*")`: every file under that directory, recursively. Each file was one line, indented, showing the path relative to item root. The gray list was removed in a prior step; it no longer displays, but its former source (rglob on analysis_dir) defines what “full visible inventory” means.
- **Where the current checkbox list comes from:** The checkbox list is built in `_refresh_export_artifact_checkboxes(artifacts)` (same panel). Its data source is `discover_analysis_artifacts(m.item_root)` in `barakuda/devices/optical_tweezers/export/discovery.py`. Discovery walks `analysis/` and `module/ot/` and returns only files matching specific patterns (trajectory, tracking, PSD CSVs, run.json, qc.json). It then **filters out** all `.json` and `.xlsx` files. So the checkbox list contains only a subset of CSVs (and no other types).
- **Which classes of files were in the gray list but are missing from checkbox discovery:**  
  - **`.json`:** All JSON files (run.json, qc.json, camera_meta.json, postprocess, psd_fit, calibration, ot_summary, run_manifest, etc.) — **excluded by discovery** (canonical filter).  
  - **`.xlsx`:** All XLSX files (e.g. results.xlsx) — **excluded by discovery** (canonical filter).  
  - **`.png`:** All PNG files (welch_psd_*.png, hist_*.png, qc.png, after.png, after_raw.png, preview_tracking.png, etc.) — **not in discovery at all** (no PNG patterns).  
  - **`.csv`:** Many CSVs (derived.csv, results.csv, calibration.csv, hist_*.csv, msd.csv, compare.csv, etc.) — **not in discovery** (discovery only has trajectory, tracking, psd patterns).  
  So the gray list included `.json`, `.xlsx`, `.csv`, `.png`, and other types; the checkbox list currently includes only a narrow subset of `.csv` files.
- **Current inclusion/exclusion by file type:**  
  - **`.json`:** Excluded from checkboxes (canonical filter).  
  - **`.xlsx`:** Excluded from checkboxes (canonical filter).  
  - **`.csv`:** Partially included (only trajectory, tracking, PSD patterns); many CSVs excluded.  
  - **`.png`:** Excluded (no discovery patterns).  
  - **Other:** Excluded (no discovery patterns).

---

## 3. TARGET BEHAVIOR

- **Every file that belongs to the intended visible Export inventory must have its own checkbox.** The intended inventory is the full analysis file tree (what the old gray list showed): every file under the manifest’s analysis_dir (or equivalent roots), recursively.
- **One checkbox = one concrete file.** No checkbox represents multiple files. No passive list.
- **No passive gray artifact/file list separate from the checkbox list.** The only list is the checkbox list.
- **Only existing files may appear.** The inventory must be built from actual files on disk (e.g. rglob or equivalent); no phantom paths.
- **`.json` and `.xlsx` under the new requirement:** The old gray list **included** `.json` and `.xlsx`. The new requirement is that “everything that used to appear in the gray list should appear as checkbox entries.” Therefore **`.json` and `.xlsx` must become selectable checkboxes** under this policy. The previous canonical exclusion (do not offer JSON/XLSX as export targets) is superseded by this requirement: the user must be able to select any file they could see in the gray list for export.
- **Exclusions:** If there are files that should **not** be selectable (e.g. internal or canonical files that must never be copied to exports/), they must be stated exactly. Under the strict “gray list = checkbox list” interpretation, there are no exclusions: every file in the analysis tree is selectable. If policy later introduces exclusions (e.g. exclude `item.json` or certain internal files), they must be explicitly listed.

---

## 4. INVENTORY SOURCE OF TRUTH

- **The source of truth for the unified checkbox list must be the full analysis file inventory** — i.e. every file under the analysis directory(ies), recursively. That is what the old gray list showed.
- **It should come from:** The **analysis_dir file inventory** (or equivalent: rglob on the manifest’s analysis_dir, or on the same roots discovery uses: `analysis/`, `module/ot/`). This replaces the current filtered discovery as the primary inventory for the Export checkbox list. Discovery can be extended to enumerate all files, or a separate inventory function can be added; the key is that the inventory is **full** (every file in analysis), not filtered by type or pattern.
- **Merged/normalized inventory:** If both manifest analysis_dir and discovery roots are used, they must be consistent. The manifest’s analysis_dir is the canonical “where analysis lives” for this item; discovery uses `_analysis_roots(root)` which returns `[root/analysis, root/module/ot]`. For a typical item, analysis_dir may be one of those. The inventory should enumerate all files under the manifest’s analysis_dir (or under both roots if analysis_dir can point elsewhere). One source of truth: the analysis tree; one pass: enumerate all files; one list: checkboxes.
- **Displayed entries, checkbox ids, labels, and exported paths must all come from the same source.** Each inventory entry is one file path (relative to item root). That path is the `id`, the `path`, and the basis for the `label` (e.g. filename or short path). On EXPORT, only checked entries are copied; each maps to exactly one file. No mismatch between what is shown and what is copied.

---

## 5. UI DISPLAY RULES

- **One unified checkbox list:** The Export section shows a single list of selectable files. No second list.
- **Every displayed file line has a checkbox:** One checkbox per file. No passive lines.
- **Checkbox label corresponds to one concrete file:** Each label is derived from the file path (e.g. filename or relative path). User-readable; avoid raw path dumps if possible.
- **Select All / Clear All** operate on the full visible list (all checkboxes).
- **EXPORT button** depends on checked items (enabled when at least one checkbox is checked; disabled when none).
- **Avoid duplicate representation:** A file appears exactly once in the list. No duplicate checkboxes for the same path.

---

## 6. CURRENT LIKELY IMPLEMENTATION POINTS

- **Old gray file inventory source:**  
  - **File:** `barakuda/devices/optical_tweezers/ui/panel.py` (removed in prior step; formerly in `_refresh_export_status()`).  
  - **Logic:** `m.analysis_dir.rglob("*")` over manifest’s analysis_dir; paths relative to item root.  
  - **Manifest:** `barakuda/devices/optical_tweezers/manifest.py` — `load_item_manifest()`, `m.analysis_dir`, `_resolve_analysis_dir()`.

- **Current export discovery:**  
  - **File:** `barakuda/devices/optical_tweezers/export/discovery.py`.  
  - **Function:** `discover_analysis_artifacts(dataset_root)`.  
  - **Logic:** Walks `analysis/`, `module/ot/`; matches patterns for trajectory, tracking, psd, run_json, qc_report; filters out `.json` and `.xlsx`.

- **Checkbox rendering:**  
  - **File:** `barakuda/devices/optical_tweezers/ui/panel.py`.  
  - **Function:** `_refresh_export_artifact_checkboxes(artifacts)`.  
  - **Logic:** One checkbox per artifact; key `art["id"]`, label `art["label"]`.

- **Export click handling/copying:**  
  - **File:** `barakuda/devices/optical_tweezers/ui/panel.py`.  
  - **Function:** `_on_export_all_clicked()`.  
  - **Logic:** Iterates checked checkboxes; resolves artifact by id from `_export_artifacts`; copies `item_root / art["path"]` to exports dir.

- **Label generation:**  
  - **Discovery:** `"{label_prefix} — {filename}"` per artifact type.  
  - **Panel:** Uses `art["label"]` from discovery. For a full inventory, labels must be derived from path (e.g. filename or short relative path) when there is no type prefix.

---

## 7. RISKS

| Risk | Level | Notes |
|------|--------|------|
| Reintroducing mismatch between displayed lines and copied files | **MEDIUM** | If inventory and export logic use different sources or ids, displayed rows may not match copied files. Mitigation: single inventory source; one id/path per file; export copies by that path only. |
| Making canonical/internal files exportable unintentionally | **MEDIUM** | Under this policy, `.json` and `.xlsx` become selectable. Previous policy treated them as canonical (do not export). Users could now copy run.json, qc.json, results.xlsx to exports/. This is intentional per requirement but may surprise users who expect canonical files to stay internal. Document clearly. |
| Label readability | **LOW** | Full inventory may have many similar filenames (e.g. multiple `*_qc.json`). Labels must be distinguishable (e.g. include subpath or short relative path). |
| Refresh/rebuild regressions | **LOW** | Changing inventory source from discovery to full rglob could affect refresh timing or ordering. Ensure stable sort and consistent refresh trigger. |
| OT-only implementation vs future shared export system | **LOW** | Logic stays under OT panel/export; future shared system would need same one-checkbox-per-file contract and full-inventory semantics. |

---

## 8. SAFE IMPLEMENTATION ROADMAP

1. **Extend or replace discovery to return full analysis file inventory.** In `discovery.py` (or a new helper), add logic to enumerate all files under the manifest’s analysis_dir (or discovery roots), returning one candidate per file with unique path-based id, path, and label. Remove or bypass the canonical filter (`.json`/`.xlsx` exclusion) and pattern-based filtering so that every file is included. Keep the same dict shape (`id`, `label`, `path`) for compatibility with the panel.
2. **Wire the panel to use the full inventory.** In `_refresh_export_status()`, call the new full-inventory function (or extended discovery) instead of the current filtered discovery. Pass the result to `_refresh_export_artifact_checkboxes()`. No change to checkbox rendering logic; it already expects one checkbox per artifact.
3. **Verify export execution.** Confirm `_on_export_all_clicked()` still copies only checked entries by `art["path"]`. The same id/path contract applies; no change needed if inventory shape is preserved.
4. **Label generation for full inventory.** Ensure each file gets a readable label (e.g. filename, or `{subdir}/{filename}` when needed to disambiguate). May require a small label helper in discovery or panel.
5. **Manual verification.** Load a dataset with JSON, XLSX, CSV, PNG; confirm all appear as checkboxes; confirm Select All, Clear All, EXPORT work; confirm only checked files are copied.

---

## 9. FIRST RUNTIME STEP

- **What to do:** Extend discovery (or add a full-inventory function) so it returns every file under the analysis directory(ies), including `.json` and `.xlsx`, with one candidate per file. Remove the canonical filter for the Export inventory path.
- **Exact likely file(s):** `barakuda/devices/optical_tweezers/export/discovery.py`
- **Exact behavior to change:** Add a new function (e.g. `discover_all_analysis_files(dataset_root, analysis_dir)`) or a parameter to `discover_analysis_artifacts` (e.g. `include_canonical=True`) that enumerates all files under the given analysis dir via rglob, returns one dict per file with `id` = path, `path` = path, `label` = filename or short path. Do not filter by `.json`/`.xlsx`. Alternatively, replace the current discovery’s filtering with full enumeration when used for Export. The panel will need to call this full-inventory path instead of the filtered one; that wiring can be step 2.
- **Why first:** The inventory source is the foundation. Establishing a full-inventory function (or mode) in discovery ensures a single, consistent source of truth before the panel is wired to it. Doing discovery first avoids changing the panel twice.

---

*End of specification. No runtime code was modified in this step.*
