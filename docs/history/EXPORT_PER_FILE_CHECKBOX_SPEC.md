# Per-File Export Checkbox Specification

**Branch:** `integration/export-per-file-checkboxes`  
**Scope:** Define the change from grouped logical export checkboxes to one checkbox per concrete generated file. No runtime code changes in this step.

---

## 1. PURPOSE

- **Target behavior:** Every generated exportable file gets its own checkbox in the Export section. One checkbox = one concrete file on disk.
- **Why change:** Grouped logical export checkboxes (e.g. one “Trajectory CSV” or “PSD spectrum CSV” representing a single chosen file per type, or one checkbox per artifact family) are no longer sufficient. Users need to select or deselect individual files. Logical grouping that merges multiple files into one checkbox prevents fine-grained control and can hide which exact files will be copied.

---

## 2. CURRENT BEHAVIOR

- **Export checkbox discovery (OT):** The Export tab uses `discover_analysis_artifacts(dataset_root)` from `barakuda.devices.optical_tweezers.export.discovery`. Discovery walks the dataset’s analysis roots (`analysis/`, `module/ot/`) and, for each **logical artifact type** (trajectory_csv, tracking_csv, psd_csv, qc_report, run_json), finds at most **one** file via `_first_file_under()` with pattern lists. It returns a list of dicts with `id`, `label`, and `path`, where `id` is the logical type (e.g. `"trajectory_csv"`) and `path` is the relative path to that one file.
- **Where grouped entries are produced:** In `discovery.py`, each logical type is added at most once (`seen_ids`). So one entry per type is produced; e.g. one “PSD spectrum CSV” entry even when multiple PSD CSVs exist (e.g. `*_psd_x.csv`, `*_psd_y.csv`). The UI then builds one checkbox per entry, keyed by `art["id"]`.
- **Examples of grouped behavior:**
  - One “Trajectory CSV” checkbox represents the first matching trajectory file found; other trajectory CSVs are not listed.
  - One “PSD spectrum CSV” checkbox represents one PSD file; other PSD CSVs (e.g. x/y axes) are not listed.
  - One “Tracking CSV” checkbox represents one tracking CSV; other tracking CSVs under subdirs are not listed.
  - Checkbox identity is logical (`trajectory_csv`, `psd_csv`, etc.), not file-unique, so the same id could in theory refer to different paths across datasets when exporting multiple items; in practice one path per id per discovery run.

---

## 3. TARGET BEHAVIOR

- **One checkbox per concrete file:** Every concrete exportable file must have its own checkbox. No checkbox may represent more than one file.
- **Checkbox identity = one real file:** Checkbox identity must map to exactly one real file on disk (e.g. stable id derived from relative path or path hash).
- **No merged checkboxes:** No checkbox may represent multiple files. If three CSV files exist, there must be three checkboxes (or three entries that each have their own checkbox).
- **Only existing files:** Only files that exist on disk may appear as export candidates. Discovery must not offer paths that do not exist.
- **Canonical outputs stay excluded:** Outputs excluded by current policy (e.g. `.json` and `.xlsx` as canonical) must remain excluded from the Export list unless the current code already includes them (current discovery explicitly filters out `.json` and `.xlsx`; that policy stays unless a separate change is specified).
- **Optional exportables per file:** Optional exportable files (e.g. `.csv`, `.png`, and similar per-file byproducts) should each appear as an individual checkbox when present.

---

## 4. UI DISPLAY RULES

- **One label per file:** Each checkbox label must correspond to one concrete file. Labels should be user-readable (e.g. short filename or human-readable description), not raw internal path dumps, when avoidable.
- **Visual grouping (if any):** If grouping is still used (e.g. DATA / REPORTS / PLOTS), it must group **individual file checkboxes**, not merge multiple files into one checkbox. Each row remains one file.
- **Select All / Clear All:** Select All and Clear All must operate on the full per-file checkbox list (check or uncheck every visible export file checkbox).
- **EXPORT button:** The EXPORT button’s enabled state must continue to depend on the current set of checked per-file checkboxes (e.g. enabled when at least one checkbox is checked and discovery succeeded; disabled when none checked or no artifacts).

---

## 5. BACKEND MAPPING

- **Unique identity per file:** Each export candidate returned by discovery (or the backend model feeding the Export UI) must contain a unique identity for **one** file (e.g. path-based id or composite key). No two candidates may share the same identity when they refer to different files.
- **One path per candidate:** Each candidate’s `path` (or equivalent) must point to exactly one real file. One candidate must not describe multiple paths or a pattern that could resolve to multiple files.
- **Export execution:** When the user clicks EXPORT, only the checked **file** candidates must be copied. Each checked checkbox must result in copying exactly one file. No implicit fan-out from one checkbox to multiple files.

---

## 6. CURRENT LIKELY IMPLEMENTATION POINTS

- **Export discovery:**  
  - `barakuda/devices/optical_tweezers/export/discovery.py`: `discover_analysis_artifacts()`, `_first_file_under()`, `_ARTIFACT_DEFS`, and the per-type loop that produces one entry per logical id. Today this is the place that “groups” by type and returns one path per type.
- **Export checkbox rendering:**  
  - `barakuda/devices/optical_tweezers/ui/panel.py`: `_refresh_export_artifact_checkboxes(artifacts)`, which builds checkboxes from the discovery result and groups them under DATA / REPORTS / PLOTS; `_export_artifact_checkboxes` (dict id → QCheckBox); `_export_artifacts` (last discovery result).
- **Export click handling / copying:**  
  - `barakuda/devices/optical_tweezers/ui/panel.py`: `_on_export_all_clicked()`: iterates `_export_artifact_checkboxes`, resolves artifact by `aid` from `self._export_artifacts` via `art_by_id.get(aid)`, and copies `item_root / art["path"]` to `exports/`. Relies on unique `aid` per checkbox; for per-file, each file must have a distinct id and a matching entry in the artifacts list.
- **Label generation for Export section:**  
  - Currently the label comes from discovery (`art["label"]`), which is the fixed logical label (e.g. “Trajectory CSV”). For per-file, labels will need to be derived per file (e.g. from filename or path) in discovery or in the panel when building checkboxes.

---

## 7. RISKS

| Risk | Level | Notes |
|------|--------|------|
| Breaking current export discovery | **MEDIUM** | Changing discovery from “one per type” to “one per file” can break callers that assume one id per type or a fixed set of ids. Mitigation: change discovery contract and UI together; keep export execution aligned with new candidate shape. |
| Mismatch between checkbox state and copied files | **HIGH** | If checkbox id or artifact list does not uniquely map to one file, EXPORT could copy wrong or duplicate files. Mitigation: ensure unique id per file and single path per candidate; copy by that path only. |
| Confusing labels for users | **LOW** | Per-file labels (e.g. many similar filenames) could be hard to distinguish. Mitigation: use short but readable labels (e.g. filename or path tail) and optional grouping by folder/type. |
| Refresh/rebuild regressions | **MEDIUM** | Rebuilding checkboxes on refresh (e.g. after RUN or dataset change) must repopulate the per-file list correctly; keying by path or stable id can avoid duplicate or missing checkboxes. |
| OT-only implementation vs future shared export system | **LOW** | Logic lives under OT export and OT panel; if a shared export system is introduced later, this spec’s rules (one checkbox per file, unique id, one path per candidate) should apply there too to avoid divergence. |

---

## 8. SAFE IMPLEMENTATION ROADMAP

1. **Discovery: enumerate all files per type**  
   In `discovery.py`, replace “first file per type” with “all matching files per type” (or equivalent) and return one candidate per file with a **unique id** (e.g. path or normalized path) and a human-readable **label** per file. Preserve canonical exclusion (no `.json`/`.xlsx` in the list). No UI change yet; discovery contract change only.

2. **Panel: key checkboxes by file-unique id**  
   In `panel.py`, ensure `_refresh_export_artifact_checkboxes` and `_export_artifact_checkboxes` use the new per-file id (no longer one id per type). Ensure `_export_artifacts` stores one entry per file and that `art_by_id` in `_on_export_all_clicked` resolves each checked id to exactly one artifact with one path.

3. **Export execution: copy one file per checked id**  
   In `_on_export_all_clicked`, keep logic “for each checked checkbox, get artifact by id and copy `art["path"]` once.” Ensure destination naming (e.g. under `exports/`) avoids collisions when multiple files share the same basename (e.g. by subpath or unique name).

4. **Labels and grouping**  
   Optionally improve per-file labels (e.g. show filename or short path) and keep DATA/REPORTS/PLOTS grouping as grouping of individual file checkboxes only.

5. **Select All / Clear All and EXPORT button**  
   Confirm Select All and Clear All still operate on all visible per-file checkboxes and EXPORT button state still depends on “at least one checked” (and any existing “has artifacts” condition).

---

## 9. FIRST RUNTIME STEP

- **What to do:** Change discovery so it returns **one entry per concrete file** instead of one per logical type, with a **unique id per file** and one **path** per entry.
- **Exact likely file(s):** `barakuda/devices/optical_tweezers/export/discovery.py`
- **Exact behavior to change:** Replace the per-type loop that uses `_first_file_under` and `seen_ids` with logic that **enumerates all** matching files for each optional-export type (e.g. all `*_trajectory.csv`, all `*_psd*.csv`, etc.), and append one dict per file with a unique `id` (e.g. normalized path or path-based slug) and a per-file `label` (e.g. filename). Keep the same canonical filter (exclude `.json` and `.xlsx`). Do not change the panel or export execution in this step; callers may temporarily receive more entries than before, so the panel must be updated in the next step to key by the new id and avoid collisions.
- **Why first:** Discovery is the single source of truth for “what can be exported.” Establishing the per-file list and stable ids there keeps the rest of the pipeline (UI and copy) as a straightforward consumer of that list. Doing discovery first avoids changing UI and copy logic twice.

---

*End of specification. No runtime code was modified in this step.*
