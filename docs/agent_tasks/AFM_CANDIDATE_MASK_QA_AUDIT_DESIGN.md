# AFM Candidate Mask QA Audit — Design Note

**Task:** AFM-A1w — Design candidate mask QA audit for the BARAKUDA AFM ROI Explorer  
**Date:** 2026-07-08  
**Branch:** `feature/afm-hydrogel-porosity`  
**Status:** design/specification only — no implementation, no production code changes, no UI buttons, no JSON output, no metrics  

**WARNING:** This document describes a future *exploratory QA audit* for the AFM ROI Explorer. It is not a scientific result, not a final segmentation, and not a porosity or pore-metric analysis. The audit may record viewer state and threshold parameters; it must not record mask-derived metrics.

---

## 1. Purpose

The future candidate mask QA audit is a lightweight provenance/state recorder for the BARAKUDA AFM ROI Explorer.

Its only purpose is to capture *what the user was looking at* while visually comparing exploratory depression masks against AFM height maps and line profiles. It preserves enough context that a later human reviewer can reproduce the viewer configuration and understand which candidate mask, channel, threshold method, and profile cut were under inspection.

It explicitly does **not**:

- produce a scientific result,
- select a final segmentation,
- select a final production channel,
- compute porosity,
- compute pore metrics,
- compute roughness,
- count or characterize objects.

---

## 2. Current viewer capabilities

As of AFM-A1v, the ROI Explorer supports the following state that the future QA audit may draw from:

- **Validated ROI `.npy` auto-load** — loads `page5_height_leveled_roi_nm.npy` and `page4_measuredHeight_leveled_roi_nm.npy` from the validated aligned ROI directory.
- **Page 5 / Page 4 channel selector** — switches between calibrated height and nominal measuredHeight channels.
- **Draggable horizontal/vertical profile line** — a `pyqtgraph.InfiniteLine` overlay that updates the profile plot and the profile index spinbox.
- **Exploratory in-memory masks:**
  - P20 percentile depression mask,
  - Otsu depression mask (requires scikit-image),
  - P30 percentile depression mask,
  - local/adaptive exploratory mask (requires scikit-image),
  - sourced from either Page 5 or Page 4.
- **Opacity slider** — 0 % to 100 %, default ~40 %, controls overlay transparency without modifying source arrays.
- **Profile/mask intersection bands** — visual red bands in the profile plot showing where the active exploratory mask intersects the current profile line; QA-only markers, not metrics.
- **Dynamic profile index ranges** — derived from the active image shape:
  - horizontal row mode: `0 .. n_rows - 1`,
  - vertical column mode: `0 .. n_cols - 1`.

---

## 3. Non-goals / forbidden outputs

The QA audit design, and any future implementation of it, must explicitly forbid the following:

- pore count,
- area fraction,
- porosity,
- pore density,
- object area,
- object size,
- equivalent diameter,
- connected-component labeling,
- `regionprops` or any object measurement,
- roughness (`Sa`, `Sq`, `Ssk`, `Sku`, `Sp`, `Sv`, `Sz`, `Ra`, `Rq`, etc.),
- final channel selection,
- final mask/segmentation selection,
- any bulk hydrogel claim.

---

## 4. What the future QA audit may record

The future audit may record only non-metric provenance and viewer-state fields. Permitted examples include:

- `timestamp` — ISO-8601 creation time of the audit record.
- `barakuda_version` / `git_commit` — version and commit hash if available.
- `source_mode` — e.g. `validated_demo_roi` or `manual_roi_arrays`.
- `displayed_channel` — e.g. `page5_height_calibrated` or `page4_measuredHeight_nominal`.
- `displayed_array_shape` — shape of the active ROI array, e.g. `[300, 472]`.
- `pixel_size_um_per_px` — lateral pixel size in µm/px if known; `null` if unknown, with a warning.
- `profile_mode` — `horizontal_row` or `vertical_column`.
- `profile_index` — current row or column index of the profile line.
- `selected_mask_name` — e.g. `none`, `page5_p20_depression`, `page4_otsu_depression`.
- `selected_mask_source_channel` — the channel from which the mask was generated, if a mask is selected.
- `mask_threshold_method` — e.g. `P20`, `P30`, `Otsu`, `local_adaptive`, or `none`.
- `mask_threshold_value` and `threshold_value_unit` — the threshold value and unit of the *source height channel* (e.g. `nm`). This is a method parameter, not a measurement of detected objects.
- `mask_opacity` — overlay opacity percentage.
- `profile_intersection_visualization_enabled` — whether the profile/mask intersection bands were visible.
- `warnings` — list of UI warnings shown to the user, e.g. missing scale, shape mismatch, mask unavailable.
- `scientific_status` — fixed string `exploratory_visual_QA_only`.

The threshold value is allowed because it is a *parameter of the candidate method* applied to the height channel, not a derived summary of segmented objects.

---

## 5. What the future QA audit must not record

The future audit must not record any numerical summary derived from the binary mask or its connected components. Forbidden fields include, but are not limited to:

- number of `True` pixels,
- mask fraction,
- total masked area,
- number of mask intervals along the profile line,
- interval lengths along the profile line,
- pore count,
- component count,
- object table,
- region properties,
- accepted/rejected object lists,
- any metric computed by `skimage.measure.regionprops`, `scipy.ndimage.label`, or similar.

If a future user asks for any of these, the response must be a new, separately approved scientific task, not an extension of this QA audit.

---

## 6. Proposed future JSON schema

The following schema is a minimal *future* design. It records viewer state, provenance, threshold parameters, and explicit non-scientific warnings. It deliberately omits all mask-derived metrics.

```json
{
  "schema_version": 1,
  "schema_name": "afm_roi_explorer_candidate_mask_qa_audit",
  "created_at": "2026-07-08T09:16:32+02:00",
  "scientific_status": "exploratory_visual_QA_only",
  "warnings": [
    "This file records viewer state only.",
    "It is not a final segmentation.",
    "It is not a porosity or pore-metric analysis.",
    "Do not use it as a scientific result."
  ],
  "barakuda": {
    "version": "...",
    "git_commit": "..."
  },
  "source": {
    "mode": "validated_demo_roi",
    "roi_arrays": [
      "page5_height_leveled_roi_nm.npy",
      "page4_measuredHeight_leveled_roi_nm.npy"
    ]
  },
  "display": {
    "channel": "page5_height_calibrated",
    "array_shape": [300, 472],
    "pixel_size_um_per_px": 0.01953125,
    "pixel_size_known": true
  },
  "profile": {
    "mode": "horizontal_row",
    "index": 150,
    "intersection_visualization_enabled": true
  },
  "mask": {
    "selected": "page5_p20_depression",
    "source_channel": "page5_height_calibrated",
    "threshold_method": "P20",
    "threshold_value": -23.5,
    "threshold_value_unit": "nm",
    "opacity_percent": 40,
    "polarity": "depression"
  },
  "ui_state": {
    "window_title": "BARAKUDA AFM ROI Explorer",
    "last_user_action": "mask_selection_changed"
  }
}
```

Key rules for this schema:

- `scientific_status` must always be `exploratory_visual_QA_only`.
- `warnings` must explicitly state that the file is not final segmentation and not porosity/pore-metric analysis.
- `threshold_value` and `threshold_value_unit` are method parameters, not results.
- No field may contain counts, fractions, areas, densities, diameters, perimeters, or any other mask-derived measurement.

---

## 7. Proposed future UI behavior

This section is design only. No UI code is added now.

- **Possible button name:** `Save QA audit...`
- **Behavior:**
  - The button must require the user to choose an output location in any future implementation.
  - No automatic writing, no auto-save on every viewer change.
  - The saved artifact must be a single JSON file containing only the allowed viewer-state fields.
  - The audit must *not* save the binary mask array itself.
- **Optional future screenshot:** A separate `Save QA snapshot...` action may save a PNG screenshot of the current viewer. This must be clearly labeled as a *visual QA snapshot*, separate from the JSON audit, and also non-scientific.
- Both actions must display a confirmation or warning dialog restating the exploratory nature of the output.

---

## 8. Relationship to QA snapshot/export

Two distinct artifacts are anticipated:

1. **QA audit JSON** — machine-readable viewer state and provenance. It contains channel, mask method, threshold parameter, profile configuration, opacity, and warnings. It contains no images and no mask-derived metrics.
2. **QA snapshot image** — a PNG screenshot of the viewer at a moment in time, intended for human visual review. It is a picture, not a data table or measurement.

Both remain exploratory and non-scientific unless later promoted by a separately approved workflow. Neither replaces a final segmentation audit, a pore table, a summary JSON, or a scientific report.

---

## 9. Validation plan for future implementation

When AFM-A1x or a follow-up task implements this audit, the following tests should be applied:

- No files are written unless the user explicitly triggers `Save QA audit...` and confirms the location.
- The JSON contains only allowed fields from Section 4.
- The JSON contains no mask counts, fractions, areas, densities, diameters, perimeters, or object tables.
- No connected-component labeling, `regionprops`, or equivalent measurement code is called during audit generation.
- Switching channel, mask, profile mode, profile index, or opacity updates the in-memory state that would be recorded.
- Missing array shape or unknown pixel size produces a warning in the `warnings` list rather than a silent default.
- The output JSON contains `scientific_status: "exploratory_visual_QA_only"` and explicit non-scientific warnings.
- The optional snapshot action, if implemented, is separate from the JSON audit and clearly labeled.

---

## 10. Next recommended task

The narrow follow-up to this design note is:

> **AFM-A1x — Implement QA audit JSON save for viewer state only, still no metrics.**

Scope of AFM-A1x:

- Add a `Save QA audit...` action to the ROI Explorer.
- Write a JSON file matching the schema in Section 6.
- Record only viewer state and threshold parameters.
- Continue to forbid mask-derived metrics, porosity, pore metrics, roughness, connected-component labeling, and `regionprops`.

Alternative follow-up (still documentation/spec only):

> **QA snapshot/export design — still no scientific outputs.**

This alternative would design the optional PNG screenshot workflow before any implementation.

Either next step requires explicit user approval.

---

## Confirmations

- AFM-A1w is design/specification only.
- No production code was changed.
- No UI buttons were added.
- No JSON outputs were written.
- No metrics were computed.
- No porosity, pore metrics, or roughness were computed.
- No connected-component labeling or `regionprops` was used.
- No final production channel or final segmentation method was selected.
- The audit may record viewer state and threshold method/value.
- The audit must not record mask-derived metrics.
