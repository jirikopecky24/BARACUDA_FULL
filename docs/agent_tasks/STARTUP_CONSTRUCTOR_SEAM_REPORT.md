# Startup Constructor Seam Report — BARAKUDA CP01

## 1. Purpose

This report identifies the safest place to later introduce BARAKUDA launch modes (Acquisition vs Analysis) while keeping current behavior unchanged during CP01 preparation.

## 2. Current startup path

Current startup path is:

1. `main.py` (or `barakuda/main.py`) is executed.
2. `QApplication(sys.argv)` is created.
3. `ShellMainWindow()` is constructed.
4. `win.show()` is called.
5. `app.exec()` starts the Qt event loop.

So both startup files currently run the same shell-first path with no mode parameter.

## 3. Duplication between startup files

Yes, `main.py` and `barakuda/main.py` currently duplicate startup logic line-by-line.

Future launchers should avoid repeating this duplication. A shared startup helper (single function) is safer for consistency and lower maintenance risk.

## 4. ShellMainWindow constructor

- Constructor signature:
  - `def __init__(self) -> None`
- Constructor arguments:
  - currently **none**
- It initializes:
  - main shell window geometry/title/icon
  - dataset panel, AFM/OT preview panels, log panel
  - batch controller
  - device container and splitters/docks
  - device selection UI controls
  - per-device run/preview worker state
- Devices are loaded at:
  - `self._devices: list[DeviceSpec] = list_devices()`
  - inside `ShellMainWindow.__init__`

## 5. Device loading seam

- `list_devices()` is called in:
  - `barakuda/shell/main_window.py` constructor (`__init__`)
- `list_devices()` currently returns:
  - OT spec
  - AFM spec
  - Acquisition spec if import succeeds
- Device specs are stored in:
  - `self._devices`
- Device dropdown is populated at:
  - `for d in self._devices: self.device_combo.addItem(d.display_name, d.device_id)`
- Selected device is activated via:
  - `device_combo.currentIndexChanged -> _on_device_changed() -> _set_device_by_index() -> _activate_device()`
- Current special acquisition behavior is in:
  - `_activate_device()` branch for `self._active_device_id == "acquisition"` (shared preview and dataset dock hidden/collapsed).

## 6. Candidate seam options

### Option A — Add mode argument to ShellMainWindow

Pros:
- Small conceptual seam: startup already constructs `ShellMainWindow` directly.
- Can preserve default by making argument optional (backward compatible).
- Keeps filtering/UI adaptation near existing device activation logic.

Cons:
- Touches large/high-risk shell file.
- Easy to accidentally mix startup changes with broader UI behavior.

Risk level:
**medium**

### Option B — Add mode argument to list_devices()

Pros:
- Narrowly focused on device set composition.
- Keeps mode concern away from many UI internals if used carefully.

Cons:
- Requires changing registry contract used by shell.
- May hide important UI behavior coupling (acquisition has special shell handling, not just list filtering).

Risk level:
**medium**

### Option C — Add shared startup helper function

Pros:
- Best for reducing duplication in `main.py` and `barakuda/main.py`.
- Enables future launchers to share one constructor path.
- Supports zero behavior change initially (helper can call `ShellMainWindow()` exactly as today).

Cons:
- Adds one new startup abstraction to maintain.
- Still needs later seam handoff to shell/registry for real mode behavior.

Risk level:
**low**

### Option D — Create launcher files first without mode support

Pros:
- Very small additive change.
- Easy to test import/start behavior.

Cons:
- Immediate user-facing value is low without mode behavior.
- Risks multiplying duplicated startup code unless helper exists first.

Risk level:
**low to medium**

## 7. Recommended seam

Recommended seam: **staged combination starting with Option C (shared startup helper), then optional argument seam in ShellMainWindow (Option A) with default unchanged.**

Why this is safest:

- zero behavior change by default
- minimal changed files in first step
- no scientific logic, timing, report, or hardware changes
- easy smoke-test path
- prevents startup duplication before adding launchers

## 8. Future implementation micro-plan

### Step 1 — Create shared startup helper

- likely files to edit:
  - `main.py`
  - `barakuda/main.py`
  - one small new shared startup module (for helper function)
- files explicitly not to touch:
  - `barakuda/shell/main_window.py` logic
  - `barakuda/devices/registry.py`
  - scientific/timing/report/hardware files
- validation check:
  - both existing entry points still launch exactly as before
- stop condition:
  - if more than 3 Python files are required

### Step 2 — Keep default behavior unchanged

- likely files to edit:
  - same startup helper path only
- files explicitly not to touch:
  - device logic and UI behavior
- validation check:
  - no visible behavior drift in default launch
- stop condition:
  - if any non-startup module requires edits

### Step 3 — Add optional mode argument with default current behavior

- likely files to edit:
  - `barakuda/shell/main_window.py` signature/wiring only
  - startup helper to pass default mode
- files explicitly not to touch:
  - acquisition hardware code
  - report/timing/batch/scientific modules
- validation check:
  - default mode path identical to current behavior
- stop condition:
  - if broad refactor in shell becomes necessary

### Step 4 — Add launchers only after default path passes

- likely files to edit/create:
  - `main_acquisition.py` (new)
  - `main_analysis.py` (new)
- files explicitly not to touch:
  - scientific/report/timing/hardware code
- validation check:
  - both new launchers import and start app
- stop condition:
  - if launcher addition requires changing registry internals

### Step 5 — Device filtering later task

- likely files to edit:
  - shell/registry seam only (small scope)
- files explicitly not to touch:
  - device implementation internals
- validation check:
  - mode-specific device availability behaves as intended
- stop condition:
  - if filtering requires changing scientific logic/hardware paths

### Step 6 — Smoke tests

- likely files to edit:
  - `tests/` launcher/startup smoke tests
- files explicitly not to touch:
  - existing validated scientific tests unless necessary
- validation check:
  - import/startup tests pass without real hardware
- stop condition:
  - if tests require physical devices

## 9. Suggested next implementation prompt

```text
You are working on BARAKUDA.

Task type: tiny implementation (startup seam only).
Goal: introduce a shared startup helper to remove duplicated launcher logic while preserving current behavior.

Allowed files:
- main.py
- barakuda/main.py
- one new small startup helper module (if needed)

Forbidden:
- Do not edit ShellMainWindow logic.
- Do not edit registry/list_devices behavior.
- Do not edit scientific logic, timing logic, report generation, batch summary logic, or acquisition hardware code.
- Do not edit more than 3 Python files total.

Expected output:
- main.py and barakuda/main.py call shared startup helper.
- Runtime behavior remains identical to current default startup.

Checks:
- Both entry points still import and start QApplication + ShellMainWindow.
- No behavior change in default launch path.
- Report modified files.

Stop condition:
- Stop if more than 3 Python files are required or if ShellMainWindow/registry changes become necessary.
```

## 10. Risks and stop conditions

Risks:

- hidden startup side effects in shell initialization
- accidental behavior drift while deduplicating startup logic
- unclear boundary between startup seam and device filtering seam
- import-order issues when adding helper abstraction

Hard stop conditions:

- stop if more than 3 Python files need editing
- stop if `ShellMainWindow` requires broad refactor
- stop if registry behavior is unclear
- stop if imports fail
- stop if hardware-specific code must be modified
- stop if tests require real hardware

## 11. Implementation status

- Shared startup helper implemented in barakuda/startup.py.
- main.py and barakuda/main.py now delegate to the helper.
- Implementation passed audit in docs/agent_tasks/STARTUP_HELPER_IMPLEMENTATION_AUDIT_001.md.
- Compile/import validation passed using:
  "%USERPROFILE%\anaconda3\envs\barakuda\python.exe"
- The earlier validation failure was an environment PATH issue.
- Startup helper is accepted as validated.
- Next safe implementation step is optional mode argument seam with default current behavior.

### Update 2026-05-12 — Optional app_mode seam

- app_mode seam implemented successfully.
- Files changed:
  - `barakuda/startup.py` — `run_app(app_mode: str = "full")` added; passes `app_mode` to `ShellMainWindow`.
  - `barakuda/shell/main_window.py` — `__init__(self, app_mode: str = "full")` added; `self._app_mode = app_mode` stored.
- Default behavior unchanged: all existing call sites pass no argument, default `"full"` applies.
- No filtering added. No device list behavior changed. No dropdown behavior changed.
- No scientific, timing, report, batch, or hardware logic touched.
- No registry/list_devices changes.
- Validation commands run:
  - `&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -m py_compile barakuda/startup.py barakuda/shell/main_window.py main.py barakuda/main.py` → exit 0 (pass)
  - `&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "import main; import barakuda.main; import barakuda.startup; from barakuda.shell.main_window import ShellMainWindow; print('mode seam imports ok')"` → printed `mode seam imports ok` (pass)
- Next safe step: add two tiny launcher files (`main_acquisition.py`, `main_analysis.py`) that call `run_app(app_mode="acquisition")` and `run_app(app_mode="analysis")` — still without filtering.

### Update 2026-05-12 — Acquisition / Analysis launcher stubs

- Files created:
  - `main_acquisition.py` — calls `run_app(app_mode="acquisition")`, `raise SystemExit(main())`.
  - `main_analysis.py` — calls `run_app(app_mode="analysis")`, `raise SystemExit(main())`.
- No existing Python files edited.
- No filtering added. No device list behavior changed. No UI behavior changed.
- No scientific, timing, report, batch, or hardware logic touched.
- No registry/list_devices changes.
- Validation commands run:
  - `&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -m py_compile main_acquisition.py main_analysis.py` → exit 0 (pass)
  - `&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "import main_acquisition; import main_analysis; print('launchers import ok')"` → printed `launchers import ok` (pass)
- Next safe step: plan and audit device filtering by app_mode before implementing it.


## 12. Acceptance checklist

- [x] Report created.
- [x] No Python/application files edited.
- [x] Current startup path described.
- [x] ShellMainWindow constructor described.
- [x] Device loading seam described.
- [x] Candidate seam options compared.
- [x] One recommended seam chosen.
- [x] Future implementation micro-plan included.
- [x] Next tiny implementation prompt included.
- [x] Risks and stop conditions included.

## 13. Recommended next task

**audit this seam report**

Reason: this report chooses a concrete seam strategy (helper-first, then optional mode seam). A quick audit ensures team agreement before even tiny startup edits and keeps CP01 changes deterministic and low-risk.

### Update 2026-05-12 — app_mode now affects visible device list

- Filtering implemented in `barakuda/shell/main_window.py` only.
- Module-level helper `_apply_mode_device_filter` added before the class definition.
- One call inserted in `ShellMainWindow.__init__` after `list_devices()`.
- Launchers `main_acquisition.py` and `main_analysis.py` now pass `app_mode` values that actively filter the visible device combo.
- Default `app_mode="full"` behavior remains preserved — all devices returned by `list_devices()` are shown.
- No change to `registry.py`, `list_devices()`, `DeviceSpec`, or any device module.
- Validation passed: compile, ShellMainWindow import, headless filter assertions ("filter logic ok"), launcher import ("launchers still ok").
- Next safe step: add startup/mode smoke tests or perform manual GUI sanity check for full/acquisition/analysis launch modes.

### Update 2026-05-12 — startup/mode smoke tests

- `tests/test_startup_modes.py` created (12 tests).
- Tests cover `_apply_mode_device_filter` for full/acquisition/analysis/unknown modes and edge cases (empty list).
- Launcher imports tested for `main`, `barakuda.main`, `main_acquisition`, `main_analysis`, `barakuda.startup`.
- No `QApplication` created. No GUI launched. No hardware required.
- Validation: `pytest tests/test_startup_modes.py -q` → 12 passed, 0 failed, 6 warnings in 4.02s.
- Next safe step: manual GUI sanity check for full/acquisition/analysis launch modes.

### Update 2026-05-12 — GUI sanity check passed

- Full mode (`main.py`), acquisition mode (`main_acquisition.py`), and analysis mode (`main_analysis.py`) all launched successfully.
- `main.py` remains the complete BARAKUDA application showing all available devices.
- `main_acquisition.py` and `main_analysis.py` now function as solo launchers with correct device scope.
- No visible startup errors observed in any mode.
- The startup/`app_mode` seam is accepted as functionally validated end-to-end.


