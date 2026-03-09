# Unified Export Checkbox List Specification

**Branch:** `integration/export-unified-checkbox-list`  
**Scope:** Define the change from a dual representation (passive gray artifact list + selectable checkboxes) to one unified list where every displayed export artifact line has a checkbox. No runtime code changes in this step.

---

## 1. PURPOSE

- The Export section should **no longer show passive gray artifact lines separate from selectable checkboxes.** Today the UI shows (1) a gray text block listing files and (2) below it a list of checkboxes. That creates two different visual models of the same export data and confuses which files are actually selectable.
- **Every displayed export artifact line must be selectable via its own checkbox.** The only list of exportable artifacts shown to the user should be the checkbox list: one line per file, one checkbox per line. There should not be a second, read-only list of the same or different files.

---

## 2. CURRENT BEHAVIOR

- **How the gray artifact list is built:** In `_refresh_export_status()` (OT panel), two QLabels are filled:
  - **`_export_status_lbl`:** Summary lines: "Item: {item_folder_name}", "Analysis: {relative_path_to_analysis_dir}", and "Exports: {relative_path_to_exports_dir}" when present. Style: gray (#666), word wrap.
  - **`_export_files_lbl`:** A **full recursive file listing** of every file under the manifest’s `m.analysis_dir`. Built with `m.analysis_dir.rglob("*")`; each file is one line, indented with two spaces, showing the path relative to item root. Style: #444, 10px. If there is no analysis dir or no files, it shows "(no files yet)". This is the passive “gray artifact list”: read-only text, no checkboxes.

- **How the checkbox list is built:** In `_refresh_export_artifact_checkboxes(artifacts)` (same panel), the list comes from `discover_analysis_artifacts(m.item_root)`. Discovery returns only **optional export candidates**: files matching specific patterns (trajectory, tracking, PSD CSVs, etc.) and **excludes** canonical outputs (`.json` and `.xlsx`). Each candidate has `id`, `label`, and `path`. One checkbox is created per artifact; key is `art["id"]`, label is `art["label"]`. These checkboxes are added to `_export_artifacts_layout` inside `_export_artifacts_container`.

- **Where the two lists come from and why they differ:**  
  - **Gray list:** Data source is the manifest’s `analysis_dir` plus a raw `rglob("*")` — i.e. **every file** under the analysis directory.  
  - **Checkbox list:** Data source is **discovery** (`discover_analysis_artifacts`), which returns only a **subset** of files (optional export types, excluding .json/.xlsx).  
  So the gray list is “everything in analysis”; the checkbox list is “only what discovery considers exportable”. They differ in content and in interaction (one passive, one selectable).

- **Whether the gray list includes files not in discovery/checkboxes:** **Yes.** The gray list includes all files under `analysis_dir` (e.g. all `.json`, `.xlsx`, and any other files). Many of these are **not** in the discovery result and therefore have **no** checkbox. So the user sees a long gray list of files and below it a shorter list of checkboxes, with no one-to-one mapping between the two.

---

## 3. TARGET BEHAVIOR

- **Every displayed export artifact line must have a checkbox.** There must be no second list of artifacts that is display-only. One displayed line = one checkbox = one concrete file.
- **There must not be a separate passive gray artifact list for the same files.** Either remove the gray file listing entirely, or replace it with the same set of entries as the checkbox list (and then unify so there is only one list with checkboxes). The preferred target is a single unified list: the only artifact lines shown are the selectable checkbox rows.
- **Only existing files may appear.** The unified list must still be driven by discovery (or a single source of truth) so that only files that exist on disk and are considered exportable are shown.
- **Current code intentionally excludes some classes of files from selectable export:** Discovery excludes canonical outputs (suffix `.json` and `.xlsx`) from the list it returns. So run.json, qc.json, results.xlsx, etc. do **not** appear in the checkbox list. The unified list should continue to show only what discovery returns (optional export candidates). It must **not** start showing every file from the analysis dir as a checkbox unless policy is explicitly changed to “all files exportable.”
- **If current export policy and current UI conflict:** The conflict is: the **gray list** shows “all files in analysis” (rglob) while **policy** is “only optional export candidates get checkboxes.” The unified list must follow policy: one list, one checkbox per line, and that list is exactly the discovery result. The gray list that shows more than discovery should be removed so that the only artifact representation is the checkbox list.

---

## 4. UI DISPLAY RULES

- **One unified list of selectable artifact entries:** The Export section must show a single list where every row is an exportable file and has a checkbox. No separate passive list of the same or different files.
- **Checkbox label must correspond to one concrete file.** Each label is the discovery label for that file (e.g. "Trajectory CSV — filename.csv").
- **No duplicate visual representation of the same file.** A file must not appear both as a gray line and as a checkbox row. It appears only once, as a checkbox row.
- **Select All / Clear All** must operate on the full visible artifact list (all checkboxes in the unified list).
- **EXPORT button state** must continue to depend on the current checked items (enabled when at least one checkbox is checked and discovery succeeded; disabled otherwise).
- **The current top gray list should be removed entirely** in the sense of the **file listing** (`_export_files_lbl` content built from `rglob("*")`). That passive list duplicates or exceeds the exportable set and must not remain as a second artifact list. Short summary lines (e.g. "Item: …", "Analysis: …") may be kept as context above the checkbox list if desired, but the long gray file tree must go. The only list of artifacts is the checkbox list.

---

## 5. BACKEND / UI MAPPING

- **Discovery/inventory source:** A single source of truth must drive the Export artifact list. That is `discover_analysis_artifacts(dataset_root)`. The unified UI must not use a different source (e.g. rglob) for displaying artifact lines.
- **Checkbox ids:** Each checkbox is keyed by the candidate’s `id` (path-based from discovery). No duplicate ids; one id per file.
- **Checkbox labels:** Labels come from discovery (`art["label"]`). One label per file.
- **Exported file paths:** On EXPORT click, only checked checkboxes are considered; each maps via `art["path"]` to one file. The path must be the same as in discovery.
- **Clicked EXPORT result:** Only the files corresponding to checked checkboxes are copied to `exports/`. No implicit inclusion of files that are not in the checkbox list.
- **No mismatch:** What is shown in the unified list must be exactly what can be exported when checked. There must be no second list suggesting other files that are not selectable or not copied.

---

## 6. CURRENT LIKELY IMPLEMENTATION POINTS

- **Gray artifact list rendering:**  
  - **File:** `barakuda/devices/optical_tweezers/ui/panel.py`  
  - **Function:** `_refresh_export_status()`.  
  - **Widgets:** `_export_status_lbl` (summary: Item, Analysis, Exports paths), `_export_files_lbl` (full file tree from `m.analysis_dir.rglob("*")`).  
  - **Data:** Manifest `m` from `load_item_manifest(item_json)`; `m.analysis_dir`; iteration over `m.analysis_dir.rglob("*")` for file lines.

- **Export discovery:**  
  - **File:** `barakuda/devices/optical_tweezers/export/discovery.py`  
  - **Function:** `discover_analysis_artifacts(dataset_root)`.  
  - **Returns:** List of dicts with `id`, `label`, `path` for optional export candidates only (canonical .json/.xlsx excluded).

- **Checkbox rendering:**  
  - **File:** `barakuda/devices/optical_tweezers/ui/panel.py`  
  - **Function:** `_refresh_export_artifact_checkboxes(artifacts)`.  
  - **Widgets:** `_export_artifacts_container` / `_export_artifacts_layout`; `_export_artifact_checkboxes` (dict id → QCheckBox).  
  - **Data:** `artifacts` from discovery, passed from `_refresh_export_status()` after calling `discover_analysis_artifacts(m.item_root)`.

- **Export click handling/copying:**  
  - **File:** `barakuda/devices/optical_tweezers/ui/panel.py`  
  - **Function:** `_on_export_all_clicked()`.  
  - **Logic:** Iterates `_export_artifact_checkboxes`, resolves artifact by id from `_export_artifacts`, copies `item_root / art["path"]` for each checked item.

- **Label generation:**  
  - **Discovery:** Each candidate’s `label` is built in `discovery.py` as `"{label_prefix} — {filename}"`.  
  - **Panel:** Checkbox text is `art["label"]` from discovery; no separate label generation in the panel for the checkbox list. The **gray list** labels are raw relative paths from `f.relative_to(m.item_root)` in `_refresh_export_status()`.

---

## 7. RISKS

| Risk | Level | Notes |
|------|--------|------|
| Showing files that should not be exportable | **LOW** | If the gray list is removed and the only list is discovery-driven, we avoid showing non-exportable files. Risk is low if we do not add a new source (e.g. rglob) to the unified list. |
| Mismatch between displayed lines and copied files | **LOW** | Today discovery and checkbox list are aligned; export copies by checkbox id/path. Unification does not change that contract; risk is low if we only remove the gray list and keep discovery as sole source. |
| Label readability | **LOW** | Same as today (discovery labels); no new risk from unification. |
| Refresh/rebuild regressions | **MEDIUM** | Removing or changing `_export_files_lbl` and possibly simplifying `_refresh_export_status()` could affect refresh behavior. Careful to repopulate only from discovery and not leave stale UI. |
| OT-only implementation vs future shared export system | **LOW** | Unification is UI-only in OT panel; a future shared export system would still need one list = one checkbox per file. |

---

## 8. SAFE IMPLEMENTATION ROADMAP

1. **Remove the passive gray file listing from the Export section.** In `_refresh_export_status()`, stop populating `_export_files_lbl` with the rglob file tree. Either set it to empty string or remove the widget from the layout so the only artifact list is the checkbox list. Keep summary lines in `_export_status_lbl` (Item, Analysis, Exports) if desired for context.
2. **Ensure the checkbox list remains the single artifact list.** Confirm that after step 1, no other widget shows a second list of files. Select All / Clear All and EXPORT button already operate on the checkbox list; no change needed there.
3. **Optional: simplify or hide the summary block.** If "Item:" / "Analysis:" lines are still useful, keep them above the checkbox list. If redundant, consider shortening or moving; do not reintroduce a file listing.
4. **Manual verification.** Load a dataset, open Export; confirm one list only (checkboxes), no gray file tree; confirm Select All, Clear All, EXPORT still work.

---

## 9. FIRST RUNTIME STEP

- **What to do:** Remove the passive gray file listing so that the Export section no longer shows a second list of files. The only list of artifacts must be the checkbox list.
- **Exact likely file(s):** `barakuda/devices/optical_tweezers/ui/panel.py`
- **Exact behavior to change:** In `_refresh_export_status()`, stop building and setting the `_export_files_lbl` content from `m.analysis_dir.rglob("*")`. Set `_export_files_lbl.setText("")` always (or remove the widget from the layout and any references). Do not change discovery, checkbox building, or export execution. Optionally keep `_export_status_lbl` with short summary (Item, Analysis path, Exports path) so the user still sees which dataset is loaded. This is the first safe step because it removes the duplicate visual model without changing the selectable list or export behavior; the checkbox list already exists and remains the single source of truth for what is shown and what can be exported.

---

*End of specification. No runtime code was modified in this step.*
