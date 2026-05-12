# Git Hygiene Plan — BARAKUDA CP01

## 1. Purpose

This plan prepares the BARAKUDA repository for safe agent-assisted development during CP01, before any feature coding starts.

## 2. Current repository state

Based on `git status --short`, `git diff --stat`, `git diff --name-only`, `git ls-files`, and `git ls-files --others --exclude-standard`:

- Tracked modified files:
  - none (`git diff --stat` and `git diff --name-only` are empty)
- Untracked documentation/rule files:
  - `docs/agent_tasks/CP01_AGENT_QUEUE.md`
  - `docs/agent_tasks/TASK_TEMPLATE.md`
  - `docs/agent_tasks/REPO_CARTOGRAPHY_REPORT.md`
  - `docs/agent_tasks/GIT_HYGIENE_PLAN.md`
  - `docs/agent_tasks/AGENT_PREP_AUDIT_001.md`
  - `AGENTS.md`
  - `.cursor/rules/00-barakuda-core.mdc`
  - `.cursor/rules/10-cp01-scope.mdc`
  - `.cursor/rules/20-agent-safety.mdc`
  - `.cursor/rules/30-testing-and-git.mdc`
  - `docs/acquisition_raw_external_handoff.md`
- Untracked scripts:
  - `scripts/add_viscosity_angfreq_sheet.py`
  - `scripts/build_thesis_brown_master.py`
  - `scripts/build_thesis_brown_master_v2_clean.py`
  - `scripts/build_thesis_brown_master_v3_results_ready.py`
  - `scripts/build_thesis_methods_master_simple.py`
  - `scripts/process_day06_dls.py`
  - `scripts/update_thesis_brown_inplace_with_day04.py`
- Untracked temporary/generated/debug folders:
  - `.tmp_drag_debug/`
  - `.tmp_drag_debug_after_fix/`
- Deleted files:
  - none reported

## 3. Main risks before coding

- Untracked local files can be accidentally mixed into future feature commits.
- Temporary/generated debug artifacts in `.tmp_*` folders can pollute repository history.
- No `.gitattributes` exists, so cross-platform line-ending behavior is not explicitly controlled.
- Packaging/install metadata is incomplete (`pyproject.toml`, `setup.py`, `setup.cfg` missing).
- `requirements.txt` includes a machine-local dependency path, reducing portability.
- Sensitive scientific and timing/report paths could be edited accidentally without strict task boundaries.
- Large/high-impact shell and pipeline files increase regression risk if touched casually.

## 4. Line-ending and formatting risk

- This is a Windows working environment and the repository has no `.gitattributes`, which creates risk of CRLF/LF drift and formatting-only noise across platforms.
- The hygiene audit context already flagged line-ending normalization as a dedicated future task.
- Do not fix line endings now.

What should be done later (dedicated task only):

1. Add and review `.gitattributes` text/binary policy.
2. Validate line-ending behavior on a clean branch.
3. Normalize only in a dedicated line-ending task, separate from feature work.

## 5. Generated, temporary, cache, and local-only files

Candidate categories to review for `.gitignore` policy later:

- Python cache:
  - `__pycache__/`, `*.pyc` (already covered in `.gitignore`; verify consistency)
- Temporary folders:
  - `.tmp_drag_debug/`
  - `.tmp_drag_debug_after_fix/`
  - optional guard pattern: `.tmp*/`
- Debug outputs:
  - `debug-*.log`
  - `barakuda_crash.log`
  - `*_drag_diagnostic.png`
  - `*_tracking_preview.png`
- Local run outputs:
  - `runs/`
- Local scripts (policy decision: keep tracked or archive elsewhere):
  - new ad-hoc scripts under `scripts/`
- Build artifacts:
  - `build/`, `dist/`, `*.egg-info/` (already in `.gitignore`, re-verify)
- IDE/editor files:
  - `.vscode/` policy should be explicit (currently `.vscode/settings.json` is tracked)

## 6. Packaging and installation gaps

- `pyproject.toml`: not found.
- `setup.py`: not found.
- `setup.cfg`: not found.
- `requirements.txt`: exists and is usable for local installation, but portability is incomplete.
- Portability concern:
  - contains local machine path pin: `packaging @ file:///C:/miniconda3/...`
- Dependency consistency concern:
  - mix of strict pins and unpinned entries (`AFMReader`, `matplotlib-scalebar`, `uncertainties`).
- For future launcher split (Acquisition/Analysis), packaging can be clean later, but requires a dedicated packaging task with explicit metadata and entry-point strategy.

## 7. Suggested .gitignore improvements

Do later; do not edit now.

- Add explicit ignores for observed temp/debug folders:
  - `.tmp_drag_debug/`
  - `.tmp_drag_debug_after_fix/`
  - optional `.tmp*/`
- Consider explicit policy for local ad-hoc script outputs and temporary artifacts.
- Clarify `.vscode/` policy (fully ignored vs selected shared settings).
- Keep existing Python/cache/build ignores; verify no gaps during dedicated hygiene branch work.

## 8. Suggested .gitattributes improvements

Do later; do not edit now.

- Add baseline normalization policy:
  - `* text=auto eol=lf`
- Add binary protections:
  - `*.png binary`
  - `*.jpg binary`
  - `*.jpeg binary`
  - `*.gif binary`
  - `*.ico binary`
  - `*.pdf binary`
- Optional Windows script policy:
  - `*.bat text eol=crlf`
  - `*.ps1 text eol=crlf`

## 9. Safe branch strategy for CP01

- `cp01-agent-prep`:
  - documentation/rules/task-governance setup only.
- `cp01-git-hygiene`:
  - `.gitignore` and `.gitattributes` policy, untracked/temp cleanup decisions, no feature logic.
- `cp01-acquisition-analysis-split`:
  - planning and minimal launcher split scaffolding only after hygiene baseline is stable.
- `cp01-timing-audit`:
  - timing truth/effective FPS/timestamps audit only, isolated from unrelated refactors.
- `cp01-batch-summary-hardening`:
  - batch summary/report consistency hardening only.
- `cp01-v1-release-candidate`:
  - integration and stabilization branch after CP01 scoped branches are validated.

Branch usage rule: one branch = one narrow goal, with no mixed hygiene + feature + scientific changes.

## 10. Files agents should not touch casually

Require explicit permission before editing:

- Scientific logic:
  - `barakuda/core/ot_physics.py`
  - `barakuda/devices/optical_tweezers/drag/physics.py`
  - `barakuda/devices/afm/core/compute.py`
- Timing logic:
  - `barakuda/core/run_protocol.py`
  - `barakuda/core/truth_resolvers.py`
  - `barakuda/core/run_manager.py`
  - timing-sensitive acquisition motion files in `barakuda/devices/acquisition/motion/`
- Report generation and summaries:
  - `barakuda/core/ot_report.py`
  - `barakuda/core/afm_report.py`
  - `barakuda/core/export_xlsx.py`
  - `barakuda/shell/batch_controller.py`
- Acquisition control:
  - `barakuda/devices/acquisition/device.py`
  - `barakuda/devices/acquisition/camera*.py`
  - `barakuda/devices/acquisition/motion/ximc_stage.py`
- Large/high-impact UI files:
  - `barakuda/shell/main_window.py`
  - `barakuda/devices/optical_tweezers/ui/panel.py`
  - `barakuda/devices/acquisition/ui/panel.py`

## 11. Minimal safe cleanup order

1. Commit or save current documentation-only preparation state.
2. Create dedicated branch for git hygiene (`cp01-git-hygiene`).
3. Add or verify `.gitattributes`.
4. Add or verify `.gitignore`.
5. Normalize line endings only in a dedicated task.
6. Review untracked temporary/generated folders.
7. Fix `requirements.txt` portability only in a dedicated task.
8. Add `pyproject.toml` only in a later packaging task.
9. Run tests.
10. Only then start Acquisition / Analysis split planning.

## 12. Acceptance checklist

- [x] Report created or updated.
- [x] No application code edited.
- [x] No Python files edited.
- [x] No files deleted.
- [x] No git commands changed repository state.
- [x] Cleanup actions are proposed but not implemented.
- [x] Next safe task is clearly recommended.

## 13. Recommended next task

**create Acquisition / Analysis split plan**

Reason: both Git Hygiene Plan and agent rules (`AGENTS.md` + `.cursor/rules/*.mdc`) are already present, so the next safe CP01 preparation step is to define `docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN.md` before any implementation work.
