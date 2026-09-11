## 1. PURPOSE

This document records an integration verification audit of the current `integration/ot-run-output-consolidation` branch before any further runtime changes. The audit is limited to the current branch state and checks whether Optical Tweezers now uses `RUN` as the primary output workflow, adds `Output Root` for fresh non-dataset runs, writes the Preview Gate report at the launched batch root, and removes the visible OT Export tab without changing dataset-mode behavior.

## 2. COMMITS REVIEWED

- `728b5de` - Output Root UI/state addition in the OT Run UI and worker handoff (`barakuda/devices/optical_tweezers/ui/panel.py`, `barakuda/shell/main_window.py`, `barakuda/shell/workers/ot_run_worker.py`).
- `728b5de` - non-dataset Output Root routing now uses the selected root for fresh OT batch runs (`barakuda/shell/batch_controller.py`).
- `cabf3e4` - Preview Gate report move to the launched batch root for fresh non-dataset OT runs (`barakuda/shell/batch_controller.py`).
- `35d032f` - Export tab removal from the visible OT UI and removal of direct main-window Export-tab refresh wiring (`barakuda/devices/optical_tweezers/ui/panel.py`, `barakuda/shell/main_window.py`).

## 3. TARGET CHECKLIST

| Item | Mark | Basis |
| --- | --- | --- |
| OT Run UI shows Output Root control | PASS | The OT Run tab now creates and renders an `Output Root` field with a browse button. |
| Output Root defaults to the legacy OT root behavior | PASS | The default is `runs/ot`, which matches the prior non-dataset OT batch root. |
| fresh non-dataset OT run with default Output Root still lands in the old default location | PASS | Non-dataset batches still resolve to `runs/ot/<batch_id>` when the default value is left unchanged. |
| fresh non-dataset OT run with changed Output Root lands under the selected directory | PASS | Batch creation now uses the selected `Output Root` when a non-empty directory path is provided. |
| fresh non-dataset OT run keeps the expected internal layout | PARTIAL | Routing changes only move the batch root; the prior per-item/per-run writer flow remains in place, but this audit did not execute a fresh run end to end. |
| Preview Gate report is written once at the launched batch root for fresh non-dataset runs | PASS | The copy logic now writes `preview_report.json` once to the non-dataset batch root and guards against repeat copies. |
| fresh non-dataset item/run folders do not receive duplicated Preview Gate reports | PASS | Non-dataset runs skip the per-run `preview/preview_report.json` copy path after the batch-root write path is selected. |
| dataset-mode OT runs still behave exactly as before | PARTIAL | Dataset-mode still routes writes into the detected dataset item root and keeps the existing dataset branch, but this step did not execute a dataset-mode regression run. |
| OT Export tab is no longer visible | PASS | The OT panel no longer adds the Export tab to the visible tab widget. |
| Run, Tracking, Postprocess, and Settings tabs still work | PARTIAL | Those four tabs are still added to the OT tab widget, but this audit did not drive the live UI. |
| app startup and OT navigation do not fail because of removed Export tab wiring | PARTIAL | Direct main-window Export-tab update hooks were removed consistently, but this audit did not perform a live startup/navigation smoke test. |

## 4. CURRENT VERIFIED BEHAVIOR

- `Output Root` is now an explicit control on the OT Run tab. Its default value is the legacy non-dataset OT root, `runs/ot`, and the selected value is forwarded through the UI-to-worker path into batch execution.
- For fresh non-dataset OT runs, batch output routing now starts from the selected `Output Root`. With the default unchanged, the batch still lands under the old location; with a different directory selected, the batch root moves under that directory while the existing per-item/per-run writer flow is otherwise preserved.
- The Preview Gate report for fresh non-dataset OT runs is now copied once to the launched batch root as `<selected_or_default_output_root>/<batch_id>/preview_report.json` instead of being copied into each item/run preview folder.
- The OT Export tab is no longer visible because it is no longer added to the OT tab widget, and the direct `main_window` calls that previously refreshed visible Export-tab state were removed.
- Dataset-mode remains on the existing dataset branch: when the input resolves to a dataset item root, writes still target that dataset item and the manifest read path still tolerates both `preview_report.json` and `preview/preview_report.json`.

## 5. REMAINING GAPS

- NOT VERIFIED - Fresh non-dataset runtime execution was not performed in this step, so the updated branch behavior was verified by code integration review rather than by a launched OT run.
- NOT VERIFIED - Dataset-mode regression behavior was not exercised end to end in this step, even though the dataset branch remains intact in current code.
- POSSIBLE - Hidden OT Export support code still exists inside `barakuda/devices/optical_tweezers/ui/panel.py` even though the Export tab is no longer visible, so there may still be dead or future-cleanup-only backend/UI remnants.
- POSSIBLE - `Output Root` does not appear to persist beyond the live panel/session in current code; this branch forwards the value into a run, but no broader persistence mechanism was identified in this audit.

## 6. EXACT NEXT SAFE STEP

no runtime patch needed; branch is ready for merge review

## 7. VERIFY PLAN

1. Launch the app on `integration/ot-run-output-consolidation` and open the Optical Tweezers panel.
2. Confirm the visible OT tabs are exactly `Run`, `Tracking`, `Postprocess`, and `Settings`, and confirm there is no visible `Export` tab.
3. In `Run`, confirm the `Output Root` control is present and initially points to the legacy OT root.
4. Execute one fresh non-dataset OT run without changing `Output Root`; verify the batch lands in the legacy default location and that the batch root contains a single `preview_report.json`.
5. Confirm the non-dataset item/run folders created by that run do not contain duplicated `preview_report.json` copies.
6. Execute one fresh non-dataset OT run with a different `Output Root`; verify the batch lands under the selected directory, keeps the expected internal item/run layout, and again writes a single batch-root `preview_report.json`.
7. Execute one dataset-mode OT run from an existing dataset item and confirm writes still remain inside the dataset item structure as before.
8. During the above checks, confirm app startup, OT panel opening, tab switching, Preview Gate, Run, Tracking, Postprocess, and Settings flows do not fail after the Export-tab removal.
