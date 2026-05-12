# REPO_CARTOGRAPHY_REPORT

## Scope

Diagnostic-only repository cartography for BARAKUDA.  
No application code edits were performed.

## 1) Main application entry point (appears to be)

- Primary launcher appears to be `main.py` at repo root.
- It creates `QApplication`, instantiates `ShellMainWindow`, and executes the UI event loop.
- `barakuda/main.py` is a near-identical package-level launcher and likely secondary/alternate entry path.
- `README.md` instructs users to run `python main.py`, reinforcing root `main.py` as canonical.

## 2) Folders containing core BARAKUDA application

- `barakuda/shell/` — main GUI shell, main window, batch controller, workers, dataset/preview/log widgets.
- `barakuda/core/` — shared core logic (pre/postprocess, run manager, reports, physics helpers, protocol/truth/resolver utilities).
- `barakuda/devices/` — modular device domain architecture and registry.
- `assets/branding/` — app branding assets (icons/logos) used by UI/runtime packaging contexts.

## 3) Folders containing Optical Tweezers analysis

- `barakuda/devices/optical_tweezers/` (main OT domain).
- Key OT subareas:
  - `pipeline/` and `pipelines/` (tracking, preprocess, QC, drift/postprocess orchestration).
  - `drag/` (analysis, physics, alignment, schema, export, active umbrella, viscoelastic).
  - `strategies/` (PSD/oscillation/time-resampling/drag-related strategies).
  - `export/`, `audit/`, `profile/`, `ui/`.

## 4) Folders containing Acquisition-related code

- `barakuda/devices/acquisition/` (main Acquisition domain).
- Key subareas:
  - `ui/` (acquisition panel and stage scan lifecycle).
  - `motion/` (stage abstractions, recipes, metric conversion, motion run, scale audit, XIMC stage adapter).
  - camera stack: `camera.py`, `camera_base.py`, `camera_factory.py`, `webcam_camera.py`.
  - data/model paths: `dataset.py`, `device.py`.

## 5) Folders containing AFM-related code

- `barakuda/devices/afm/` (main AFM domain).
- Key subareas:
  - `core/` (compute pipeline, overlay/diameter helpers, cache).
  - `methods/` (method implementations such as `rod_bacteria.py`, `hydrogel_porosity.py`).
  - `io/` (AFM format readers/loaders).
  - `export/`, plus `device.py` and `manifest.py`.

## 6) Tests that exist

- Main suite under `tests/` with focused files for OT drag workflow, output routing, batch/timing, truth resolvers, and acquisition motion behavior.
- Notable themes:
  - OT/drag: `test_drag_*`, `test_ot_*`, `test_offline_drag_reprocess_workflow.py`.
  - Acquisition/motion: `test_acquisition_motion_*`, `test_stage_*`, dataset tree import.
  - Lifecycle/reporting: `test_postrun_lifecycle.py`, `test_truth_resolvers_and_report.py`.
- Additional standalone test-like scripts at root:
  - `test_roi.py`
  - `test_roi2.py`
- Test configuration present:
  - `pytest.headless.ini`
  - `tests/conftest.py`

## 7) Packaging / install files that exist

- `requirements.txt`
- `requirements.lock.txt`
- `README.md` (run/install-facing guidance)
- No `pyproject.toml`, `setup.py`, `environment.yml`, `Dockerfile`, or `Makefile` were found.

## 8) Files/folders that look risky or very large

- Ephemeral/generated debug data folders:
  - `.tmp_drag_debug/`
  - `.tmp_drag_debug_after_fix/`
  - These contain CSV/JSON run artifacts and should be treated as generated data, not source-of-truth code.
- Large script candidates (high line counts inferred from `__main__` locations):
  - `scripts/build_thesis_methods_master_simple.py` (very large)
  - `scripts/build_thesis_brown_master.py`
  - `scripts/process_day06_dls.py`
- High-complexity integration files likely sensitive to regressions:
  - `barakuda/shell/main_window.py`
  - `barakuda/shell/batch_controller.py`
  - `barakuda/devices/optical_tweezers/drag/pipeline.py`
  - `barakuda/devices/optical_tweezers/pipeline/orchestrator.py`

## 9) Files/folders agents should not touch casually

- Launch and shell integration:
  - `main.py`
  - `barakuda/shell/main_window.py`
  - `barakuda/shell/batch_controller.py`
- Core protocol/truth/report contracts:
  - `barakuda/core/run_protocol.py`
  - `barakuda/core/truth_resolvers.py`
  - `barakuda/core/run_manager.py`
- Device registration and manifests:
  - `barakuda/devices/registry.py`
  - `barakuda/devices/*/manifest.py`
  - `barakuda/devices/*/device.py`
- Scientific logic surfaces:
  - `barakuda/devices/optical_tweezers/drag/physics.py`
  - `barakuda/core/ot_physics.py`
  - `barakuda/devices/afm/core/compute.py`
- Hardware interfaces:
  - `barakuda/devices/acquisition/motion/ximc_stage.py`
  - acquisition camera/stage base abstractions under `barakuda/devices/acquisition/`.

## 10) Recommended minimal route to separate BARAKUDA Acquisition and BARAKUDA Analysis launchers

Minimal, low-risk path (without immediate deep refactor):

1. Keep current shell as shared base (`ShellMainWindow`) and preserve existing default behavior.
2. Introduce two thin launcher scripts only:
   - `main_acquisition.py`
   - `main_analysis.py`
3. In each launcher, pass a startup mode flag/profile into shell initialization (or initial device selection hook) so:
   - Acquisition launcher starts focused on `barakuda.devices.acquisition`.
   - Analysis launcher starts focused on analysis devices (OT/AFM).
4. Keep shared infrastructure unchanged initially:
   - `barakuda/core/`
   - worker framework under `barakuda/shell/workers/`
   - existing device registry contracts.
5. Add launcher-specific smoke tests only (start + correct initial mode), then iterate.
6. Defer any architectural split of shared classes until launcher-level separation is stable and tested.

This route minimizes risk by introducing separation at startup composition boundaries first, not by rewriting device/core logic.
