# Export Tab UI Bug — Diagnostic Report

**Date:** 2026-03-09  
**Scope:** Focused diagnostic only. No runtime code modified in this step.

---

## 1. SYMPTOM

- **Visible UI problem:** In the OT Export tab, analysis artifacts are listed (user sees a list of files under the dataset’s analysis area). The checkbox controls for selecting which artifacts to export are not visible. The EXPORT button remains disabled.

---

## 2. RELEVANT IMPLEMENTATION

| Responsibility | File | Class / method / path |
|----------------|------|-------------------------|
| Export tab UI creation | `barakuda/devices/optical_tweezers/ui/panel.py` | `PipelinePanel.__init__`: `export_box = QWidget()`, `_exp_layout = QVBoxLayout(export_box)`; header, Open button row, `_export_status_lbl`, `_export_files_lbl`, `_export_artifacts_container`, `_btn_export_all`; `tab_export` → `tab_export_layout` → `scroll_exp` (QScrollArea) → `scroll_exp.setWidget(export_box)` (lines 252–295, 556–563). |
| Artifact discovery → UI population | `panel.py` | `_refresh_export_status()` (1054): loads manifest via `load_item_manifest(item_json)`; builds file list for `_export_files_lbl` from `m.analysis_dir.rglob("*")`; calls `discover_analysis_artifacts(m.item_root)`; passes result to `_refresh_export_artifact_checkboxes(artifacts)` and sets `_btn_export_all.setEnabled(len(artifacts) > 0)`. |
| Checkbox widget creation | `panel.py` | `_refresh_export_artifact_checkboxes(artifacts)` (1134): for each group (DATA, REPORTS, PLOTS), builds `group_artifacts = [(aid, artifacts_by_id[aid]) for aid in artifact_ids if aid in artifacts_by_id]`; only when `group_artifacts` is non-empty adds a group header and per-artifact `QCheckBox(art["label"])` (1158–1162). |
| Checkbox container layout insertion | `panel.py` | Same method: checkboxes (and group headers) are added to `self._export_artifacts_layout` (VBoxLayout of `_export_artifacts_container`). Container is added to Export tab in `__init__` via `_exp_layout.addWidget(self._export_artifacts_container)` (287). |
| Export button enable/disable | `panel.py` | `_refresh_export_status()`: `self._btn_export_all.setEnabled(len(artifacts) > 0)` (1122). On error or no dataset: `setEnabled(False)` (1060, 1083, 1131). |
| Dataset selection / refresh wiring | `panel.py` | `set_dataset_path(path_str)` (1033) sets `_export_dataset_path` and calls `_refresh_export_status()`. Called from main_window when user selects an item. |
| Post-RUN refresh wiring | `barakuda/shell/main_window.py` | In `_on_ot_done()` (OT run completion): `paths = self.dataset.get_selected_paths()`; if paths and panel has `set_dataset_path`, calls `self._device_panel.set_dataset_path(str(paths[0]))` to refresh Export tab (478–483). |
| Discovery (backend) | `barakuda/devices/optical_tweezers/export/discovery.py` | `discover_analysis_artifacts(dataset_root)`: looks under `dataset_root/analysis/` for fixed filenames only (`trajectory.csv`, `tracking.csv`, `psd.csv`, `qc.json`, `run.json`); returns list of `{id, label, path}` for files that exist. |

---

## 3. ROOT CAUSE ANALYSIS

| Likely cause | Status | Notes |
|--------------|--------|--------|
| Checkbox widgets never created | **CONFIRMED** | When `discover_analysis_artifacts(m.item_root)` returns `[]`, `artifacts_by_id` is empty. For every group, `group_artifacts` is empty, so `if not group_artifacts: continue` runs and no headers or checkboxes are added. So with current discovery, checkboxes are never created. |
| Checkbox widgets created but not inserted into visible layout | **REJECTED** | When artifacts are non-empty, widgets are added to `_export_artifacts_layout` (container’s layout), and the container is in the Export tab’s main layout. Insertion path is correct. |
| Checkbox container hidden / zero height / wrong parent | **POSSIBLE** | Container is not explicitly hidden. When it has no children (empty layout), it may get minimal or zero height; that is a consequence of no checkboxes being added, not a separate visibility bug. |
| Stylesheet / palette makes them invisible | **REJECTED** | No stylesheet applied to Export checkboxes or container that would hide them. Group header uses `group_style` (color #555); checkboxes use default. |
| Refresh clears widgets but does not rebuild them | **REJECTED** | `_refresh_export_artifact_checkboxes` clears the layout then rebuilds from the current `artifacts` list. Rebuild logic is correct; when `artifacts` is empty, rebuild adds zero widgets. |
| Checkbox state map exists but UI not bound | **REJECTED** | `_export_artifact_checkboxes` is populated when checkboxes are created (1162). When no checkboxes are created, map is empty; no separate binding bug. |
| Export button enable logic depends on wrong condition | **REJECTED** | Enable condition is `len(artifacts) > 0`. That is correct; the issue is that `artifacts` is empty because discovery returns `[]`. |
| Selected dataset state missing in Export tab | **REJECTED** | Dataset path is set via `set_dataset_path`; `_refresh_export_status()` runs and uses it. Status label and file list are updated from the manifest; only the discovery result is empty. |
| Artifact list and checkbox list populated by different code paths | **CONFIRMED** | “Artifacts listed” comes from `_export_files_lbl`, filled from `m.analysis_dir.rglob("*")` (1100–1105) in `_refresh_export_status`. Checkboxes (and EXPORT enable) come from `discover_analysis_artifacts(m.item_root)`, which looks only under `m.item_root/analysis/` for fixed filenames. So the user sees files (rglob) but checkboxes/EXPORT depend on discovery (fixed names under `analysis/`), which often returns `[]` with current layout (e.g. `module/ot/` or stem-prefixed names). |

---

## 4. EXACT FAILURE POINT

- **Most likely failing function/method:** `discover_analysis_artifacts(dataset_root)` in `barakuda/devices/optical_tweezers/export/discovery.py`.
- **Exact reason:** It looks for fixed filenames (`trajectory.csv`, `tracking.csv`, `psd.csv`, `qc.json`, `run.json`) only under `dataset_root/analysis/`. Real outputs use stem-prefixed names (e.g. `{stem}_trajectory.csv`) and may live under `module/ot/` or `module/ot/ot_v2_shadow/`. So discovery returns an empty list; `_refresh_export_artifact_checkboxes([])` adds no checkboxes; `_btn_export_all.setEnabled(len(artifacts) > 0)` keeps the button disabled.
- **Bug category:** **Combination:** backend discovery (path/name mismatch) is the primary cause; UI correctly reflects the empty discovery result (no checkboxes, button disabled). The “listed” artifacts are from a different, manifest-based path (rglob), so the UI appears inconsistent.

---

## 5. SMALLEST SAFE FIX

- **Minimal one-step repair:** Make artifact discovery for the Export tab use the same analysis location and naming as the pipeline. Either:
  - **Option A:** In `discovery.py`, resolve the analysis directory from the manifest when an item root is used (e.g. accept optional manifest or item.json path and use `m.analysis_dir`), and discover artifacts by pattern (e.g. `*_trajectory.csv`, `*_qc.json`, `run.json`) under that dir and known subdirs; or
  - **Option B:** In `_refresh_export_status`, after loading the manifest, build the artifact list from the same files that populate `_export_files_lbl` (or from a scan of `m.analysis_dir` with stem/pattern-aware rules) and pass that list into the existing `_refresh_export_artifact_checkboxes` and button logic, without changing the checkbox/EXPORT behavior.
- **Exact runtime files to edit in the next step:**
  - **Option A:** `barakuda/devices/optical_tweezers/export/discovery.py` (and possibly `panel.py` to pass manifest or analysis_dir into discovery if the API changes).
  - **Option B:** `barakuda/devices/optical_tweezers/ui/panel.py` only: in `_refresh_export_status`, build an artifact list from `m.analysis_dir` (pattern or scan) in the same shape as discovery (`id`, `label`, `path`), then call `_refresh_export_artifact_checkboxes(artifacts)` and `setEnabled(len(artifacts) > 0)` unchanged.
- **Why smallest safe:** One code path is fixed (discovery or in-panel derivation) so that the Export tab gets a non-empty list when files exist. No schema, no experiment registry, no refactor of other tabs. Checkbox and EXPORT logic stay as-is.

---

## 6. VERIFY PLAN

After applying the fix in the next step:

1. **Branch:** Ensure branch is `integration/export-experiment-registry-fix`.
2. **Run app:** Start BARAKUDA, select OT device, open a dataset that has analysis outputs (e.g. item with `module/ot/` or `analysis/` containing stem-prefixed or known artifact files).
3. **Export tab:** Open the Export tab. Confirm `_export_status_lbl` shows the item and analysis path, and `_export_files_lbl` still lists files if present.
4. **Checkboxes:** Confirm that one or more checkbox(es) appear for discovered artifacts (e.g. Trajectory CSV, QC report), grouped under DATA / REPORTS (and PLOTS if applicable).
5. **EXPORT button:** Confirm the EXPORT button becomes enabled when at least one artifact is discovered.
6. **Export action:** Select/deselect checkboxes, click EXPORT; confirm selected files are copied to the dataset’s `exports/` folder and status message updates.
7. **Regression:** With no dataset or invalid path, confirm status shows “No dataset loaded.” or error, no checkboxes, and EXPORT stays disabled.

---

*End of report. No runtime code was modified.*
