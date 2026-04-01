# BARAKUDA Truth Model Migration Note

This note summarizes the post-migration source-of-truth behavior for timing, bead, drag, QC semantics, and scale.

## 1) Timing truth

- Primary source is per-frame timestamps sidecar (`*_timestamps.csv` or `video_timestamps.csv` when explicitly resolved).
- Derived truth fields are:
  - `frame_count`
  - `t_first_s`
  - `t_last_s`
  - `elapsed_time_s`
  - `effective_fps`
  - `timing_source`
  - `timing_source_detail`
  - `timestamp_validation_pass`
  - `timestamp_validation_message`
- If timestamps are missing or invalid, BARAKUDA switches to explicit estimated timing mode (no silent primary fallback).

## 2) Bead truth

- Bead parameters are resolved centrally via run-level provenance.
- Physics paths no longer accept silent bead fallback for missing/invalid bead size.
- Bead provenance fields are exported and report-visible:
  - `bead_diameter_um`
  - `bead_radius_um`
  - `bead_source`
  - fallback/warning state

## 3) Drag truth

- Primary drag report/export source is `*_drag_summary.json`.
- Legacy `*_drag.json` / `*_compare.json` is fallback-only and explicitly marked.
- Report/XLSX provenance now exposes:
  - `report_source_kind`
  - `report_source_path`

## 4) Dropped vs tracking-lost semantics

- Metrics are separated:
  - `camera_dropped_frames` (acquisition write path / camera pipeline)
  - `tracking_lost_frames` (postprocess/tracking QC)
  - `lost_fraction` (tracking QC fraction)
- Reports and exports must not alias camera drops to tracking loss.

## 5) Scale truth

- Scale is resolved centrally per run.
- Export/report-visible scale provenance:
  - `um_per_px` (resolved value)
  - `scale_source`
  - scale warning when unavailable/invalid

## 6) What changed vs previous behavior

- Timestamp-derived timing is now preferred end-to-end where available.
- Legacy `fi/fps` time axis is fallback-only (not silent primary truth).
- Drag report loading now prioritizes modern summary artifacts.
- QC semantics for dropped frames vs lost tracking are explicit and separated.

## 7) What users should expect in UI/report/export

- Timing displays now identify whether values are timestamp-derived or estimated.
- Missing or invalid bead/scale inputs are surfaced as provenance or warning states.
- Drag reports expose their source kind/path and show legacy fallback explicitly.
