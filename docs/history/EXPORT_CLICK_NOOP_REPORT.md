# OT Export Click No-Op — Diagnostic Audit Report

**Branch:** `diagnostic/export-click-no-op`  
**Date:** 2026-03-09  
**Scope:** Focused diagnostic only. No runtime code modified in this step.

---

## 1. PURPOSE

This audit isolates why the OT Export action appears to do nothing (user clicks EXPORT; no visible effect; `exports/` is not produced in the dataset snapshot; OT output layout still shows legacy `module/ot` and `ot_v2_shadow`) before any runtime fix is attempted. The goal is to identify exact code paths, failure candidates, and the single most likely cause so the next patch can be minimal and safe.

---

## 2. RELEVANT IMPLEMENTATION

| Responsibility | File(s) | Class / method / path |
|----------------|--------|------------------------|
| Export button creation | `barakuda/devices/optical_tweezers/ui/panel.py` | `PipelinePanel.__init__`: `self._btn_export_all = QPushButton("EXPORT")` (line 301), added to `_exp_layout` (306). |
| Export button signal connection | `panel.py` | Same: `self._btn_export_all.clicked.connect(self._on_export_all_clicked)` (306). |
| Export button enable/disable state | `panel.py` | `_update_export_button_state()` (1154–1157): enables when `has_any and any_checked` (at least one checkbox exists and at least one checked). Called from `_refresh_export_artifact_checkboxes` and checkbox `stateChanged`. `_refresh_export_status()` also sets `setEnabled(False)` when no dataset or error (1072, 1095, 1133). |
| Export dataset path selection / multi-selection source | `panel.py`: `set_dataset_path(path_str)` (1045–1048) sets `_export_dataset_path` and calls `_refresh_export_status`. `set_export_paths(paths)` (1050–1052) sets `_export_paths`. `main_window.py` (277–286): `_on_item_selected` calls `set_dataset_path(str(path))` and `set_export_paths(self.dataset.get_selected_paths())`. Selection comes from `dataset_panel.get_selected_paths()` (Path(s) stored in list item `UserRole`). |
| Artifact discovery feeding Export UI | `barakuda/devices/optical_tweezers/export/discovery.py`: `discover_analysis_artifacts(dataset_root)`. Uses `_analysis_roots(root)` → `[root/"analysis", root/"module"/"ot"]` (only dirs that exist). For each analysis root, `rglob("*")`; each file gets `id`/`label`/`path` (path relative to `dataset_root`). `panel.py` `_refresh_export_status()` (1125–1128): after loading manifest, calls `discover_analysis_artifacts(m.item_root)` and assigns result to `_export_artifacts`, then `_refresh_export_artifact_checkboxes(artifacts)`. |
| Checkbox map/state | `panel.py`: `_export_artifact_checkboxes: dict[str, QCheckBox]` keyed by artifact `id` (path string). `_refresh_export_artifact_checkboxes(artifacts)` (1136–1152): clears layout, one `QCheckBox(art["label"])` per artifact, `art["id"]` as key; `stateChanged` → `_update_export_button_state`. |
| Export click handling | `panel.py`: `_on_export_all_clicked()` (1170–1236). Builds `paths_to_export` from `_export_paths` or `[_export_dataset_path]`; for each path resolves `item_json` (same candidate logic as refresh); resolves `item_root`; builds `to_copy` from checked checkboxes with `art_by_id.get(aid)` and `(item_root / art["path"]).is_file()`; if `to_copy` non-empty, `mkdir exports`, copies files, appends to `export_dirs`; finally sets status label or "Export failed: no valid dataset path(s)." |
| Destination `exports/` directory creation | `panel.py` `_on_export_all_clicked`: `exports_dir = item_root / "exports"`; `exports_dir.mkdir(parents=True, exist_ok=True)` only when `to_copy` is non-empty for that path (1219–1221). |
| File copy execution | Same: `_shutil.copy2(src, dst)` with `src = item_root / art["path"]`, `dst = exports_dir / Path(art["path"]).name` (1222–1225). |
| Export status/error reporting | Same: success → `self._export_status_lbl.setText("Exported {n} file(s) to:\n" + dirs)`; no valid path → "Export failed: no valid dataset path(s)."; exception → "Export error:\n{!r}". No other logging. |

**Item.json resolution (shared by refresh and click):** In both `_refresh_export_status` and `_on_export_all_clicked`, `item_json` is set as: if `path.name == "item.json"` then `item_json = path`; else loop over candidates `(path.parent / "item.json", path.parent.parent / "item.json")` and use first existing. There is **no** candidate `path / "item.json"` when `path` is a directory (e.g. the item folder).

---

## 3. CURRENT LIKELY FAILURE POINTS

| Candidate cause | Status | Notes |
|-----------------|--------|--------|
| Button click not connected | **REJECTED** | `clicked.connect(self._on_export_all_clicked)` in `panel.py` line 306. |
| Button disabled by state logic when user expects it enabled | **POSSIBLE** | If `_refresh_export_status` never succeeds (e.g. item.json not found), checkboxes are cleared and button disabled; user may have expected button enabled after selecting an item. |
| `_on_export_all_clicked` not reached | **REJECTED** | Signal is connected; if button were enabled, handler would run. |
| `_export_paths` / `_export_dataset_path` empty or wrong at click time | **POSSIBLE** | If selection is the item **folder** path, both refresh and click use the same item_json resolution; if that resolution fails, `paths_to_export` can still be `[folder path]` but every iteration fails to find `item_json` → `continue` → no exports, "Export failed: no valid dataset path(s)." |
| Artifact ids in checkbox state do not match `self._export_artifacts` | **REJECTED** | Checkboxes are keyed by `art["id"]` and built from the same `artifacts` list stored in `_export_artifacts`; `art_by_id` in handler is from `_export_artifacts`. |
| Handler iterates but copies zero files | **POSSIBLE** | If for every path in `paths_to_export` either `item_json` is None (resolution gap) or `to_copy` is empty (e.g. no checked boxes or no file at `item_root / art["path"]`), no copy runs and no `exports/` is created. |
| Handler creates no `exports/` because no checked/valid files survive | **POSSIBLE** | Same as above: `to_copy` empty → `continue` → no mkdir/copy for that path. |
| Exceptions swallowed or only written to a label the user may miss | **POSSIBLE** | Exceptions in `_on_export_all_clicked` set `_export_status_lbl` to "Export error:\n{!r}"; no log or dialog. User might not notice the label. |
| Export status text updates but filesystem output absent | **POSSIBLE** | If handler runs but all iterations hit `item_json is None` or `not to_copy`, status becomes "Export failed: no valid dataset path(s)." — user may see this as "nothing happened" if the label is overlooked. |
| Current working tree behavior differs from inspected snapshot layout | **REJECTED** | Snapshot layout is used only to document where files are; code paths above are from current sources. |

**Item.json resolution when selection is the item folder:** When the dataset list selection is the **item directory** path (e.g. `.../items/2026-02-19-Bead1um-0-um_s`), the code only checks `path.parent / "item.json"` and `path.parent.parent / "item.json"`. It does **not** check `path / "item.json"`. So `item_json` is **never** found for that selection. Consequence: (1) In `_refresh_export_status`, status shows "No item.json found near: ...", checkboxes cleared, EXPORT disabled. (2) In `_on_export_all_clicked`, if that path is in `paths_to_export`, the loop does `if item_json is None: continue`, so no export for that path; if all paths are item folders, `export_dirs` stays empty and status shows "Export failed: no valid dataset path(s)."

---

## 4. DATASET SNAPSHOT FINDINGS

Evidence: OT run snapshot `runs/ot/2026-03-09_204108/items/2026-02-19-Bead1um-0-um_s/` and its `item.json`.

- **`exports/`:** **Absent.** The item directory contains no `exports/` folder. Export has not successfully run for this snapshot (or no run created it).
- **Preview outputs:** Under `module/ot/preview/`: e.g. `2026-02-19-Bead1um-0-um_s_preview_tracking.png`, `preview_report.json`.
- **Legacy root-level outputs in `module/ot`:** Present: e.g. `module/ot/run.json`, `module/ot/2026-02-19-Bead1um-0-um_s_qc.png`, `module/ot/2026-02-19-Bead1um-0-um_s_results.csv`, `module/ot/2026-02-19-Bead1um-0-um_s_results.xlsx`, plus subdirs `audit/`, `physics/`, `tracking/`.
- **`ot_v2_shadow`:** Present under `module/ot/ot_v2_shadow/`: e.g. `*_trajectory.csv`, `*_qc.json`, `*_ot_summary.json`, `welch_psd_*.png`, `run_manifest.json`, `results.csv`, `*_derived.csv`, `*_camera_meta.json`.
- **`item.json` and analysis pointers:** `item.json` has `analysis.dir` = `"module/ot"`, `analysis.trajectory` = `"module/ot/ot_v2_shadow/2026-02-19-Bead1um-0-um_s_trajectory.csv"`, `analysis.qc` and `analysis.summary` also under `module/ot/ot_v2_shadow/`. So key analysis outputs are pointed into `ot_v2_shadow`; discovery scans `module/ot` (including `ot_v2_shadow`) and would find these files by path.

---

## 5. EXACT FAILURE HYPOTHESIS

**Single most likely explanation for “EXPORT does nothing”:**

- **Primary issue:** **Selection/path state and item.json resolution.** When the user selects the OT dataset from the list, the stored path is often the **item folder** (e.g. `.../items/2026-02-19-Bead1um-0-um_s`). Both `_refresh_export_status` and `_on_export_all_clicked` resolve `item_json` only from `path.parent / "item.json"` and `path.parent.parent / "item.json"`; they never check `path / "item.json"`. So when the selected path is the item directory, `item_json` is never found. That yields: (1) Refresh shows "No item.json found", no checkboxes, EXPORT disabled — so the user sees no export UI state, or (2) If the user had previously opened by dialog (item.json path) and then changed selection to the folder, or if `_export_paths` contains folder paths, the click handler runs but every path fails resolution, so no `exports/` is created and status shows "Export failed: no valid dataset path(s)." In both cases the observable result is “click EXPORT → nothing useful; no `exports/`.”

- **Category:** Selection/path state (missing resolution case for item directory).

---

## 6. EXACT NEXT SAFE PATCH

- **File(s):** `barakuda/devices/optical_tweezers/ui/panel.py` only.
- **Behavior to change:** In both `_refresh_export_status` and `_on_export_all_clicked`, when resolving `item_json` from a path that is not already `item.json`, add the candidate **`path / "item.json"`** (when `path` is a directory) to the list of candidates checked (e.g. first in the loop so that selecting the item folder finds `item.json` inside it).
- **Why smallest safe step:** Fixes the single identified resolution gap that causes “no item.json” when the selected path is the item folder; no change to discovery, schema, or experiment registry; no refactor of other tabs; export logic (to_copy, mkdir, copy, status) remains unchanged.

---

## 7. LAYOUT FOLLOW-UP NOTE

The OT layout issue is separate from the Export no-op:

- **Legacy root-level outputs in `module/ot`:** Current runs still write canonical and optional outputs under `module/ot/` (and subdirs like `physics/`, `tracking/`, `audit/`). The canonical target layout is `acquisition/` + `analysis/` + `exports/`.
- **`ot_v2_shadow` overlap:** Strategy/exporter outputs live under `module/ot/ot_v2_shadow/` and `item.json` points key analysis fields there. Discovery already scans `module/ot` (including `ot_v2_shadow`), so Export can find files; the no-op is due to item_json resolution, not discovery paths.
- **Recommendation:** Address layout migration (e.g. writing to `analysis/` instead of `module/ot`, and eventual deprecation of `ot_v2_shadow`) only **after** EXPORT is fixed and verified (e.g. `exports/` created and populated when the user clicks EXPORT). Doing layout changes first could obscure or regress the Export fix.

---

## 8. VERIFY PLAN

After applying the next runtime patch (add `path / "item.json"` candidate in `panel.py`):

1. **Branch:** Confirm branch is `diagnostic/export-click-no-op` (or the branch that contains the patch).
2. **Run app:** Start BARAKUDA, select OT device, load a dataset that includes an OT item (e.g. item folder or item.json from `runs/ot/.../items/<id>/`).
3. **Select item folder:** In the Dataset list, select the row that corresponds to the **item folder** path (e.g. path ending in `.../items/2026-02-19-Bead1um-0-um_s`).
4. **Export tab:** Open the Export tab. Confirm status shows the item and analysis path (e.g. "Item: ...", "Analysis: module/ot") and that at least one artifact checkbox is visible and EXPORT is enabled.
5. **Export action:** Check one or more artifacts, click EXPORT. Confirm `exports/` is created under the item root and selected files are copied into it, and status shows "Exported N file(s) to: ...".
6. **No regression:** With no dataset selected or invalid path, confirm status shows "No dataset loaded." or "No item.json found...", no checkboxes, and EXPORT remains disabled.
7. **Single commit:** Confirm exactly one commit was created for the diagnostic report step; no runtime source files were modified in that commit.

---

*End of report. No runtime code was modified in this step.*
