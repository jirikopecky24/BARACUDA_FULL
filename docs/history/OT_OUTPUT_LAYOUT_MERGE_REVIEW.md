# OT Output Layout — Merge Review

## 1. PURPOSE

This document is the **final merge-review audit** for the BARAKUDA OT output layout simplification branch (`integration/ot-output-layout-simplification`). It summarizes the branch goal, commit chain, verified functional changes, remaining risks, merge readiness, and recommended merge procedure for a human reviewer. **This step does NOT merge anything** — it only adds this report. The actual merge into `main` is to be done by a human after review.

---

## 2. BRANCH SUMMARY

| Item | Value |
|------|--------|
| **Current branch name** | `integration/ot-output-layout-simplification` |
| **Branch goal** | Simplify OT analysis output layout: move new pipeline artifacts to `pipeline/`, result summaries to `summary/`, QC image to `qc/`; keep manifest backward compatibility with `ot_v2_shadow/` and legacy root-level files. |
| **Merge target** | Intended to merge directly into `main` after human review. (If your process uses an integration branch first, merge there then to `main`.) |

---

## 3. COMMIT CHAIN

Relevant commits (oldest to newest along the branch):

| Short SHA | Commit message | Purpose |
|-----------|----------------|---------|
| `c3db219` | fix: resolve preview report from preview directory | Preview report manifest resolution: resolve from `preview/preview_report.json`. |
| `ac90bae` | fix: support pipeline and ot_v2_shadow in ot manifest | Manifest supports both `pipeline/` and `ot_v2_shadow/` for qc/trajectory and related paths. |
| `2e65ea4` | fix: write new ot pipeline artifacts under pipeline directory | Non-dataset OT runs write pipeline artifacts to `run_dir/pipeline/` instead of `ot_v2_shadow/`. |
| `5d242b8` | fix: write dataset-mode ot pipeline artifacts under pipeline directory | Dataset-mode OT runs also write pipeline artifacts to `run_dir/pipeline/` (unified path). |
| `5f107f4` | fix: write new ot result summaries under structured summary directory | New `*_results.csv` and `*_results.xlsx` write to `run_dir/summary/` instead of analysis root. |
| `22de3ca` | fix: write new ot qc image under structured qc directory | New `*_qc.png` writes to `run_dir/qc/` instead of analysis root. |
| `797184f` | docs: verify current ot output layout after cleanup steps | Layout verification report: fresh-run snapshot, checklist, remaining root-level outputs, next-step recommendation. |

Additional docs/audit commits on the branch (e.g. `af6d7fa`, `44e1b6b`, `0ba5a2f`) support the above changes but are not listed in full here.

---

## 4. VERIFIED FUNCTIONAL CHANGES

Concrete functional changes now present on the branch:

- **Preview report** — Can resolve from `preview/preview_report.json` (manifest and batch copy into run’s `preview/`).
- **Manifest compatibility** — Manifest supports both `pipeline/` and `ot_v2_shadow/` for qc JSON, trajectory, and related resolution; old datasets keep working.
- **New pipeline writes** — New OT runs write pipeline artifacts under `pipeline/` (dataset and non-dataset).
- **No new ot_v2_shadow** — New runs do not create a fresh `ot_v2_shadow/` directory.
- **Result summaries** — New OT result summaries (`*_results.csv`, `*_results.xlsx`) go under `summary/`.
- **QC image** — New OT QC image (`*_qc.png`) goes under `qc/`.
- **Root-level files** — Fresh OT runs leave only `run.json` in the analysis root (plus subdirs: `preview/`, `pipeline/`, `tracking/`, `audit/`, `physics/`, `summary/`, `qc/`).
- **Old datasets** — Old datasets with `ot_v2_shadow/` (or root-level result/qc files) remain readable via manifest fallbacks; full manual regression (load and use an old dataset) is recommended post-merge but is not a code blocker.

---

## 5. REMAINING RISKS

| Risk | Level |
|------|--------|
| OT manifest backward compatibility (old paths still resolved) | **LOW** — Manifest explicitly checks `ot_v2_shadow/` and root fallbacks; risk is limited to untested legacy layouts. |
| Dataset-mode vs non-dataset-mode consistency | **NONE** — Both modes use the same `pipeline/`, `summary/`, `qc/` layout under their respective run roots. |
| Root-level `run.json` remaining in analysis root | **NONE** — Intentional; single canonical root file. |
| Old dataset compatibility | **LOW** — Design preserves fallbacks; recommend one manual test with an old `ot_v2_shadow/` dataset after merge. |
| Need for later `qc/` manifest enhancement (e.g. resolve QC PNG from manifest) | **LOW** — Only if UI/export needs to resolve the QC image by path; current manifest focuses on `*_qc.json` in `pipeline/`. |
| Future cleanup of legacy datasets (no migration in this branch) | **LOW** — Known; migration can be a separate, optional follow-up. |

**No confirmed code blocker** for merge from a layout/behavior perspective.

---

## 6. MERGE READINESS

**READY FOR MERGE REVIEW**

Reasons:

- All stated layout goals are implemented: new writes go to `pipeline/`, `summary/`, and `qc/`; no new `ot_v2_shadow/`; only `run.json` remains in the analysis root for new runs.
- Manifest backward compatibility is in place for `ot_v2_shadow/` and legacy paths.
- Verification document (`OT_OUTPUT_LAYOUT_VERIFICATION.md`) confirms layout and recommends no further runtime patch before merge.
- Remaining risks are LOW or NONE; no mandatory code change is required before a human-reviewed merge.

---

## 7. RECOMMENDED MERGE PROCEDURE

Perform these steps as a **human developer**; do not automate the merge in this audit step.

1. **Verify working tree**  
   On your machine, ensure the working tree is clean and you are on the target branch (e.g. `main`):  
   `git status`  
   `git branch --show-current`

2. **Optional: tag or note current main**  
   To be able to revert or compare:  
   `git tag pre-ot-layout-merge`  
   or note the current `main` commit SHA.

3. **Merge with review**  
   From `main`:  
   `git checkout main`  
   `git pull origin main`  
   `git merge integration/ot-output-layout-simplification`  
   Resolve any conflicts if they appear; complete the merge (e.g. `git commit` after conflict resolution).

4. **Post-merge verification**  
   Run the checks in Section 8 below.

5. **Do not auto-merge in this step**  
   This document does not perform the merge; a human must run the merge after review.

---

## 8. POST-MERGE VERIFY CHECKLIST

After merging `integration/ot-output-layout-simplification` into `main`, run these checks:

- [ ] **Fresh OT dataset-mode run** — Run a full OT analysis in dataset mode on a real dataset; confirm run completes and outputs are under the expected subdirs.
- [ ] **Fresh non-dataset OT run** — Run OT on a standalone video (non-dataset); confirm outputs under `module/ot/pipeline/`, `module/ot/summary/`, `module/ot/qc/` and no new `ot_v2_shadow/`.
- [ ] **Preview report** — Confirm preview report resolves from the preview directory (e.g. `preview/preview_report.json` in the run).
- [ ] **Pipeline artifacts** — Confirm new run writes pipeline artifacts under `pipeline/` (e.g. `*_qc.json`, `*_trajectory.csv`, `*_ot_summary.json`).
- [ ] **No ot_v2_shadow** — Confirm the new run does not create `ot_v2_shadow/`.
- [ ] **Result summaries** — Confirm `*_results.csv` and `*_results.xlsx` are under `summary/`.
- [ ] **QC image** — Confirm `*_qc.png` is under `qc/`.
- [ ] **Old dataset** — If available, open an old dataset that still uses `ot_v2_shadow/` (or root-level result/qc files) and confirm it still loads and behaves correctly.
- [ ] **No OT workflow regression** — Quick smoke test: load dataset, run analysis, open results/export; no obvious breakage.

Document any failure; fix or revert as needed before considering the merge complete.
