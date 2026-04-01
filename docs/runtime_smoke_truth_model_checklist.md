# Runtime Smoke Test Checklist (Truth Model)

Run on one Brownian dataset and one Drag dataset after deployment.

## Brownian run

- [ ] Open dataset and run analysis to completion.
- [ ] Confirm bead provenance is visible (`bead_diameter_um`, `bead_radius_um`, `bead_source`).
- [ ] Confirm timing truth fields exist in run/report metadata:
  - `frame_count`, `elapsed_time_s`, `effective_fps`, `timing_source`, validation fields.
- [ ] Confirm scale and temperature are present and consistent in UI/report/export.
- [ ] Cross-check `fc`, `kappa`, `eta`, `D` between JSON, PDF, XLSX, and UI summary.
- [ ] Verify no silent fallback warning is hidden for bead/scale/timing.

## Drag run

- [ ] Open dataset and run drag analysis to completion.
- [ ] Confirm timestamp validation fields are present and pass (or explicit fallback warning exists).
- [ ] Confirm drag source precedence:
  - `report_source_kind=drag_summary` when `*_drag_summary.json` exists.
- [ ] Confirm `report_source_path` points to actual source file.
- [ ] Confirm stage timing consistency (`motion_start/stop`, alignment fields) across outputs.
- [ ] Confirm QC separation:
  - `camera_dropped_frames` vs `tracking_lost_frames` vs `lost_fraction`.
- [ ] Confirm JSON, PDF, XLSX, and UI summary show consistent drag truth values.

## Export collision guard

- [ ] Export two artifacts with same basename from different relative paths.
- [ ] Confirm no silent overwrite happened.
- [ ] Confirm collision-safe renamed output exists (`__dupXX`) when needed.
