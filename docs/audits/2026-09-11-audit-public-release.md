# BARAKUDA — Audit: Current State vs. Public, Installable Release

**Date:** 2026-09-11
**Type:** One-time technical snapshot / audit. Not a living document — do not append dated
updates here the way `AGENT_BARAKUDA_WORKFLOW_NOTE.md` or `CP01_AGENT_QUEUE.md` are updated.
If a later audit is needed, write a new dated file in `docs/audits/`.
**Scope:** Read-only analysis. No application code was changed to produce this report.
**Relationship to existing docs:** This file does not duplicate `ARCHITECTURE.md` (sections 2,
6, 7, 8 are the authoritative architecture reference — this audit links to them instead of
re-describing them) or `docs/agent_tasks/REPO_CARTOGRAPHY_REPORT.md` (repo map) or
`docs/agent_tasks/CP01_AGENT_QUEUE.md` / `ACQUISITION_ANALYSIS_SPLIT_PLAN.md` /
`STARTUP_CONSTRUCTOR_SEAM_REPORT.md` (history of the Acquisition/Analysis split). Where those
documents already answer a question, this audit cites them rather than re-deriving the answer.

**Branch note:** this analysis was produced on `feature/afm-hydrogel-porosity`, which is an
unrelated AFM feature branch. Per `AGENT_BARAKUDA_WORKFLOW_NOTE.md` §2 (`main` = frozen
baseline, no new feature work committed directly on it) and the one-task-one-branch rule in
`AGENTS.md`, this document should be committed on its own branch — suggested name
`docs/public-release-audit` (or `chore/public-release-audit`), branched from
`staging/barakuda-next` — not on `feature/afm-hydrogel-porosity` and not on `main`.

---

## 1. Repository structure and main modules

Four layers, entry points down to core, as already documented in `ARCHITECTURE.md` §2:

```
main.py / main_acquisition.py / main_analysis.py   (entry points, each 6-8 lines)
  → barakuda/startup.py: run_app(app_mode="full"|"acquisition"|"analysis")
       → barakuda/shell/                             (GUI + orchestration)
            → barakuda/devices/{optical_tweezers,afm,acquisition}/  (per-device domain logic)
                 → barakuda/core/                     (shared physics, IO, reporting)
```

- **Entry points** (`main.py`, `main_acquisition.py`, `main_analysis.py`) — each just calls
  `barakuda.startup.run_app(app_mode=...)`. `barakuda/main.py` also exists and is identical to
  root `main.py` (`from barakuda.startup import run_app; run_app()`) — a second, redundant
  entry point left over from before the startup-helper seam (`docs/agent_tasks/
  STARTUP_CONSTRUCTOR_SEAM_REPORT.md` §3, §11).
- **Shell** (`barakuda/shell/`, 5 top-level files + `widgets/` + `workers/`) — `main_window.py`
  (1941 lines) and `batch_controller.py` (3161 lines) are the two largest non-report files in
  the repo. Full breakdown in §5 below.
- **Devices** (`barakuda/devices/`) — `registry.py` (23 lines) and `base.py` (23 lines,
  `DeviceSpec` frozen dataclass with `device_id`, `display_name`, `create_panel`). Three
  device packages: `optical_tweezers/` (largest, 5 subdomains — see §3), `afm/`, `acquisition/`.
- **Core** (`barakuda/core/`, 19 files) — `ot_report.py` is the single largest file in the
  entire repo at **5859 lines**. Physics/IO/reporting modules already catalogued in
  `ARCHITECTURE.md` §6.

Total Python source: **40,741 lines** across `barakuda/` (`find barakuda -name "*.py" | xargs wc -l`).

Largest files repo-wide, for scale:

| File | Lines |
|---|---|
| `barakuda/core/ot_report.py` | 5859 |
| `barakuda/shell/batch_controller.py` | 3161 |
| `barakuda/devices/acquisition/ui/panel.py` | 2853 |
| `barakuda/devices/optical_tweezers/ui/panel.py` | 1981 |
| `barakuda/devices/optical_tweezers/drag/analysis.py` | 1965 |
| `barakuda/shell/main_window.py` | 1941 |
| `barakuda/devices/acquisition/camera.py` | 1164 |

No `pyproject.toml`, `setup.py`, `setup.cfg`, `environment.yml`, `Dockerfile`, or CI config
exist (`docs/agent_tasks/REPO_CARTOGRAPHY_REPORT.md` §7 already noted this; confirmed still
true — see §4 and §7 below for the packaging-implications detail).

---

## 2. The "two applications" — what they actually are today

**Finding: there are not two applications. There is one shared GUI process (`ShellMainWindow`)
with a startup-time device-list filter.** This matters directly for the "keep two separate
apps if it makes sense" question in the brief — the current implementation is much closer to
"one app, two launch shortcuts" than to two independent programs.

Mechanically (`barakuda/shell/main_window.py`):
- `run_app(app_mode=...)` constructs exactly one `ShellMainWindow(app_mode=app_mode)` — same
  class, same process, same window, regardless of which of the three `main_*.py` files was run.
- A module-level helper `_apply_mode_device_filter(devices, app_mode)` filters the device
  dropdown after `list_devices()` runs: `app_mode="acquisition"` keeps only the Acquisition
  device; `app_mode="analysis"` excludes it; `app_mode="full"` (the plain `main.py` default)
  shows all three (OT, AFM, Acquisition, if importable). This is confirmed in
  `docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN.md` (device-filtering update, and its own
  "Code facts" section) and in the shell audit performed for this report.
- All device panels, workers, the dataset panel, preview panel, log panel, and
  `BatchController` are constructed identically regardless of `app_mode` — only which entries
  appear in the device combo box changes. `self._app_mode` is read in exactly one place
  (the filter call).
- Both "apps" therefore share 100% of the process, 100% of `barakuda/core/`, and 100% of the
  shell code (`ShellMainWindow`, `BatchController`, all widgets/workers). The only Acquisition-
  specific UI accommodation inside the shared shell is that `_activate_device()` hides the
  dataset dock and shared preview stack when the acquisition device is active (confirmed in the
  shell audit, `main_window.py:700-724`).

How they communicate/share data in practice: not via any runtime IPC — they share data purely
through the filesystem contract described in `ARCHITECTURE.md` §7.2/§7.4. Acquisition writes
video + `video_meta.json` + `*_timestamps.csv` into `items/<item_id>/acquisition/`; Analysis
(OT/AFM) reads that same directory tree as its input. There is no in-process or on-disk
"handoff" file beyond that directory structure and `item.json`/`batch.json` manifests
(`ARCHITECTURE.md` §7.2). This is a clean, already-correct separation of concerns at the data
level — it is only the process/UI level that is not actually split.

One layering consequence of the shared-process design: `barakuda/devices/acquisition/ui/
panel.py:64-66` imports `barakuda.shell.widgets.run_protocol_dialog`,
`barakuda.shell.stage_service`, and `barakuda.shell.stage_console_window` — a device-layer
module reaching up into the shell layer, which `ARCHITECTURE.md` §2/§12 already flags as one of
the two known dependency-direction violations in the repo. This import exists because the
motorized XIMC stage is single-connection, process-wide shared hardware: `StageService`
(`barakuda/shell/stage_service.py:40-47`) is a process-wide lease arbiter between the
Acquisition panel and the separate `StageConsoleWindow` diagnostics window, and no device-layer
equivalent of that arbiter currently exists. It is a real violation of the documented layer
rule, but a load-bearing one, not incidental sloppiness — any real two-process split would need
to either move `StageService` down into a shared layer both processes can reach, or make stage
control genuinely single-owner per process.

---

## 3. What's done, what's in progress, what's dead

### Optical Tweezers (`barakuda/devices/optical_tweezers/`) — most mature module

- **`pipeline/` vs `pipelines/` — confirmed dead code.** `barakuda/devices/optical_tweezers/
  pipelines/` (4 files: `drift_correction.py`, `postprocess_ot3.py`, `qc_flags.py`,
  `tracking.py`) has **zero importers anywhere in the repository**, tests included
  (`grep -rln "optical_tweezers\.pipelines\b" . --include=*.py` returns nothing). The live code
  path is exclusively `barakuda/devices/optical_tweezers/pipeline/` (singular — `auto_roi.py`,
  `derived_newtonian.py`, `orchestrator.py`, `preprocess.py`, `qc.py`, `tracking.py`), imported
  from `drag/pipeline.py:13`, `strategies/psd_procfft.py:12`, `strategies/psd_welch.py:14`,
  `shell/batch_controller.py:308,1294`, and `shell/main_window.py:916`. `pipelines/` (plural)
  is a leftover from an earlier refactor and is safe to remove — a genuinely trivial, low-risk
  cleanup (one directory, zero call sites to update).
- **Brownian/PSD analysis** — production path: `strategies/psd_welch.py`, `psd_lorentzian.py`,
  `psd_procfft.py`, `drag_constant_velocity.py`, `time_resampling.py`, backed by
  `core/ot_physics.py` (`ARCHITECTURE.md` §6.1). This is the module `AGENT_BARAKUDA_WORKFLOW_NOTE.md`
  and `.cursor/rules/ot-baseline-and-forward-design.mdc` both treat as the canonical, stable
  reference implementation for the whole app ("OT in its current form is the ideal default and
  canonical model for BARAKUDA").
- **`drag/` subsystem** (12 files + 3 subpackages) — the newer, actively-hardened half of OT.
  `analysis.py` (1965 lines) implements the two-gate validation model already documented in
  `ARCHITECTURE.md` §8.5 (`physics_primary_gate` + `detection_qc_gate` → `final_drag_verdict`).
  Also present: `physics.py`, `pipeline.py` (591 lines), `io.py` (760 lines), `alignment.py`,
  `windows.py`, `schema.py`, `export.py`, `calibration_import.py`, `plotting.py`,
  `cli_debug.py` (an intentional debug CLI, not stray debug code). This subsystem has the
  heaviest test investment in the repo: 8 dedicated files (`tests/test_drag_anchor_mode_plumbing.py`,
  `test_drag_artifact_discovery.py`, `test_drag_output_routing.py`, `test_drag_own_tracking_workflow.py`,
  `test_drag_physics_validation_gate.py`, `test_drag_preflight_workflow.py`,
  `test_drag_stage_truth_verification.py`, `test_drag_windowing_stage_markers.py`) plus
  `test_offline_drag_reprocess_workflow.py`.
  - `drag/active_umbrella/` (runner.py, trajectory_helpers.py, protocols/oscillatory.py 523
    lines, protocols/step_response.py) — substantial working code, not a stub, but two
    "placeholder" comments mark unfinished forward-looking work specifically:
    `oscillatory.py:103` ("Rheology target placeholder (for future G'/G'')") and `:355`
    ("Complex response placeholder; future mapping can convert to compliance/modulus") — i.e.
    the active-umbrella oscillatory protocol runs and produces data today, but complex-modulus
    (G′/G″) reporting from it is explicitly future work, not yet wired.
  - `drag/viscoelastic/models.py` (99 lines) — working Kelvin-Voigt model code; one docstring
    at line 90 calls the exponential creep-compliance form a "placeholder," meaning the
    functional form is a simplified stand-in pending a more general model, not that the file is
    non-functional.
- **`strategies/piezo_oscillation.py` (22 lines) — a genuine, confirmed stub.** Its class
  docstring says "Piezo oscillation calibration strategy (stub for future implementation)" and
  its one method body is `raise NotImplementedError("Piezo oscillation calibration coming
  soon")` (line 22). This is the only file under `optical_tweezers/` that is an unambiguous,
  fully-non-functional stub.
- `strategies/`, `export/` (`discovery.py`, `exporter.py`), `audit/` (`schema.py`), `profile/`
  (`profile_store.py`), `ui/` (`panel.py` 1981 lines, `batch_tools.py` 542 lines) round out the
  module. `device.py` registers `DeviceSpec(device_id="optical_tweezers",
  display_name="Optical Tweezers", create_panel=lambda: PipelinePanel())`.

**Net assessment:** OT Brownian/PSD analysis is production-grade and is explicitly the design
reference for the rest of the app. The drag/active-microrheology subsystem is newer but is the
most heavily-tested part of the entire codebase and is not experimental in the "half-written"
sense — it has real validation gates, real tests, and only two forward-looking placeholders
(G′/G″ reporting, a more general viscoelastic model) that don't block current operation. The
only true dead/stub code in OT is `pipelines/` (dead directory) and `piezo_oscillation.py`
(stub, and already UI-gated as unavailable — see AFM parallel below).

### AFM (`barakuda/devices/afm/`) — one working method, one confirmed stub, no tests

- **`methods/rod_bacteria.py`** (106 lines) — the only production AFM method, explicitly
  labelled "the default and currently only production method" (comment, line 14). Wraps
  `core/afm_v2_pipeline.py` (324 lines, "Cellpose-only segmentation + rod geometry filter").
  Full pipeline works end-to-end: `.spm` → `io/afmreader_loader.py` (AFMReader-based, no
  fallback path — scale is only ever taken from the Scan Size header, never borrowed from
  OT/camera scale) → `core/afm_v2_pipeline.py` → `core/afm_report.py` → PDF/XLSX.
- **`methods/hydrogel_porosity.py`** (36 lines) — **confirmed a hard stub, not partial code.**
  `DISPLAY_NAME = "Hydrogel Porosity (coming soon)"`; `compute()` body is exactly
  `raise NotImplementedError("Hydrogel Porosity method is not yet implemented.")`;
  `get_default_params()` returns `{}`. The method selector in `device.py:38` already lists it
  as `("Hydrogel Porosity (coming soon)", "hydrogel_porosity", False)` — the trailing `False`
  disables it in the dropdown, so a user cannot even select it today. This matches
  `AGENT_BARAKUDA_WORKFLOW_NOTE.md`'s framing: the current work on this branch
  (`feature/afm-hydrogel-porosity`) is explicitly scoped to the ROI Explorer QA/visualization
  layer only (`barakuda/devices/afm/ui/roi_explorer.py`, 752 lines) — "no segmentation, no
  porosity, no pore metrics, no roughness, no final channel selection" (workflow note §0).
- **Zero dedicated AFM tests exist.** No `tests/test_afm_*.py` file of any kind; the only
  AFM-adjacent test hit is a generic startup-mode smoke test
  (`tests/test_startup_modes.py`), not AFM logic. Contrast with Acquisition/motion, which has
  5 dedicated test files, and drag, which has 8.
- **Two known, unfixed UI bugs**, both documented in `AGENT_BARAKUDA_WORKFLOW_NOTE.md` §10 and
  independently confirmed in this audit:
  - **AFM batch progress bar sticks at 79%.** Root cause: `main_window.py:1839-1846`'s
    `_afm_run_on_timer()` smoothing timer is hard-capped (`if 20 <= val < 79: val += 1` — it
    literally cannot advance past 79 on its own), and the only thing that can push it past 79
    is a real `progress_pct` signal ≥80 from the worker. But `BatchController.run_afm_batch`
    only calls `progress_fn` twice per file — once at batch start and once at file completion
    (`batch_controller.py:2577, 3064-3065`) — with nothing during the (slow) Cellpose inference
    itself. For a single-file run, or the first files of a batch, the timer runs unopposed for
    the entire inference and visibly freezes at 79% until the file finishes, even though the
    backend is actively working (log lines keep appearing).
  - **AFM panel visual inconsistency with OT.** The specific historical cause named in the
    workflow note (`_make_card()` leaking a `QFrame {...}` CSS selector onto child widgets) no
    longer exists in the codebase — no `_make_card` symbol and no leaking `QFrame {` selector
    were found anywhere in `barakuda/`. The residual inconsistency is now a plain
    styling-approach mismatch (AFM's `device.py` uses ad-hoc per-widget `setStyleSheet()` calls,
    same pattern as OT but with a different, uncoordinated color/weight palette) rather than an
    active CSS-leak bug — see §5 for the styling system finding that explains why.

**Net assessment:** AFM has exactly one working method end-to-end, with real report/export
output, but the module as a whole is materially behind OT — second method is a hard stub and
UI-disabled, zero dedicated tests, one confirmed live progress-bar bug, and a documented
(if now partially resolved) visual-consistency gap against the OT reference design.

### Acquisition (`barakuda/devices/acquisition/`) — mature, hardware-focused, largest single UI file

- Camera stack: `camera.py` (1164 lines, Basler/pypylon, optional dependency),
  `camera_base.py` (interface), `camera_factory.py`, `webcam_camera.py` (OpenCV fallback,
  optional cv2 dependency).
- Motion stack (`motion/`): `motion_run.py` (797 lines, "Synchronized Record + Motion
  orchestration," deterministic 12-step flow), `ximc_stage.py` (533 lines, Standa XIMC/XILab,
  Windows-targeted), `stage_base.py` (explicitly states "Motion physics and drag analysis are
  never the concern of this layer" — a clean boundary statement), `metric_conversion.py`,
  `stage_scale_audit.py`, `trace.py`, `recipes.py` (currently only one recipe:
  `constant_velocity_drag`).
- `ui/panel.py` — **2853 lines, the single largest UI file in the entire repository**, larger
  than OT's panel (1981) and nearly triple AFM's `device.py` (833).
- Test coverage is real: 5 dedicated files (`test_acquisition_motion_semantics.py`,
  `test_acquisition_motion_thread_safety_audit.py`, `test_acquisition_motion_ui_scaffold.py`,
  `test_stage_scale_audit.py`, `test_stage_scan_lifecycle_guard.py`) plus cross-cutting
  drag/stage tests.

**Net assessment:** functionally mature and reasonably tested, but its UI file size (2853
lines in one panel class) is the most extreme concentration-of-responsibility finding in the
whole GUI layer — see §5. One naming/labeling rough edge for a public release:
`device.py:10` hardcodes `DeviceSpec(display_name="Acquisition (Basler)", ...)` — even though
the camera stack gracefully falls back to a plain USB webcam via OpenCV when `pypylon`/Basler
hardware isn't present (confirmed above), the UI always brands the device as brand-specific
lab hardware, which will read as wrong or confusing to a non-lab user running the app on a
laptop with just a webcam.

### Committed but functionally dead/legacy code found repo-wide

- `barakuda/devices/optical_tweezers/pipelines/` — dead directory (§3 above).
- `barakuda/devices/afm/io/brucker_spm.py` (124 lines, a raw Bruker-header/CIAO-block regex
  parser) — confirmed orphaned: `grep -rn "brucker_spm" barakuda --include=*.py` returns zero
  hits outside the file itself. It is not imported by `afmreader_loader.py` (the file actually
  wired into the production `.spm` load path, §3) or anywhere else. Either a superseded first
  attempt at SPM parsing before the AFMReader dependency was adopted, or an early exploration
  never wired in — safe to remove, or worth a one-line comment explaining why it's kept if
  there's a reason to keep it around (e.g. as a fallback reference for a future format).
- **OT Export tab is still fully live despite being marked for removal.** `AGENT_BARAKUDA_WORKFLOW_NOTE.md`
  §4 states plainly: "Export is no longer the intended primary output model" and "OT Export
  UI/workflow is being phased out / removed." In the actual code, the Export tab in
  `barakuda/devices/optical_tweezers/ui/panel.py` is not orphaned at all — it is a fully wired,
  user-visible tab (`tab_export`, lines 975-983) with live handlers
  (`_on_open_export_dataset`, `_refresh_export_status`, `_on_export_all_clicked`, lines
  1763-1981) that actively copies files via `build_collision_safe_export_path`. This is a
  documentation/implementation gap, not a code-quality bug: the intent to retire it is recorded,
  the retirement hasn't happened.
- 14 root-level Markdown files with `EXPORT_` and `OT_OUTPUT_`/`OT_RUN_` prefixes
  (`EXPORT_ALL_VISIBLE_FILES_CHECKBOXES_SPEC.md` through `EXPORT_UNIFIED_CHECKBOX_LIST_VERIFICATION.md`,
  `OT_OUTPUT_LAYOUT_AUDIT.md` through `OT_RUN_OUTPUT_CONSOLIDATION_VERIFICATION.md`) are
  one-off spec/audit/verification documents from past agent sessions on export and output-layout
  work that, per the note above, is being superseded. They are historically useful but are dead
  weight in a public repo root — see §4 and §8.
- `barakuda/devices/acquisition/motion/ximc_stage.py:224-230` and
  `barakuda/devices/acquisition/motion/motion_run.py:232-236` contain committed ad-hoc tracer
  blocks (`# #region agent log — freeze tracer`) that append JSON lines to
  `debug-a34608.log` on every call — this is live, running debug instrumentation left in
  production code (not dead code, but code that shouldn't ship as-is; detailed in §4).

---

## 4. Technical debt, duplication, dependency and distribution blockers

### Duplication

- `barakuda/main.py` duplicates root `main.py` exactly (§1). One of the two is redundant now
  that `barakuda/startup.py` exists.
- `barakuda/devices/optical_tweezers/pipelines/` duplicates (an old version of) `pipeline/` and
  is entirely dead (§3).
- `assets/branding/barakuda/` and `logo/` contain **identical filenames**
  (`app_icon.png`, `logo_dark.png`, `logo_light.png`, `logo_main.png`) in two separate
  locations — worth confirming whether these are byte-identical copies or diverged, and
  consolidating to one location before a public release.

### Dependency / requirements issues

- `requirements.txt` line 11 pins `packaging @ file:///C:/miniconda3/conda-bld/packaging_1761049101700/work`
  — an **absolute local-filesystem path specific to one machine's conda build cache**. `pip
  install -r requirements.txt` will fail verbatim on any other machine, which is disqualifying
  for a public "pip install and go" story.
- `requirements.txt` and `requirements.lock.txt` diverge in both directions, not just
  pinned-vs-unpinned: the lock file has 4 extra transitive scikit-image dependencies
  (`ImageIO`, `lazy_loader`, `networkx`, `tifffile`) not listed in `requirements.txt`, while
  `requirements.txt` lists `AFMReader`, `matplotlib-scalebar`, `uncertainties` (all unpinned,
  no version) that are absent from the lock file entirely. Neither file is a complete,
  reproducible statement of the actual dependency graph on its own.
- `scikit-image` itself is unpinned (`>=0.21.0`) in `requirements.txt` but pinned
  (`==0.25.2`) in the lock file — a real version-drift risk for a scientific app where
  determinism is a stated project goal (`AGENT_BARAKUDA_WORKFLOW_NOTE.md` §1: "same input +
  same config + same version = same output").
- No `pyproject.toml` / `setup.py` at all — there is no `pip install barakuda` or `barakuda-
  acquisition` console-script story today; every launch is `python main*.py` from inside the
  source tree with the right interpreter already active.
- **`cellpose` is listed as optional but is actually mandatory for the only working AFM
  method.** `requirements.txt:28` has it commented out — `# cellpose  # optional: deep-learning
  segmentation backend for AFM` — but `afm/core/afm_v2_pipeline.py:3` states "Backend: Cellpose
  (mandatory)" and `afm/device.py:56-59` shows a hard warning banner ("⚠ Cellpose is NOT
  installed. Segmentation will fail.") precisely because Rod Bacteria — the only non-stub AFM
  method (§3) — cannot run without it. A fresh `pip install -r requirements.txt` produces an
  AFM device that opens but cannot analyze anything until the user separately discovers and
  installs `cellpose` themselves. This should be a real (if optionally-extra) dependency, not a
  comment.

### Paths, config, and data hardcoded to the source tree

- Every output/config root in the app is computed via `Path(__file__).resolve().parents[N]`
  climbing back to the repo root, never via `QStandardPaths` (zero uses anywhere in
  `barakuda/`) or any per-user app-data directory:
  - `barakuda/shell/main_window.py:106` — `runs_folder = Path(__file__).resolve().parents[2] / "runs"`
  - `barakuda/devices/optical_tweezers/ui/panel.py:461` — `Path(__file__).resolve().parents[4] / "runs" / "ot"`
  - `barakuda/devices/optical_tweezers/profile/profile_store.py:5` — climbs 5 parents to
    `profiles/ot/`
- This is fine for a source-tree-run scientific tool but is a **direct blocker for a real
  installer**: an app installed under `Program Files` (or `/Applications`, or `/opt`) would
  either need admin-writable install directories (bad practice) or every one of these
  `Path(__file__)`-based roots reworked to resolve against a per-user writable directory. This
  is one of the highest-leverage, most mechanical changes needed before packaging (see §7).

### Logging is ad-hoc, and includes live committed debug instrumentation

- No `logging.basicConfig` anywhere in the repo; `logging.getLogger` appears in only 9 files
  with no shared handler/formatter/rotation configuration. No `sys.excepthook` exists in any
  entry point, so there is no in-app crash-log mechanism at all.
- `barakuda_crash.log` and the `debug-*.log` files at repo root are not produced by any
  application feature — they come from manual redirection during past debugging sessions
  (consistent with there being no in-app logging setup that would produce them).
- Two motion-control files contain **live, currently-running debug tracer code**, not leftover
  scratch: `barakuda/devices/acquisition/motion/motion_run.py:232-236` and
  `barakuda/devices/acquisition/motion/ximc_stage.py:224-230` (comment-delimited
  `#region agent log` blocks) append a JSON line to `debug-a34608.log` on every stage-motion
  call. This explains why that one file is 1.3 MB and has a fresh timestamp — it is actively
  growing on every run, not a stale artifact. This should be treated as real technical debt: an
  unconditional file-append inside a hot hardware-control path, committed to source, is both a
  minor performance/IO concern and something a public release should not ship silently.

### Test suite: one repeated anti-pattern makes the full run look red; the tests themselves are green

Running the canonical command (`pytest -c pytest.headless.ini`, canonical interpreter
`C:/Users/jirik/anaconda3/envs/barakuda/python.exe`) produces, depending on exact invocation,
either 3 collection errors or those plus 7 further test failures. Both symptoms were fully
root-caused for this audit (not left as "out of scope") — they are **the same single bug**,
not two separate problems:

- **Root cause: 4 test files install a fake `sys.modules["PyQt6"]` stub at module scope, and
  it never gets cleaned up.** `tests/test_batch_controller_timing_truth.py:7-14`,
  `tests/test_ot_batch_efficiency_workflow.py:302-340,424-447,...`,
  `tests/test_ot_mode_sync.py`, and `tests/test_postrun_lifecycle.py` each contain a block
  shaped like:
  ```python
  if "PyQt6" not in sys.modules:
      _pyqt6 = types.ModuleType("PyQt6")
      _pyqt6.QtWidgets = types.ModuleType("PyQt6.QtWidgets")
      ...
      sys.modules["PyQt6"] = _pyqt6
      sys.modules["PyQt6.QtWidgets"] = _pyqt6.QtWidgets
  ```
  intended to let pure-logic code (e.g. `batch_controller`) import without a real Qt
  environment. The guard makes each file individually safe, but pytest collects every test
  file into **one shared process**, in alphabetical order. Whichever of these four files is
  collected first — `test_batch_controller_timing_truth.py`, since none of
  `test_acquisition_motion_*.py` (which sort before it) import real PyQt6 at module scope —
  installs its incomplete fake module tree, and Python's import cache means the real `PyQt6`
  package is never consulted again for the rest of the process. Every later test that needs
  the real package then breaks: **at collection time** for files whose top-level `from PyQt6...
  import ...` runs during collection (3 files: `test_dataset_tree_import.py`,
  `test_ot_mode_sync.py`, `test_startup_modes.py` — `ModuleNotFoundError:
  No module named 'PyQt6.QtCore'; 'PyQt6' is not a package`), and **inside the test body** for
  files whose real-PyQt6 import is deferred to run time (the other 7: 1 in
  `test_acquisition_motion_ui_scaffold.py`, 5 in `test_ot_batch_efficiency_workflow.py`, 1 in
  `test_postrun_lifecycle.py`). Confirmed directly: every one of these 10 tests, and every file
  containing them, **passes at 100% when run in isolation or with
  `--ignore=tests/test_batch_controller_timing_truth.py`** (verified: `pytest -c
  pytest.headless.ini --ignore=tests/test_batch_controller_timing_truth.py` →
  259 passed / 5 skipped / 0 failed across the other 264 tests, and
  `test_batch_controller_timing_truth.py`'s own 3 tests pass standalone). **Corrected total:
  262 passing, 0 failing, 5 skipped, 267 collected — the suite is fully green; what's broken is
  test isolation, not application code or scientific logic.**
- **Not a scientific regression.** None of the 4 offending files, nor any of the 10 tests that
  break because of them, touch physics/timing/report logic — this is purely a test-harness
  defect (module-scope global mutation with no teardown). The fix is mechanical and
  low-risk: replace the raw `sys.modules[...] = ...` assignments in those 4 files with
  `monkeypatch.setitem(sys.modules, ...)` (auto-reverts after each test) or an equivalent
  fixture-scoped stub — no production code needs to change.
- The 5 skips are also fully explained and are not a coverage gap worth chasing: all 5 are
  `pytest.skip("Real item folder is not available in this environment.")` calls in
  `tests/test_truth_resolvers_and_report.py:1557,1576,1874,1893,1912`, guarding integration
  tests that need a real captured OT dataset folder not present in this repository — this is
  the same gap noted in §8's "Sample data" recommendation, not a test-writing gap.
- `tests/conftest.py` is 6 lines and does nothing but register the `ui` pytest marker — no
  headless Qt platform (`QT_QPA_PLATFORM=offscreen`) is set anywhere in `conftest.py` or
  `pytest.headless.ini`, so headless behavior (if it holds) is implicit/environmental, not
  something the test config itself guarantees. Worth making explicit before wiring CI, since
  CI runners won't have the same implicit environment as the dev machine.

### Root-level repository clutter (already tracked in git — needs an actual cleanup commit, not just `.gitignore`)

`git ls-files` confirms these are committed, not just present on disk:

- **23 non-canonical loose Markdown files at repo root** (`DRAG_*`, `EXPORT_*`, `OT_OUTPUT_*`,
  `OT_RUN_OUTPUT_*`, `OT_V2_SHADOW_AUDIT.md`), all one-off audit/spec/verification documents
  from prior agent-assisted work, alongside the 4 canonical governance docs (`AGENTS.md`,
  `AGENT_BARAKUDA_WORKFLOW_NOTE.md`, `ARCHITECTURE.md`, `CLAUDE.md`) and `README.md`. 289 KB
  total. A public repo root with 28 Markdown files, only 5 of which are load-bearing, reads as
  noise to an outside contributor.
- `test_roi.py` and `test_roi2.py` at repo root — tracked, sit outside `tests/` and outside
  `pytest.headless.ini`'s `testpaths = tests`, so they are committed source that the canonical
  test run never executes.
- `script/` (singular — one file, `script/tests/OT_SMOKE.md`) alongside `scripts/` (plural, 17
  files on disk, but only 2 tracked: `dev_afm_roi_explorer.py`,
  `offline_drag_reprocess_day05.py` — the other ~15 one-off AFM/JPK/thesis scripts are
  deliberately excluded via individual `.gitignore` entries, so that split is already
  intentional, just visually confusing as a `script/`-vs-`scripts/` naming pair).
- `.vscode/settings.json` is tracked (`git ls-files .vscode/` confirms it) and bakes in a
  machine- and person-specific absolute path:
  `"python.defaultInterpreterPath": "C:\\Users\\jirik\\anaconda3\\envs\\barakuda\\python.exe"`.
  This is a minor privacy leak (the current maintainer's Windows username, tied to their real
  email per the git author identity on this repo) in a file that will also be simply wrong for
  every other contributor — either untrack it, or replace the hardcoded path with a
  workspace-relative/environment-variable form before making the repo public.

**Branch hygiene** (not part of "root clutter" but relevant to a clean public handoff): the
repository currently has 89 local branches and 62 remote branches. `git branch --merged main`
shows 83 of the 89 local branches are already merged into `main` and add no unique history —
almost entirely stale refs from iterative agent-assisted feature work (e.g. `test-2c79def`,
`find-last-good`, `ot-ui-rework-profiles`, `base-stable-acq`, dating back to March). Only 6
local branches are unmerged/active. None of this blocks a public release by itself (a `git
push --mirror` to a fresh public remote can simply not carry the stale branches at all), but if
the existing remote history is pushed as-is, a newcomer cloning the repo sees ~150 branches for
what is functionally a handful of active lines of work — worth a deliberate branch-pruning pass
before "public GitHub" rather than carrying it over silently.

What is **not** a cleanup problem, already correctly handled: `debug-*.log` (5 files, 1.5 MB),
`barakuda_crash.log`, `.tmp_drag_debug_after_fix/`, `.pytest_cache/`, `__pycache__/`, and
`runs/` (9.9 MB of real run output) are all untracked and/or already `.gitignore`d — they exist
locally on this machine but were never committed. `ot_shadow_trace.log` is currently untracked
but **is not yet covered by any `.gitignore` rule**, so nothing currently stops it from being
accidentally committed later.

### No distribution/CI scaffolding exists at all

No `*.spec` (PyInstaller), no build/packaging scripts, no `.github/workflows/`, no `.github/`
directory of any kind, no `LICENSE`, `CITATION.cff`, or `CONTRIBUTING.md`. Icon assets exist
only as `.png` (`logo/app_icon.png` etc.) — no `.ico`, which a Windows installer/executable
needs. This is expected for a lab-internal research tool at this stage, not a defect, but it is
the largest single gap between "current state" and "publicly installable."

---

## 5. GUI assessment (code-based; no live screenshots were taken for this pass)

This assessment is derived from reading `main_window.py`, `batch_controller.py`,
`shell/widgets/`, `shell/workers/`, and the OT/AFM/Acquisition panel files — not from running
the app and observing it live in a browser/desktop session. That's a limitation worth noting:
a follow-up pass that actually launches all three modes and screenshots each screen would
strengthen the visual-consistency findings below.

### Screen/panel inventory (one shared shell, per §2)

- Left dock: Dataset panel (`shell/widgets/dataset_panel.py`, 880 lines) — file/folder import
  list, checkable items, status icons, hierarchical folder import (with its own two dialogs,
  `SubfolderSelectionDialog` and `HierarchicalFolderImportDialog`).
- Top bar: device dropdown + method/profile combo.
- Center: tabbed/stacked Preview panel (`preview_panel.py`, 710 lines) — pyqtgraph-based image
  preview with ROI overlay, frame slider; separate stacked instances for AFM and OT.
- Right: the active device panel (OT `ui/panel.py` 1981 lines, AFM `device.py` 833 lines, or
  Acquisition `ui/panel.py` 2853 lines) — these three are visually and structurally the least
  consistent part of the app (see styling finding below).
- Bottom dock: Log panel (`log_panel.py`, 19 lines — trivial read-only `QTextEdit`).
- Dialogs: `RunProtocolDialog` (run_protocol.json editor), `PreviewGateReportDialog`
  (per-file PASS/FAIL table), `_CameraSelectDialog` (Acquisition), plus a separate top-level
  window `stage_console_window.py` (XIMC stage jog/diagnostics console, independent of the main
  shell window).

### Styling: no design system, ad-hoc per-widget CSS

A repo-wide search for a centralized `.qss` stylesheet or theme module found **none** —
`setStyleSheet()` is called 80 times across `barakuda/`, essentially all of them one-off inline
strings on individual widgets, e.g. `self._lbl_diag_status.setStyleSheet("color: #666;")`
(`stage_console_window.py:201`), `self.lbl_scale.setStyleSheet("color: #b71c1c; font-weight:
600;")` (`afm/device.py:72`), a hardcoded dark terminal box
`"QPlainTextEdit { background: #1e1e1e; color: #cccccc; border: 1px solid #333; padding: 4px;
}"` (`acquisition/ui/panel.py:462-465`). Colors in use span an uncoordinated set (`#555`,
`#666`, `#888`, `#0277bd`, `#2e7d32`, `#b71c1c`, `#cc3333`, ...) with no shared token/palette.
The specific historical `_make_card()` CSS-leak bug named in
`AGENT_BARAKUDA_WORKFLOW_NOTE.md` §10.1 no longer exists in the code (confirmed absent by grep
and by `git log -S`), but the underlying visual-inconsistency symptom it was trying to explain
is still structurally true today, just for a more mundane reason: there is no shared styling
layer at all, so every panel's author picked their own inline colors independently. This is a
textbook case where "redesign the GUI" and "extract a design system" are the same underlying
fix.

### One god-window, one god-controller

- `ShellMainWindow` (1941 lines) is a single class doing UI layout construction, business/domain
  glue (OT profile load/save, OT drag/baseline pairing UI logic), Qt signal wiring, QThread
  lifecycle management for 4 separate worker/thread pairs, and device activation — with no
  view/controller separation. `_activate_device()` alone is ~200 lines and branches by
  `device_id` string comparison with per-branch try/except signal wiring that **silently logs a
  warning and continues** on failure (`main_window.py:674`, `"WARN: OT panel signals not wired:
  {e!r}"`) rather than failing loudly — meaning a future contributor who changes a device
  panel's expected attribute surface can silently break signal wiring with no test or runtime
  error to catch it.
- `BatchController` (3161 lines) is organized as three comment-delimited "sections" but is
  functionally three enormous methods: `run_batch` (OT, lines 844-2549 — **1706 lines in one
  method**), `run_afm_batch` (lines 2550-3093, ~544 lines), `run_preview_gate` (lines 355-768,
  ~414 lines). This is a maintainability/regression-risk finding independent of GUI aesthetics
  — any GUI redesign work needs to route around this file, not touch its internals, which
  aligns with `AGENT_BARAKUDA_WORKFLOW_NOTE.md`'s own instinct to treat `batch_controller.py`
  as high-risk (already listed as a "do not touch casually" file in
  `docs/agent_tasks/GIT_HYGIENE_PLAN.md` §10 and `CP01_AGENT_QUEUE.md`'s split plan §10).
- Threading pattern is consistent and reasonable: four `QObject`-based workers
  (`afm_preview_worker.py`, `afm_run_worker.py`, `ot_pdf_worker.py`, `ot_run_worker.py`), each
  moved to a manually-created `QThread` with `pyqtSignal`s for progress/result/error — a
  conventional, if manually-wired (not `QThreadPool`-based), pattern. Not a problem to fix, just
  worth knowing before touching thread lifecycle during any redesign.

### Workflow friction signals

The mandatory Preview Gate → Run Batch sequence itself is a clean two-call flow
(`_on_preview_gate` → `batch.run_preview_gate(...)` → `btn_run.setEnabled(self.batch.preview_done)`),
consistent with the README's documented workflow. But surrounding it: 139 occurrences of
`hasattr(...)` duck-typing (95) or bare `except Exception` (44) across `main_window.py` alone, device
switching silently calls `self.batch.reset_gate()` on every change (invalidating a completed
Preview Gate with no obvious on-screen explanation to the user), and Acquisition mode
specifically resizes/hides the dataset dock and shared preview stack as a special case inside
`_activate_device()`. None of this is a functional bug, but it is the kind of accumulated
special-casing that makes a GUI redesign risk becoming a GUI+behavior rewrite unless scoped
carefully (see Phase 3 in §10).

### What a redesign should preserve vs. what it's free to change

Preserve (functional contracts, not visual choices): the Preview Gate → Run Batch gate itself;
the dataset/preview/log dock layout concept (it's a reasonable IDE-like layout, just
unstyled); the per-device-panel-swap pattern; the off-thread worker pattern for long-running
batch/report work. Free to change: every inline `setStyleSheet()` call, the visual language of
cards/labels/buttons, the currently-inconsistent OT-vs-AFM-vs-Acquisition look, and (as a
UX improvement, not required) making Preview Gate invalidation on device switch visible to the
user instead of silent.

---

## 6. Target architecture: two apps, one shared core

Given §2's finding — today's "two apps" are one process with a device filter, not two
programs — and the user's stated preference to keep two separate applications where that makes
architectural sense, the two real options are:

**Option A — keep the current single-process, mode-filtered shell** (what exists today),
just cleaned up and restyled. Lowest risk, smallest change, but does not give an "Acquisition"
install on a lab capture machine any actual independence from OT/AFM code — installing
Acquisition-only still ships all of OT's and AFM's 40K+ lines and their dependencies
(matplotlib, scikit-image, AFMReader, etc.) even though a pure capture workstation never uses
them.

**Option B — two real entry-point packages sharing one core library**, structured roughly as:

```
barakuda_core/            # today's barakuda/core/ + barakuda/devices/{base,registry}.py
                           #   physics, IO, run/report contracts, truth resolvers, calibration
barakuda_acquisition/      # today's barakuda/devices/acquisition/ + a slim acquisition-only shell
barakuda_analysis/         # today's barakuda/devices/{optical_tweezers,afm}/ + a slim analysis shell
```

with `barakuda_core` as a proper installable dependency of both, and the current
`ShellMainWindow`/`BatchController` either split into an acquisition-specific controller and an
analysis-specific controller (both built on shared dock/dataset/preview/log widget classes kept
in `barakuda_core` or a thin `barakuda_shell_common`), or kept as one shared shell class that
each entry point instantiates with a narrower, purpose-built widget set rather than the current
filter-after-construct approach.

This is a substantial refactor, not a cleanup — it directly touches `main_window.py` and
`batch_controller.py`, both flagged as high-risk/do-not-touch-casually in existing governance
docs. It should not be attempted in one pass; §10 sequences it as its own phase, after cleanup
and before GUI redesign, precisely because a device-filtered single shell is a legitimate
intermediate state to ship a first public release from if Option B's full split turns out to be
more work than the timeline allows. Recommendation: **do Option A cleanup first, decide on
Option B only after Phase 1-2 are done and the real packaging/distribution pressure (see §7) is
felt** — e.g., if lab acquisition machines genuinely need a much smaller install than analysis
workstations, that's the concrete signal to commit to Option B; if not, Option A properly
cleaned up and packaged may be entirely sufficient for the public release goal.

Either option should preserve, as fixed contracts per `ARCHITECTURE.md` §8 and
`AGENT_BARAKUDA_WORKFLOW_NOTE.md` §1: the truth-resolver model (timing/scale/bead truth), the
Preview Gate, the drag validation gate, and the deterministic run/report pipeline. None of this
audit's findings suggest touching those.

---

## 7. Distribution strategy for a non-technical end user

Ordered by what actually blocks "install and use it," not by implementation difficulty:

1. **Fix path resolution first — this blocks everything else.** Replace every
   `Path(__file__).resolve().parents[N]` output/config root (found in `main_window.py`,
   `ui/panel.py`, `profile_store.py` — §4) with a per-user writable directory. On Windows the
   natural choice is `%LOCALAPPDATA%\BARAKUDA\` (via `QStandardPaths.writableLocation
   (QStandardPaths.StandardLocation.AppDataLocation)`, which BARAKUDA currently never imports).
   This one change is what makes a real installer possible at all — without it, an installed
   copy under `Program Files` can't write `runs/` or read/write `profiles/` without elevated
   permissions.
2. **Fix `requirements.txt` portability** (remove the machine-local `packaging @ file:///...`
   pin; reconcile it against `requirements.lock.txt` into one accurate, installable set) before
   attempting any bundling — PyInstaller/briefcase/whatever tool is chosen will fail or silently
   miss dependencies otherwise.
3. **Packaging format: PyInstaller `--onedir` + a Windows installer (Inno Setup or WiX), not
   `--onefile`.** `--onefile` is simpler to hand someone but decompresses to a temp directory on
   every launch, which is a bad fit for a PyQt6 + numpy/scipy/opencv/matplotlib/scikit-image
   stack this size (slow startup, antivirus false positives are common with unpacking exes).
   `--onedir` bundled into a proper installer (sets Start Menu shortcuts, an uninstaller, and
   writes to `%LOCALAPPDATA%`) is the standard approach for a scientific PyQt6 app of this
   scale. Needs a real `.ico` (convert from the existing `logo/app_icon.png`).
4. **Two installers or one with a component choice**, mapping directly to §6's decision: if
   Option A (single shared shell) is kept, ship one installer with three Start Menu shortcuts
   (Full / Acquisition / Analysis) pointing at the same installed binary with different launch
   args — cheapest, matches today's architecture exactly. If Option B (real split) is done
   later, ship two installers (or one installer with selectable components) so an
   Acquisition-only lab machine doesn't need scikit-image/matplotlib/AFMReader installed at all.
5. **Config**: keep `profiles/` (OT param profiles) as the shipped default set inside the
   install directory, but let user-created/modified profiles live under the same
   `%LOCALAPPDATA%\BARAKUDA\` root as run outputs — never inside the (potentially
   read-only-for-non-admin) install directory.
6. **Data**: `runs/` becomes `%LOCALAPPDATA%\BARAKUDA\runs\` (or a user-chosen "Output Root,"
   which the OT panel already partially supports per `AGENT_BARAKUDA_WORKFLOW_NOTE.md` §4/§5 —
   that existing Output Root selector is the right hook to generalize, not a new mechanism).
7. **Logging**: add one real `logging.basicConfig` (or a small `barakuda/core/logging_setup.py`)
   with a rotating file handler writing to `%LOCALAPPDATA%\BARAKUDA\logs\`, and a
   `sys.excepthook` in each entry point that writes uncaught exceptions there instead of letting
   the process die silently or scatter `debug-*.log`/`barakuda_crash.log` files into whatever
   the current working directory happens to be. This also directly replaces the two committed
   ad-hoc tracer blocks in `motion_run.py`/`ximc_stage.py` (§4) with something safe to leave on
   permanently.
8. **Updates**: for a lab tool distributed to a small, known set of users, a manual
   "download the new installer from the GitHub Releases page" flow is appropriate for v1 — an
   auto-updater (e.g. checking GitHub Releases on startup) is a reasonable v2 addition, not a
   launch blocker, and adds meaningful complexity (code signing considerations, background
   update UX) that isn't justified yet.

---

## 8. Preparing the repository for a public GitHub release

- **README.md** — current version (`README.md`, 26 lines) is a stub written mid-refactor
  ("`Run Batch` orchestration is the next implementation step" — no longer true; AFM described
  as "placeholder panel" — no longer fully true, rod_bacteria is production per §3). Needs a
  real rewrite: what BARAKUDA is (optical tweezers microrheology + AFM + acquisition lab
  software), install instructions (once packaging exists), the three launch modes and what each
  is for, a screenshot or two once the GUI redesign lands, and a pointer to `ARCHITECTURE.md`
  for anyone wanting to contribute.
- **LICENSE** — does not exist. This is a decision only the user/institution can make (lab/PhD
  software often has constraints around institutional IP, prior publications, or funding-body
  requirements) — flagging as an open question rather than guessing, per the audit's own
  ground rules.
- **CITATION.cff** — does not exist; straightforward to add once authorship and any associated
  publication (the PhD Talent acceleration context mentioned in `AGENT_BARAKUDA_WORKFLOW_NOTE.md`)
  is settled.
- **requirements/packaging metadata** — add a real `pyproject.toml` (PEP 621) once §4's
  requirements-file reconciliation is done; this is also what makes `pip install -e .` and a
  console-script entry point (`barakuda`, `barakuda-acquisition`, `barakuda-analysis`) possible,
  replacing "run `python main.py` from inside the checked-out source" as the documented usage
  path.
- **Release workflow / GitHub Actions** — none exist (`.github/` is entirely absent). Minimum
  viable CI: run `pytest -c pytest.headless.ini` on push/PR (once the order-dependent
  collection-error bug from §4 is fixed, otherwise CI will be flaky from day one), plus a
  `py_compile`/import-smoke check for all three entry points on a Windows runner (the app is
  Windows-targeted — XIMC stage, Basler camera — so a Windows CI runner matters more than
  Linux/macOS here). A packaging-build workflow (produce the installer as a release artifact)
  is a natural Phase 4/5 addition, not a Phase 1 one.
- **Tests** — see §4's full breakdown: the suite is actually fully green (262 passing, 0
  failing, 5 skipped for a missing sample dataset) once a repeated `sys.modules["PyQt6"]`
  test-isolation anti-pattern in 4 files is fixed; AFM has zero dedicated tests. Before
  "public and CI-checked" is a fair claim, that isolation bug needs fixing — as-is, CI would be
  red on an arbitrary fraction of runs depending on collection order, which is worse than
  simply broken since it looks like flakiness rather than a clear failure.
- **Sample data** — none currently exist in the repo (the `runs/` directory is real lab data,
  correctly gitignored, not sample/synthetic data). For a public repo where people should be
  able to clone and try the analysis pipeline without lab hardware, a small synthetic or
  anonymized example dataset (a short OT video + timestamps, one `.spm` file) checked into
  something like `sample_data/` or fetched via a documented download step would materially help
  adoption — this is new work, not a cleanup, and should be scoped as its own task.
- **Root-level cleanup** — move or archive the 23 non-canonical loose `.md` files (§4) into
  `docs/history/` (or similar) rather than deleting them outright — they document real past
  decisions (export policy, output layout) that a future contributor might legitimately need,
  they just don't belong scattered across a public repo root. Remove `test_roi.py`/`test_roi2.py`
  from root (either fold into `tests/` properly or delete if genuinely obsolete — needs a
  human call, not an automated one, since this audit didn't read their content). Consolidate
  `assets/branding/barakuda/` vs `logo/` duplication. Delete the dead `barakuda/devices/
  optical_tweezers/pipelines/` directory. Add `.gitattributes` for line-ending policy (flagged
  but deferred back in `docs/agent_tasks/GIT_HYGIENE_PLAN.md` §4/§8 and still not done).

---

## 9. New visual direction for the GUI (proposal only — not implemented)

Per the brief, this is a direction to react to, not a spec to build from yet.

**Problem statement from §5:** no design system exists; every panel author chose their own
inline colors; OT is the de facto reference look per `.cursor/rules/ot-baseline-and-forward-
design.mdc` but AFM and Acquisition don't consistently follow it; the dock-based IDE-style
layout (dataset / preview / device panel / log) is structurally sound and worth keeping.

**Proposed direction:**

1. **Extract one QSS stylesheet, loaded once at `QApplication` construction in
   `barakuda/startup.py`.** This is the single highest-leverage, lowest-risk change: it doesn't
   touch any business logic, doesn't touch `batch_controller.py`, and immediately eliminates
   the 80-call scattered-`setStyleSheet` problem from §5. Define a small palette (2-3 neutral
   backgrounds, one accent color, one warning/error color reused for `PHYSICS_WARNING` /
   scale-reduced-trust / drag-gate-fail states — those already exist as data, they just don't
   have a consistent visual treatment today) and typography scale, and apply it globally instead
   of per-widget.
2. **Standardize the "card" pattern properly this time** — a single reusable
   `QGroupBox`/`QFrame`-based section widget used identically across OT, AFM, and Acquisition
   panels for parameter groups, replacing each panel's own ad-hoc section styling. This is
   exactly what `_make_card()` was trying to do before it was removed (§3/§5) — worth
   reattempting, but as a shared, tested widget class living in `barakuda/shell/widgets/`
   (or a new `barakuda/shell/theme.py` + `widgets/card.py`) rather than a per-file helper.
3. **Keep the dock layout, tighten the visual hierarchy.** Dataset (left), device panel (right),
   preview (center), log (bottom) is a reasonable, familiar layout for this kind of tool — the
   redesign should focus on consistent spacing/typography/color inside that structure rather
   than reinventing the layout itself, which would risk exactly the "rewritten workflow, not
   restyled UI" outcome the brief explicitly wants to avoid.
4. **Make gate/warning states visually first-class.** Preview Gate PASS/FAIL, drag validation
   verdict (`pass`/`suspect`/`fail`), and scale/timing "reduced trust" warnings
   (`ARCHITECTURE.md` §8.2, §8.5) are already rich, meaningful data the app computes — today
   they surface as plain-colored labels among many other plain-colored labels. A redesign should
   give these a distinct, consistent visual treatment (e.g. a status chip/badge component) so
   the scientifically-important signals are visually louder than routine UI chrome, not equally
   weighted with it.
5. **Fix the AFM progress bar bug (§3) as part of, not separate from, the GUI pass** — it's a
   small, contained fix (add a mid-inference progress callback in `afm_v2_pipeline.py` /
   `afm_run_worker.py`) and touching AFM's batch-run UI code during the redesign pass is a
   natural place to also close this out, rather than opening a second unrelated touch of the
   same files later.

Explicitly out of scope for the redesign, per the brief: no change to the Preview Gate →
Run Batch gate logic itself, no change to what data is shown (only how), no touching
`batch_controller.py`'s internals beyond wiring a new progress callback point.

---

## 10. Prioritized phased plan

**Phase 1 — Cleanup and stabilization** (lowest risk, no scientific/UI logic touched)
1. Remove dead `barakuda/devices/optical_tweezers/pipelines/` directory (zero importers,
   confirmed in §3).
2. Remove duplicate `barakuda/main.py` (identical to root `main.py`, §4) — keep whichever is
   actually documented as canonical.
3. Root-level tidy: relocate the 23 non-canonical `.md` files into `docs/history/`, resolve
   `test_roi.py`/`test_roi2.py` (fold into `tests/` or remove, human call needed),
   consolidate `assets/branding/barakuda/` vs `logo/`.
4. Add `.gitignore` coverage for `ot_shadow_trace.log` (currently uncovered, §4).
5. Fix `requirements.txt` portability (remove the machine-local `packaging` path; reconcile
   against `requirements.lock.txt`).
6. Fix the `sys.modules["PyQt6"]` test-isolation anti-pattern in the 4 identified files (§4) —
   root cause is known, fix is mechanical (`monkeypatch.setitem` instead of a bare module-scope
   assignment); needed before CI can be trustworthy. No other test triage is required — the
   suite is otherwise fully green (262/262 non-skipped tests passing, §4).
7. Decide whether to remove the committed debug-tracer blocks in `motion_run.py`/`ximc_stage.py`
   now (simple deletion) or defer to Phase 1's logging work replacing them properly (§7 point 7)
   — either is reasonable, just needs a decision.

**Phase 2 — Architecture** (decide and, if warranted, execute the Option A vs B question from §6)
1. Decide Option A (keep shared shell, cleaned up) vs Option B (real Acquisition/Analysis
   package split) — driven by whether lab deployment actually needs a lighter Acquisition-only
   install, not by preference alone.
2. If Option B: extract `barakuda_core` as an installable shared package first, in isolation,
   before touching `main_window.py`/`batch_controller.py` internals.
3. Resolve the two documented layering violations (`core/tracking.py` + `core/video_reader.py`
   importing device-layer `optical_tweezers.perf`; `acquisition/ui/panel.py` importing
   shell-layer `stage_service`/`stage_console_window`/`run_protocol_dialog`) — `ARCHITECTURE.md`
   §12 already prioritizes this as the top item for the next code-review pass, independent of
   this audit.
4. Add per-user writable path resolution (`QStandardPaths`) as its own isolated task — it's
   foundational to Phase 4 packaging and should land before, not during, packaging work.

**Phase 3 — GUI redesign** (visual only, per §9 — no workflow/logic changes)
1. Extract and apply one global QSS stylesheet.
2. Build the shared "card" section widget and roll it out to OT/AFM/Acquisition panels
   consistently.
3. Add the status-chip/badge treatment for gate and warning states.
4. Fix the AFM progress-bar bug as part of this pass (§3, §9 point 5).
5. Decide the fate of the OT Export tab (§3) — either finish retiring it per the existing
   workflow-note intent, or explicitly un-deprecate it — it shouldn't stay in limbo through a
   visual redesign.
6. Manual QA pass across all three `app_mode`s (full/acquisition/analysis) with real screenshots
   — this audit's GUI section (§5) was code-only; a follow-up visual QA pass should close that
   gap once redesign work starts.

**Phase 4 — Packaging and installer**
1. Centralized logging setup + `sys.excepthook` (§7 point 7), replacing the ad-hoc debug logs.
2. `pyproject.toml` + console-script entry points.
3. PyInstaller `--onedir` build for each launch mode (or each package, if Option B was chosen
   in Phase 2), `.ico` icon conversion from existing `logo/app_icon.png`.
4. Inno Setup/WiX installer wrapping the PyInstaller output, writing to
   `%LOCALAPPDATA%\BARAKUDA\`.
5. Manual install/uninstall test on a clean machine (no conda, no dev tooling).

**Phase 5 — Public release**
1. LICENSE decision (needs user/institutional input — flagged, not decided, in §8).
2. README rewrite, CITATION.cff, CONTRIBUTING.md.
3. GitHub Actions: pytest on push/PR (contingent on Phase 1 item 6 being done), packaging-build
   workflow producing installer artifacts on tagged releases.
4. Sample/synthetic dataset for first-run trial without lab hardware (§8) — scope as its own
   task, likely sized similarly to a Phase 1-2 task, not a quick add-on.
5. First tagged public release.

---

## Open questions for the user (flagged, not guessed at)

- **License choice** — institutional/funding constraints may apply; needs your input, not an
  assumption.
- **Option A vs Option B** (§6) — do any lab Acquisition-only machines actually need a
  materially smaller install than a full Analysis workstation? If not, Option A properly
  cleaned up may be sufficient and Option B's larger refactor may not be worth the risk it
  carries relative to `main_window.py`/`batch_controller.py`'s sensitivity.
- **OT Export tab fate** (§3, §8) — finish retiring it, or keep it and update the workflow note?
  It's currently live code contradicting a documented intent.
- **23 legacy root `.md` files** (§4, §8) — archive into `docs/history/` as recommended, or
  delete outright? They have real historical value but no clear owner for a public-facing repo.
