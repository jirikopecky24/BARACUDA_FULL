# AFM ROI Explorer — Design Note

**Task:** AFM-A1t step 0 — Design BARAKUDA integrated AFM ROI Explorer
**Date:** 2026-07-03
**Branch:** feature/afm-hydrogel-porosity
**Status:** design only — no implementation, no production code changes

**WARNING:** This note describes a future visualization/QA tool. It is not a request to compute porosity, pore metrics, roughness, or to select a final production channel.

---

## A. Current diagnostic limitation

The current diagnostic workflow produced an interactive 3D surface with Plotly (`AFM-A1s`):

- `page5_height_interactive_3d.html`
- `page4_measuredHeight_interactive_3d.html`
- `page5_page4_comparison_interactive_3d.html`

These HTML files are useful for quick surface inspection, but they are **external browser-style artifacts**, not part of BARAKUDA's integrated workflow. They do not provide:

- channel switching inside the same UI,
- mask candidate toggling,
- opacity control,
- interactive line-profile tools,
- profile plots tied to the selected topography channel,
- a path back into the AFM analysis pipeline.

For production-level QA, an **integrated BARAKUDA AFM ROI Explorer** is needed.

---

## B. Recommended minimal v0 viewer

### v0 scope (visualization/QA only)

1. **2D map panel**
   - Render the aligned ROI as a color map with a colorbar.
   - X/Y axes in µm, Z values in nm (or other native units for auxiliary channels).
   - Support zoom and pan.

2. **Channel selector**
   - `Page 5 height calibrated` (primary topography)
   - `Page 4 measuredHeight nominal` (control topography)
   - `Page 2 adhesion` (auxiliary contrast)
   - `Page 3 slope` (auxiliary QC)
   - optionally `Page 1 vDeflection` (QC)

3. **Mask selector**
   - `none`
   - `P20 depression mask`
   - `Otsu depression mask`
   - `P30 depression mask`
   - `local/adaptive exploratory mask`

4. **Opacity slider**
   - Blend mask overlay from 0 % to 100 % without altering source arrays.

5. **Line profile tool**
   - Click-drag a line on the 2D map.
   - Optionally modes:
     - horizontal row profile,
     - vertical column profile,
     - arbitrary line profile if supported cleanly by the chosen 2D widget.

6. **Profile plot**
   - Distance in µm on X-axis.
   - Height in nm for Page 5 / Page 4.
   - Optional overlay of the selected auxiliary channel value.
   - No metric computation here.

7. **Optional 3D tab**
   - Embed Plotly via `Qt WebEngine` or use the existing browser-export pattern as a fallback.
   - Marked as secondary to the 2D + profile workflow.

---

## C. Recommended implementation strategy

### Phase order

1. **2D ROI map + channel selector + profile plot**
   - Lowest risk, highest value for QA.
   - Reuses existing BARAKUDA dependencies (PyQt6, pyqtgraph, matplotlib).
2. **Mask overlay + opacity**
   - Add transparent mask image layer on top of the 2D map.
3. **3D surface tab**
   - Optional, added after 2D workflow is stable.
   - Can start with an embedded Plotly WebEngine view or a generated static preview.
4. **Scientific metrics**
   - Explicitly out of scope for the Explorer.
   - Any porosity/pore/roughness computation belongs in `barakuda/devices/afm/methods/hydrogel_porosity.py`, not the viewer.

### Separation of concerns

- Viewer loads arrays from pipeline output locations (or from in-memory cache).
- Viewer never writes source arrays.
- Viewer never computes final metrics.
- Viewer emits QA events only (e.g., selected channel, selected mask, profile coordinates).

---

## D. Proposed files for future implementation

Listed for planning only. **Do not edit in this task.**

- `barakuda/devices/afm/ui/roi_explorer.py` — main explorer widget
- `barakuda/devices/afm/ui/roi_map_view.py` — 2D map + overlay layer
- `barakuda/devices/afm/ui/profile_plot.py` — line-profile matplotlib/pyqtgraph plot
- `barakuda/devices/afm/ui/channel_mask_toolbar.py` — selectors and opacity slider
- `barakuda/devices/afm/ui/surface_3d_tab.py` — optional 3D surface tab
- `barakuda/devices/afm/core/roi_cache.py` — lightweight in-memory ROI/channel cache
- `barakuda/devices/afm/manifest.py` — extend if needed for ROI array discovery

These mirror the structure used in:

- `barakuda/devices/optical_tweezers/ui/panel.py`
- `barakuda/shell/widgets/preview_panel.py`
- `barakuda/devices/acquisition/ui/panel.py`

---

## E. Dependency recommendation

Use existing BARAKUDA dependencies wherever possible.

| Dependency | Already in requirements.txt | Role in ROI Explorer | Recommendation |
|---|---|---|---|
| PyQt6 | yes | main UI framework | required |
| pyqtgraph | yes | 2D image, ROI lines, profiles | required |
| matplotlib | yes | profile plots, static 3D previews | required |
| numpy | yes | array handling | required |
| scipy | yes | interpolation for line profiles | required |
| plotly | no (installed locally only) | interactive 3D | optional / diagnostic-only |
| Qt WebEngine | no (PyQt6-Qt6 may include it) | embed Plotly in Qt | optional / future optional |
| VisPy | no | GPU 3D | future optional |
| PyVista / vtk | no | full 3D mesh rendering | future optional |
| napari | no | multi-dimensional viewer | future optional, likely heavy |

**Decision:** v0 should rely on **PyQt6 + pyqtgraph + matplotlib**. 3D can remain Plotly-in-browser as an auxiliary diagnostic path until embedding is justified.

---

## F. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Qt WebEngine is heavy | installer size, startup time | avoid for v0; use browser fallback |
| Plotly in browser is not deeply integrated | workflow fragmentation | acceptable for diagnostic 3D only |
| Matplotlib 3D is slow and weakly interactive | poor user experience | do not use as primary 3D |
| PyQtGraph does not provide real 3D surface | limits native 3D | defer true 3D to future optional dependency |
| Mask overlays can obscure height detail | bad QA usability | opacity slider + toggle |
| Profile extraction from auxiliary channels may have different units | misleading plot | label axes clearly per channel |
| Touching production AFM pipeline by mistake | scientific regression | keep viewer UI code separate from `methods/` and `core/compute.py` |

---

## G. Next implementation step

Recommended narrow follow-up task:

> **AFM-A1t step 1 — Implement minimal 2D ROI viewer + horizontal/vertical profile tool, no 3D yet.**

Scope of that step:
- Create `barakuda/devices/afm/ui/roi_explorer.py`.
- Add a tab/panel reachable from the AFM pipeline area.
- Load Page 5 and Page 4 aligned ROI arrays.
- Show 2D map with channel selector (Page 5 / Page 4 / adhesion / slope).
- Add horizontal-row and vertical-column profile tools.
- Show profile plot in nm vs µm.
- No mask overlay, no 3D, no metrics.

---

## H. Files inspected for this design note

- `barakuda/devices/afm/device.py` — existing AFM panel (Cellpose/rod-bacteria focused)
- `barakuda/devices/afm/core/compute.py` — compute profile resolution
- `barakuda/devices/optical_tweezers/ui/panel.py` — reference OT UI structure
- `barakuda/shell/widgets/preview_panel.py` — existing preview widget using pyqtgraph
- `barakuda/devices/acquisition/ui/panel.py` — reference live preview + ROI pattern
- `barakuda/shell/main_window.py` — main window layout, device switching, preview stack
- `requirements.txt` — dependency inventory

---

## I. Implementation status

### I.1 AFM-A1t v0 ROI viewer

**Date:** 2026-07-07  
**Commit:** `6473481 afm-ui: add ROI explorer QA viewer`  
**Branch:** `feature/afm-hydrogel-porosity`

AFM ROI Explorer v0 has been implemented, GUI-tested, committed, and pushed.

### I.2 AFM-A1u exploratory mask overlay QA

**Date:** 2026-07-08  
**Commit:** `5debfd5 afm-ui: add exploratory mask overlay QA`  
**Branch:** `feature/afm-hydrogel-porosity`

Exploratory mask overlay controls were added to the v0 viewer.

#### Added controls

- **Mask selector combo box:**
  - None
  - Page 5 / Page 4 P20 depression
  - Page 5 / Page 4 Otsu depression (requires scikit-image)
  - Page 5 / Page 4 P30 depression
  - Page 5 / Page 4 local/adaptive exploratory (requires scikit-image)
- **Opacity slider:** 0–100 %, default 40 %.
- **Warning label:** "Mask overlay is exploratory QA only — no porosity or pore metrics."
- **Status label:** shows selected mask name, source channel, threshold value, and "exploratory only".

#### Behavior

- Masks are generated in memory only from already loaded ROI arrays.
- No masks are saved.
- Mask polarity is depression: `mask = Z <= threshold`.
- Overlay is a transparent red layer aligned with the 2D image.
- The red draggable profile line remains visible above the overlay.
- Channel switching (Page 5 / Page 4) still works while a mask is displayed.

#### User GUI QA passed

- Overlay displays after selecting a mask.
- Opacity slider updates the overlay immediately.
- Draggable horizontal/vertical profile line remains visible and updates the profile plot.
- Page 5 masks work.
- Page 4 masks work.
- Page 5 mask can be overlaid on the Page 4 image.

#### Current limitations

- No saved masks.
- No connected-component labeling.
- No regionprops or object measurements.
- No porosity, pore metrics, or roughness computed.
- No final production channel selected.
- No final segmentation method selected.
- Raw `.jpk-qi-data` loading is not implemented.
- 3D integrated viewer is not implemented.

### I.3 AFM-A1v profile/mask intersection QA

**Date:** 2026-07-08  
**Commit:** `d684a35 afm-ui: add profile mask intersection QA`  
**Branch:** `feature/afm-hydrogel-porosity`

Profile/mask intersection visualization and dynamic profile index ranges were added.

#### Added features

- **Visual profile/mask intersection bands** in the profile plot.
  - Shows where the currently active exploratory mask intersects the active horizontal/vertical profile line.
  - Rendered as semi-transparent red vertical bands behind the yellow profile curve.
  - Bands are QA-only visual markers, not metrics.
- **Dynamic profile index ranges** derived from the active image shape.
  - Horizontal row mode uses `0..n_rows - 1`.
  - Vertical column mode uses `0..n_cols - 1`.
  - No hard-coded ROI dimensions.
  - Index is clamped into the valid range when switching modes or channels.
- **Mask/image shape mismatch safety check** displays a clear QA warning and hides intersection marks if shapes do not match.

#### User GUI QA passed

- Horizontal index full range works (0..299 for current demo ROI).
- Vertical index full range works (0..471 for current demo ROI).
- Draggable vertical line spans full image width.
- Profile mask bands appear for active mask and update when the line is dragged.
- Page 5 / Page 4 channel switching preserves correct index ranges.
- Selecting "None" mask hides the profile mask bands.

#### Current limitations

- No saved masks.
- No connected-component labeling.
- No regionprops or object measurements.
- No porosity, pore metrics, or roughness computed.
- No numerical summaries from mask intersections.
- No final production channel selected.
- No final segmentation method selected.
- Raw `.jpk-qi-data` loading is not implemented.
- 3D integrated viewer is not implemented.

### Implemented files

- `barakuda/devices/afm/ui/roi_explorer.py` — main explorer widget
- `barakuda/devices/afm/ui/__init__.py` — AFM UI package marker
- `scripts/dev_afm_roi_explorer.py` — standalone development launcher

### Current v0 capabilities

- **Validated ROI .npy auto-load** — loads `page5_height_leveled_roi_nm.npy` and `page4_measuredHeight_leveled_roi_nm.npy` from the validated aligned ROI directory relative to repo root.
- **Page 5 / Page 4 channel selector** — switch between calibrated height and nominal measuredHeight channels.
- **2D image display** — pixel-coordinate pyqtgraph `ImageView` with viridis color scale and histogram.
- **Draggable horizontal / vertical cut line** — `pyqtgraph.InfiniteLine` overlay; dragging updates the index spinbox and refreshes the profile.
- **Profile plot in physical units** — distance in µm, height in nm.
- **Exploratory mask overlay** — in-memory depression masks (P20, P30, Otsu, local/adaptive) with opacity slider and warning label.
- **Warning: QA visualization only** — UI labels and module docstring explicitly state that this is a diagnostic viewer.

### User GUI QA passed

- "Load validated demo ROI" auto-loads both channels.
- Horizontal row mode shows a red horizontal cut line.
- Dragging the line updates the row index and profile plot.
- Editing the index spinbox moves the line and updates the profile.
- Vertical column mode switches the line orientation and updates the range correctly.
- Page 5 / Page 4 channel switching works.
- Window resize and maximize behave acceptably with splitter/stretch layout.

### Current limitations

- Raw `.jpk-qi-data` loading is not implemented.
- 3D integrated viewer is not implemented.
- No porosity, pore metrics, or roughness are computed.
- No final production channel is selected by the viewer.

---

## J. Confirmations

- The original AFM-A1t step 0 task was design-only and created this note without implementation.
- AFM-A1t step 1 later implemented the v0 UI viewer in commit `6473481 afm-ui: add ROI explorer QA viewer`.
- The v0 implementation changed UI/QA code only (`barakuda/devices/afm/ui/roi_explorer.py`, `barakuda/devices/afm/ui/__init__.py`, `scripts/dev_afm_roi_explorer.py`).
- No scientific metric computation was added or modified.
- No AFM analysis, segmentation, porosity, pore metrics, or roughness computation was run.
- No final production channel was selected.
