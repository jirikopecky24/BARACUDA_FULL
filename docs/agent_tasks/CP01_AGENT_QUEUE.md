# CP01 Agent Queue — BARAKUDA v1 Preparation

## Metadata

- Project: BARAKUDA
- Checkpoint: CP01 — BARAKUDA v1 laboratory deployment and PhD Talent acceleration
- Queue purpose: safe agent-assisted development preparation
- Last updated: 2026-05-12
- Current phase: agent preparation and repository control

## Governance Note

Do not create a new document for every small task. Related updates should be appended to the existing relevant document unless the user explicitly requests a new file.

## Current active goal

Prepare BARAKUDA for safe agent-assisted development during CP01.

The current goal is not to add new scientific features.

The current goal is to make the repository understandable, controlled, installable and safe for later work on:

1. BARAKUDA Acquisition
2. BARAKUDA Analysis
3. timing audit
4. batch summary hardening
5. v1 laboratory deployment

---

## Golden rule

One agent task = one narrow job.

No agent is allowed to rewrite the whole application.

No agent is allowed to mix refactoring, bug fixing, UI redesign and scientific logic changes in one task.

---

## Task 001 — Repository cartography

Status: completed

Dependency: none

Goal:

Create a map of the current BARAKUDA repository.

Allowed action:

Read files and write one report.

Forbidden action:

Do not edit application code.

Expected output:

docs/agent_tasks/REPO_CARTOGRAPHY_REPORT.md

Acceptance checklist:
- [x] Output file exists.
- [x] Task stayed within allowed scope.
- [x] No application code was changed.
- [x] Result is useful for the next CP01 step.

---

## Task 002 — Git hygiene plan

Status: completed

Dependency: Task 001

Goal:

Identify repository hygiene issues before feature work.

Allowed action:

Read git status, inspect project files, write one report.

Forbidden action:

Do not normalize line endings yet.
Do not delete files yet.
Do not edit application code.

Expected output:

docs/agent_tasks/GIT_HYGIENE_PLAN.md

Acceptance checklist:
- [x] Output file exists.
- [x] Task stayed within allowed scope.
- [x] No application code was changed.
- [x] Result is useful for the next CP01 step.

---

## Task 003 — Agent rules setup

Status: completed

Dependency: Task 001 and Task 002 (if available)

Goal:

Create stable rules for Cursor agents.

Expected output:

AGENTS.md
.cursor/rules/00-barakuda-core.mdc
.cursor/rules/10-cp01-scope.mdc
.cursor/rules/20-agent-safety.mdc
.cursor/rules/30-testing-and-git.mdc

Acceptance checklist:
- [x] Output files exist.
- [x] Task stayed within allowed scope.
- [x] No application code was changed.
- [x] Result is useful for the next CP01 step.

---

## Task 004 — Acquisition / Analysis split plan

Status: not started

Dependency: Task 001, Task 002, and Task 003

Goal:

Plan the minimal safe split into BARAKUDA Acquisition and BARAKUDA Analysis.

Forbidden action:

Do not implement yet.

Expected output:

docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN.md

Acceptance checklist:
- [ ] Output file exists.
- [ ] Task stayed within allowed scope.
- [ ] No application code was changed.
- [ ] Result is useful for the next CP01 step.

---

## Task 005 — Startup helper seam

Status: completed

Goal:
Extract duplicated startup logic from main.py and barakuda/main.py into a shared helper without behavior change.

Output:
- barakuda/startup.py
- updated main.py
- updated barakuda/main.py
- docs/agent_tasks/STARTUP_CONSTRUCTOR_SEAM_REPORT.md
- docs/agent_tasks/STARTUP_CONSTRUCTOR_SEAM_REPORT_AUDIT_001.md
- docs/agent_tasks/STARTUP_HELPER_IMPLEMENTATION_AUDIT_001.md

Acceptance:
- [x] Shared startup helper created.
- [x] main.py delegates to shared helper.
- [x] barakuda/main.py delegates to shared helper.
- [x] ShellMainWindow untouched.
- [x] registry/list_devices untouched.
- [x] scientific/timing/report/batch/hardware logic untouched.
- [x] implementation audited.
- [x] no behavior change intended.

Validation status:
- Compile validation passed using explicit Anaconda BARAKUDA interpreter.
- Import validation passed using explicit Anaconda BARAKUDA interpreter.
- Generic shell commands python/py/python3 are still not available from PATH, but direct interpreter path works.

---

---

## Task 006 — Optional app_mode seam

Status: completed

Dependency: Task 005

Goal:
Add an optional app_mode startup path with default current behavior unchanged.

Acceptance:
- [x] barakuda/startup.py accepts app_mode with default "full".
- [x] ShellMainWindow accepts app_mode with default "full".
- [x] app_mode is stored as self._app_mode but not used for filtering yet.
- [x] main.py behavior remains unchanged.
- [x] barakuda/main.py behavior remains unchanged.
- [x] no registry/list_devices changes.
- [x] no scientific/timing/report/batch/hardware changes.
- [x] compile validation passed.
- [x] import validation passed.

Validation status:
- Compile validation passed using explicit Anaconda BARAKUDA interpreter.
- Import validation passed using explicit Anaconda BARAKUDA interpreter.
- "mode seam imports ok" printed.

---

---

## Task 007 — Acquisition / Analysis launcher stubs

Status: completed

Dependency: Task 006

Goal:
Add two tiny root launcher files that call the shared startup helper with app_mode values.

Output:
- main_acquisition.py
- main_analysis.py

Acceptance:
- [x] main_acquisition.py exists.
- [x] main_analysis.py exists.
- [x] main_acquisition.py calls run_app(app_mode="acquisition").
- [x] main_analysis.py calls run_app(app_mode="analysis").
- [x] both preserve raise SystemExit(main()) behavior.
- [x] no filtering added.
- [x] no existing Python files edited.
- [x] no registry/list_devices changes.
- [x] no scientific/timing/report/batch/hardware changes.
- [x] compile validation passed.
- [x] import validation passed.

Validation status:
- Compile validation passed using explicit Anaconda BARAKUDA interpreter.
- Import validation passed using explicit Anaconda BARAKUDA interpreter.
- "launchers import ok" printed.

---

---

## Task 008 — app_mode device filtering

Status: completed

Dependency: Task 007

Goal:
Filter visible devices by app_mode using a minimal ShellMainWindow composition-boundary filter.

Output:
- updated barakuda/shell/main_window.py

Acceptance:
- [x] _apply_mode_device_filter exists.
- [x] app_mode="full" preserves all devices.
- [x] app_mode="acquisition" keeps only acquisition device.
- [x] app_mode="analysis" excludes acquisition device.
- [x] registry/list_devices unchanged.
- [x] DeviceSpec unchanged.
- [x] device modules unchanged.
- [x] no scientific/timing/report/batch/hardware logic touched.
- [x] compile validation passed.
- [x] import validation passed.
- [x] headless filter test passed.
- [x] launcher import validation passed.

Validation status:
- Compile: exit 0 (pass).
- ShellMainWindow import: "ShellMainWindow import ok" (pass).
- Headless filter assertions: "filter logic ok" (pass) — all three modes verified.
- Launcher import: "launchers still ok" (pass).
- Note: headless test required PowerShell here-string (@"..."@) syntax because def cannot appear in a semicolon-chained -c one-liner.

---

---

## Task 009 — startup/mode smoke tests

Status: completed

Dependency: Task 008

Goal:
Add test coverage for app_mode device filtering and launcher import contracts.

Output:
- tests/test_startup_modes.py

Acceptance:
- [x] test file exists.
- [x] full mode filter behavior tested.
- [x] acquisition mode filter behavior tested.
- [x] analysis mode filter behavior tested.
- [x] unknown mode fallback behavior tested.
- [x] launcher import safety tested.
- [x] no QApplication created.
- [x] no GUI launched.
- [x] no hardware required.
- [x] compile validation passed.
- [x] pytest passed.

Validation status:
- Compile: exit 0 (pass).
- pytest tests/test_startup_modes.py -q: 12 passed, 0 failed, 6 warnings in 4.02s.
- Warnings are pre-existing SWIG DeprecationWarning from hardware imports — unrelated to these tests.

---

---

## Task 010 — manual GUI sanity check

Status: completed

Dependency: Task 009

Goal:
Manually verify that full, acquisition, and analysis launch modes open successfully and show the expected device scope.

Acceptance:
- [x] main.py launches full BARAKUDA mode.
- [x] full mode shows the complete available device set.
- [x] main_acquisition.py launches BARAKUDA Acquisition solo mode.
- [x] main_analysis.py launches BARAKUDA Analysis solo mode.
- [x] no startup crashes observed.
- [x] no visible startup errors observed.

Validation status:
Manual GUI sanity check passed.
User confirmed that main/full mode contains everything, and acquisition and analysis work as solo applications.

---

---

## CP01 Status Checkpoint — 2026-05-12

### Current validated state

- BARAKUDA full mode works through `main.py`.
- BARAKUDA Acquisition solo mode works through `main_acquisition.py`.
- BARAKUDA Analysis solo mode works through `main_analysis.py`.
- Shared startup helper exists in `barakuda/startup.py`.
- `app_mode` seam exists in `run_app()` and `ShellMainWindow.__init__`.
- Device filtering by `app_mode` exists in `ShellMainWindow` via `_apply_mode_device_filter`.
- Startup/mode smoke tests pass (12/12, hardware-free).
- Manual GUI sanity check passed by user.
- No scientific/timing/report/batch/hardware logic was changed during the split work.

### Validated outputs

| File | Role |
|---|---|
| `barakuda/startup.py` | Shared startup helper with `app_mode` seam |
| `main_acquisition.py` | BARAKUDA Acquisition solo launcher |
| `main_analysis.py` | BARAKUDA Analysis solo launcher |
| `barakuda/shell/main_window.py` | `app_mode` device filter added |
| `tests/test_startup_modes.py` | Headless smoke tests for filter and launcher imports |

### Next branch decision options

1. **Git hygiene / checkpoint**
   Stabilize current work, inspect git status, decide what to commit, avoid mixing validated split work with future changes.

2. **Packaging / entry points**
   Make the three modes easier to launch and eventually package.

3. **Timing audit**
   Verify effective FPS, `timestamps.csv` status, timing truth, and timing-related reports.

4. **Batch summary hardening**
   Strengthen batch outputs, summary tables, and report consistency.

### Recommended next branch

**Git hygiene / checkpoint.**

Reason: the Acquisition / Analysis split is now functionally validated end-to-end. Before adding more behavior, the repository state should be stabilized so future tasks do not mix validated split work with packaging, timing, or batch changes.

---

## Git Hygiene Checkpoint — 2026-05-12

### Purpose

Inspect repository state after the validated Acquisition / Analysis startup split (Tasks 005–010) and identify a clean commit boundary before the next CP01 branch begins.

---

### Git status summary

**Tracked files with unstaged modifications (` M`):** 3 files.
These are files that git already tracks and have been changed since the last commit.

**Untracked files (`??`):** 29 items (files and directories).
These have never been committed. They include new CP01 implementation files, agent governance docs, analysis/planning docs, temporary debug folders, and external scripts.

No staged changes. Nothing is currently queued for commit. The working tree is entirely unstaged.

---

### Change classification

#### A — Validated split implementation (tracked, modified)

These are existing tracked files modified as part of the startup split:

| File | Git status | What changed |
|---|---|---|
| `main.py` | ` M` (modified) | Replaced inline startup with `run_app()` delegate |
| `barakuda/main.py` | ` M` (modified) | Same — replaced inline startup with `run_app()` delegate |
| `barakuda/shell/main_window.py` | ` M` (modified) | Added `_apply_mode_device_filter`, `app_mode` parameter, `self._app_mode`, one filter call |

Diff summary: 3 files changed, 19 insertions, 15 deletions. All changes are confirmed correct and validated.

#### B — Validated split implementation (untracked, new files)

New files that are part of the completed split work:

| File | Role |
|---|---|
| `barakuda/startup.py` | Shared startup helper |
| `main_acquisition.py` | BARAKUDA Acquisition solo launcher |
| `main_analysis.py` | BARAKUDA Analysis solo launcher |
| `tests/test_startup_modes.py` | Smoke tests (12/12 pass) |

#### C — Agent governance and CP01 documentation (untracked, new files)

| File / Folder | Notes |
|---|---|
| `AGENTS.md` | Agent rules for this repository |
| `.cursor/rules/00-barakuda-core.mdc` | Core rules |
| `.cursor/rules/10-cp01-scope.mdc` | CP01 scope rules |
| `.cursor/rules/20-agent-safety.mdc` | Safety rules |
| `.cursor/rules/30-testing-and-git.mdc` | Testing and git rules |
| `docs/agent_tasks/CP01_AGENT_QUEUE.md` | Task queue (this file) |
| `docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN.md` | Split plan |
| `docs/agent_tasks/STARTUP_CONSTRUCTOR_SEAM_REPORT.md` | Seam report |
| `docs/agent_tasks/GIT_HYGIENE_PLAN.md` | Git hygiene plan |
| `docs/agent_tasks/REPO_CARTOGRAPHY_REPORT.md` | Repository map |
| `docs/agent_tasks/TASK_TEMPLATE.md` | Task template |
| `docs/agent_tasks/STARTUP_HELPER_IMPLEMENTATION_AUDIT_001.md` | Startup helper audit |
| `docs/agent_tasks/STARTUP_HELPER_ENV_VALIDATION_001.md` | Env validation report |
| `docs/agent_tasks/STARTUP_CONSTRUCTOR_SEAM_REPORT_AUDIT_001.md` | Seam report audit |
| `docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN_AUDIT_001.md` | Split plan audit |
| `docs/agent_tasks/AGENT_PREP_AUDIT_001.md` | Agent prep audit |
| `docs/agent_tasks/ANTIGRAVITY_ENV_CHECK_001.md` | Environment check report |
| `docs/acquisition_raw_external_handoff.md` | External acquisition handoff note |

#### D — Temporary / debug / local files (untracked — do NOT commit)

| File / Folder | Why |
|---|---|
| `.tmp_drag_debug/` | Temporary debug output folder |
| `.tmp_drag_debug_after_fix/` | Temporary debug output folder |
| `scripts/add_viscosity_angfreq_sheet.py` | One-off analysis script |
| `scripts/build_thesis_brown_master.py` | One-off thesis script |
| `scripts/build_thesis_brown_master_v2_clean.py` | One-off thesis script |
| `scripts/build_thesis_brown_master_v3_results_ready.py` | One-off thesis script |
| `scripts/build_thesis_methods_master_simple.py` | One-off thesis script |
| `scripts/process_day06_dls.py` | One-off data processing script |
| `scripts/update_thesis_brown_inplace_with_day04.py` | One-off thesis script |

#### E — Unexpected application code changes

None found. All tracked modifications are confirmed split implementation changes. No scientific, timing, report, batch, or hardware files were modified.

---

### Recommended commit boundary

**Two commits** in the following order:

**Commit 1 — Agent governance and CP01 preparation:**
```
cp01: add agent governance rules and CP01 preparation docs
```
Files to include:
- `AGENTS.md`
- `.cursor/rules/00-barakuda-core.mdc`
- `.cursor/rules/10-cp01-scope.mdc`
- `.cursor/rules/20-agent-safety.mdc`
- `.cursor/rules/30-testing-and-git.mdc`
- `docs/agent_tasks/CP01_AGENT_QUEUE.md`
- `docs/agent_tasks/GIT_HYGIENE_PLAN.md`
- `docs/agent_tasks/REPO_CARTOGRAPHY_REPORT.md`
- `docs/agent_tasks/TASK_TEMPLATE.md`
- `docs/agent_tasks/AGENT_PREP_AUDIT_001.md`
- `docs/agent_tasks/ANTIGRAVITY_ENV_CHECK_001.md`

**Commit 2 — Acquisition / Analysis startup split:**
```
cp01: add acquisition and analysis launch modes with app_mode device filtering
```
Files to include:
- `main.py` (modified — startup delegate)
- `barakuda/main.py` (modified — startup delegate)
- `barakuda/startup.py` (new — shared helper)
- `barakuda/shell/main_window.py` (modified — filter + app_mode)
- `main_acquisition.py` (new — acquisition launcher)
- `main_analysis.py` (new — analysis launcher)
- `tests/test_startup_modes.py` (new — smoke tests)
- `docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN.md`
- `docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN_AUDIT_001.md`
- `docs/agent_tasks/STARTUP_CONSTRUCTOR_SEAM_REPORT.md`
- `docs/agent_tasks/STARTUP_CONSTRUCTOR_SEAM_REPORT_AUDIT_001.md`
- `docs/agent_tasks/STARTUP_HELPER_IMPLEMENTATION_AUDIT_001.md`
- `docs/agent_tasks/STARTUP_HELPER_ENV_VALIDATION_001.md`

**Optional separate commit 3 — External / handoff notes (if desired):**
```
docs: add acquisition raw external handoff note
```
File: `docs/acquisition_raw_external_handoff.md`

---

### Do not commit yet

| Item | Reason |
|---|---|
| `.tmp_drag_debug/` | Temporary debug output — should be added to `.gitignore` |
| `.tmp_drag_debug_after_fix/` | Temporary debug output — should be added to `.gitignore` |
| `scripts/*.py` (all) | One-off local analysis scripts — review whether they belong in the repository before committing; if yes, a separate `scripts:` commit is appropriate |

---

### .gitignore / .gitattributes recommendation

**Do not change `.gitignore` or `.gitattributes` in this task.**

Recommended future hygiene task: add `.tmp_*` and `scripts/` (or specific script names) to `.gitignore` to prevent accidental future staging. This is a small, safe, separate task that should be done before the next feature branch.

---

### Recommended next action

**User reviews git status and stages selected files manually.**

Reason: the commit boundary is clear, but staging involves selecting specific files from a mixed untracked list. Manual staging avoids accidentally including temporary debug folders or unreviewed scripts. The user should run `git add` only for the files listed in Commit 1 and Commit 2 above, then commit each group separately.

Redundant one-off audit/environment documents were removed after their conclusions were consolidated into the CP01 queue, split plan, and seam report.

---

## Next recommended task

Perform Git hygiene / checkpoint review for the validated Acquisition / Analysis split work.

