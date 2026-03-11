## 1. PURPOSE

This document is the final merge-review audit for the `integration/ot-run-output-consolidation` branch. It evaluates whether the branch is ready for safe human-reviewed merge preparation around the OT RUN Output Consolidation work, and this step does **not** merge anything.

## 2. BRANCH SUMMARY

- Current branch name: `integration/ot-run-output-consolidation`
- Branch goal: make `RUN` the primary Optical Tweezers output workflow by exposing `Output Root` for fresh non-dataset runs, preserving the legacy default root when unchanged, moving Preview Gate reporting to the launched batch root, and removing the visible OT Export tab.
- Intended merge path: human-reviewed merge directly into `main`; no additional integration branch is identified by the current task.

## 3. COMMIT CHAIN

- `728b5de` - `fix: honor selected output root for new ot batch runs` - adds OT `Output Root` UI/state handoff and routes fresh non-dataset batch output under the selected root while keeping the legacy default when unchanged.
- `cabf3e4` - `fix: store ot preview gate report at batch root` - writes the non-dataset Preview Gate report once at the launched OT batch root instead of duplicating it into each run preview folder.
- `35d032f` - `fix: remove ot export tab from primary ui workflow` - removes the visible OT Export tab and deletes direct main-window wiring that previously refreshed that visible tab.
- `7ebc457` - `docs: add ot run output consolidation verification report` - records the integration verification audit confirming the current branch behavior and the remaining manual verification scope.

## 4. VERIFIED FUNCTIONAL CHANGES

- OT Run UI now exposes an `Output Root` control with browse support for fresh non-dataset OT runs.
- Fresh non-dataset OT runs now honor the selected `Output Root`.
- The default `Output Root` still preserves the legacy non-dataset behavior by resolving to `runs/ot`.
- The Preview Gate report is now stored once at the launched batch root for fresh non-dataset OT runs.
- Fresh non-dataset item/run folders no longer receive duplicated Preview Gate report copies.
- The OT Export tab is no longer visible in the OT tab set.
- `Run`, `Tracking`, `Postprocess`, and `Settings` remain as the visible OT tabs.
- Dataset-mode OT behavior remains on the existing dataset path and was not changed by the runtime commits on this branch.

## 5. REMAINING RISKS

- Output Root persistence across app restarts - LOW - Current code forwards the live panel value into a run, but broader persistence across restarts was not identified or manually verified.
- remaining hidden Export backend code - LOW - Hidden Export helpers still exist in the OT panel code, but the visible tab and direct visible-tab refresh wiring were removed.
- dataset-mode future Output Root decisions - LOW - Dataset-mode intentionally remains unchanged on this branch, so any future decision about applying `Output Root` to dataset-mode is deferred rather than blocking this merge review.
- old assumptions elsewhere about fixed OT root - MEDIUM - Non-dataset OT runs can now launch from a selected root, so any external tooling that assumed a fixed `runs/ot` location may need targeted human verification.
- batch root Preview Gate behavior - LOW - Code now guards for a single non-dataset batch-root copy, but final confidence still depends on manual post-merge runtime verification.
- current OT workflow compatibility - LOW - The branch-level code review and verification report found no confirmed runtime blocker, but final readiness still depends on targeted human UI/run smoke checks.

No confirmed code blocker was identified in the current branch state.

## 6. MERGE READINESS

READY FOR MERGE REVIEW

The branch is ready for merge review because the intended runtime changes are present as a small, coherent commit chain, the follow-up verification report found no required runtime patch before review, runtime code was not modified after that verification step, and the remaining concerns are verification-oriented risks rather than confirmed code blockers.

## 7. RECOMMENDED MERGE PROCEDURE

1. Verify `main` and `integration/ot-run-output-consolidation` both have clean working trees before starting the human review/merge process.
2. Optionally record the current `main` state by noting the HEAD SHA or creating a lightweight tag before the merge review.
3. Review the branch commit chain and the two docs reports, then merge `integration/ot-run-output-consolidation` into `main` using the normal human-reviewed merge flow.
4. Do not squash away traceability unless that is already the repository’s standard review practice.
5. After the merge completes, run the targeted post-merge manual verification listed below on `main`.
6. Do not auto-merge in this step; this document only prepares the branch for human-reviewed merge handling.

## 8. POST-MERGE VERIFY CHECKLIST

1. Launch the app from merged `main` and open the Optical Tweezers UI.
2. Confirm the `Output Root` control is visible in the OT `Run` tab.
3. Execute one fresh non-dataset OT run with the default `Output Root` and verify output lands in the legacy default location under `runs/ot`.
4. Execute one fresh non-dataset OT run with a changed `Output Root` and verify output lands under the selected location.
5. Confirm the internal run layout remains correct for those fresh non-dataset runs.
6. Confirm `preview_report.json` appears exactly once at the launched non-dataset batch root.
7. Confirm fresh non-dataset item/run folders do not contain duplicated `preview_report.json` copies.
8. Confirm the OT Export tab is absent and the visible OT tabs remain `Run`, `Tracking`, `Postprocess`, and `Settings`.
9. Execute one dataset-mode OT run and confirm dataset-mode behavior remains as before.
10. Confirm there is no obvious OT workflow regression during startup, OT navigation, Preview Gate, Run, Tracking, Postprocess, and Settings usage.
