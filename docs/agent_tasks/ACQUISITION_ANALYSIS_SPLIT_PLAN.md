# Acquisition / Analysis Split Plan — BARAKUDA CP01

## 1. Purpose

BARAKUDA should be split into separate Acquisition and Analysis launch modes for CP01 to improve v1 laboratory usability, reduce operator confusion, and lower risk of mixing hardware capture workflows with offline analysis workflows.

This is:

- a v1 usability split for lab deployment,
- not a fork into two separate projects,
- and should preserve one shared BARAKUDA codebase.

## 2. Current startup flow

Current startup is straightforward and currently shared:

- Main entry points:
  - `main.py`
  - `barakuda/main.py`
- Both entry points create `QApplication`, construct `ShellMainWindow`, and call `app.exec()`.
- Application shell:
  - `barakuda/shell/main_window.py` is the central UI assembly point.
  - It creates dataset/preview/log panels and device panel container.
- Module loading:
  - `ShellMainWindow` calls `list_devices()` from `barakuda/devices/registry.py`.
  - `list_devices()` currently returns OT + AFM, and conditionally Acquisition.
- UI panel assembly:
  - Device dropdown (`device_combo`) is populated from `DeviceSpec` list.
  - `_activate_device()` swaps device panel and wiring per selected module.
  - Acquisition mode already has special UI behavior in the shell (shared preview hidden, dataset dock hidden).

## 3. Current module structure

High-level structure in current repository:

- Shared core:
  - `barakuda/core/`
  - `barakuda/shell/` (main window, batch controller, workers, shared widgets)
  - `barakuda/devices/base.py`
  - `barakuda/devices/registry.py`
- Acquisition-related:
  - `barakuda/devices/acquisition/` (camera stack, motion stack, acquisition panel, acquisition device spec)
- Analysis-related:
  - mostly OT + AFM through `barakuda/devices/optical_tweezers/` and `barakuda/devices/afm/`
  - analysis orchestration and run/report support in `barakuda/core/` and `barakuda/shell/`
- Optical Tweezers:
  - `barakuda/devices/optical_tweezers/` (pipeline, drag, strategies, export, audit, UI panel)
- AFM:
  - `barakuda/devices/afm/` (methods, compute, I/O, export, panel/device spec)
- Reports:
  - `barakuda/core/ot_report.py`
  - `barakuda/core/afm_report.py`
  - `barakuda/core/export_xlsx.py`
  - plus worker/export paths in shell and device modules
- Tests:
  - `tests/` with OT/drag, timing/batch, acquisition motion, and reporting checks
- Docs/rules:
  - `docs/agent_tasks/`
  - `AGENTS.md`
  - `.cursor/rules/`

Note: paths like `barakuda/app.py`, `barakuda/ui/`, `barakuda/acquisition/`, `barakuda/analysis/`, `barakuda/plugins/`, and `barakuda/modules/` are not present in the current structure; equivalent functionality is currently organized under `barakuda/shell/`, `barakuda/core/`, and `barakuda/devices/`.

## 4. Proposed v1 split concept

Safest minimal CP01 concept:

- Keep one shared codebase.
- Add two small launcher entry points later:
  - BARAKUDA Acquisition
  - BARAKUDA Analysis
- Introduce a simple startup mode argument/profile:
  - `mode="acquisition"`
  - `mode="analysis"`
  - optional `mode="full"` (internal/developer)
- Filter visible/available devices by mode at startup composition boundary.
- Do not duplicate scientific logic (OT/AFM/physics/report code stays shared).
- Preserve current `main.py` behavior during first phase to avoid breaking established workflows.

## 5. BARAKUDA Acquisition mode

Acquisition mode should prioritize live capture and run creation:

- camera/acquisition workflow
- run creation and folder initialization
- metadata capture
- sidecar generation (timestamps/meta/qc artifacts)
- acquisition sanity checks (preview/connectivity/basic motion checks)
- optional run protocol access tied to acquisition run folders
- no heavy offline analysis as default behavior unless explicitly needed

## 6. BARAKUDA Analysis mode

Analysis mode should prioritize post-acquisition processing:

- opening existing videos/datasets
- Brownian analysis
- Drag analysis
- batch summaries
- report generation
- dataset-level exports
- retrospective audit workflows
- no requirement for active camera/stage control hardware

## 7. Shared core that must remain common

Do not duplicate these shared parts:

- configuration and runtime defaults
- project/run metadata structures and protocol handling
- file/path helpers and run-output layout utilities
- report infrastructure where shared
- scientific calculation modules (OT/AFM physics/compute paths)
- logging and provenance/audit surfaces
- common shell framework and common widgets/workers where mode-agnostic
- device registry contract (`DeviceSpec`, list/build pattern), even if filtered by mode

## 8. Minimal implementation sequence for later

Startup helper seam completed.
The original duplicated startup logic has been extracted into barakuda/startup.py.
This supports later mode launchers while preserving current behavior.
Next implementation should not skip validation of the helper with the correct Python environment.

### Update 2026-05-12 — Launcher stubs completed (Task C)

`main_acquisition.py` and `main_analysis.py` now exist at the repository root.
Both call the shared startup helper with their respective app_mode values:
- `run_app(app_mode="acquisition")`
- `run_app(app_mode="analysis")`

No filtering is implemented yet. No existing files were modified. Compile and import validation passed.
Next step: plan and audit device filtering by app_mode before implementing it (Task D).


Conservative small-task sequence:

### Task A — Confirm startup constructor seam

- Goal:
  - identify the safest constructor seam for injecting launch mode without behavior change.
- Likely files to edit:
  - none (analysis task) or later `main.py`, `barakuda/main.py`, `barakuda/shell/main_window.py` signature only.
- Files not to touch:
  - scientific modules under `barakuda/core/` and device physics/compute files.
- Validation check:
  - documented seam and unchanged current startup behavior.
- Stop condition:
  - if seam requires refactoring multiple subsystems.

### Task B — Add non-invasive mode argument

- Goal:
  - add optional startup mode argument with default preserving current behavior.
- Likely files to edit:
  - `barakuda/shell/main_window.py`
  - maybe `main.py` and `barakuda/main.py` for wiring.
- Files not to touch:
  - timing/scientific/report logic files.
- Validation check:
  - default launch still works exactly as before.
- Stop condition:
  - if more than 5 Python files are required.

### Task C — Add two tiny launchers

- Goal:
  - add minimal launchers for acquisition and analysis modes.
- Likely files to edit/create:
  - `main_acquisition.py` (new)
  - `main_analysis.py` (new)
  - optional minimal import helper if needed.
- Files not to touch:
  - registry internals, scientific logic, UI layout files.
- Validation check:
  - launchers import and construct app successfully.
- Stop condition:
  - if launcher creation requires modifying deep device logic.

### Task D — Add device filtering by mode

- Goal:
  - filter visible/loaded devices by mode (composition-level only).
- Likely files to edit:
  - `barakuda/shell/main_window.py` (selection/filter path)
  - optionally `barakuda/devices/registry.py` only if absolutely necessary.
- Files not to touch:
  - OT/AFM/acquisition scientific pipelines and report code.
- Validation check:
  - Acquisition launcher shows acquisition-focused device set.
  - Analysis launcher shows analysis-focused device set.
- Stop condition:
  - if filtering requires changing device implementation internals.

### Task E — Add smoke tests for startup

- Goal:
  - add lightweight tests for launcher import/startup contracts.
- Likely files to edit:
  - add focused tests under `tests/` (launcher/mode smoke only).
- Files not to touch:
  - scientific/timing/report calculation tests unless needed for imports.
- Validation check:
  - smoke tests pass in headless-safe manner.
- Stop condition:
  - if tests require real hardware.

### Task F — Update docs

- Goal:
  - document mode intent, startup commands, and safety boundaries.
- Likely files to edit:
  - `README.md`
  - `docs/agent_tasks/` status/notes as needed.
- Files not to touch:
  - app logic.
- Validation check:
  - docs clearly distinguish acquisition vs analysis paths.
- Stop condition:
  - if documentation reveals unresolved architectural ambiguity.

### Task G — Packaging entry points (later)

- Goal:
  - define packaged entry points once launcher behavior is stable.
- Likely files to edit:
  - future packaging metadata (`pyproject.toml`) in dedicated packaging task.
- Files not to touch:
  - scientific logic.
- Validation check:
  - install/run path reproducible and mode launchers available.
- Stop condition:
  - if packaging work conflicts with unresolved git hygiene/line-ending baseline.

## 9. Risks and stop conditions

Key risks:

- accidental scientific logic changes during launcher work
- breaking existing full app launch behavior
- hidden coupling between acquisition and analysis imports
- hardware-specific imports causing analysis-mode startup failures
- UI registry/listing side effects from device filtering
- hidden assumptions inside module loading and signal wiring

Hard stop conditions:

- stop if more than 5 Python files must change
- stop if scientific calculations need edits
- stop if hardware control code must be changed just to support analysis launcher
- stop if registry logic is unclear
- stop if tests cannot import app startup paths

## 10. Files agents should not touch during first implementation

Require explicit permission before editing:

- scientific formula files:
  - `barakuda/core/ot_physics.py`
  - `barakuda/devices/optical_tweezers/drag/physics.py`
  - `barakuda/devices/afm/core/compute.py`
- timing/FPS logic:
  - `barakuda/core/run_protocol.py`
  - `barakuda/core/truth_resolvers.py`
  - timing-sensitive acquisition motion files under `barakuda/devices/acquisition/motion/`
- batch summary logic:
  - `barakuda/shell/batch_controller.py`
- report value generation:
  - `barakuda/core/ot_report.py`
  - `barakuda/core/afm_report.py`
  - `barakuda/core/export_xlsx.py`
- acquisition hardware control:
  - `barakuda/devices/acquisition/camera*.py`
  - `barakuda/devices/acquisition/motion/ximc_stage.py`
- large UI files:
  - `barakuda/shell/main_window.py` (only minimal controlled edits when explicitly approved)
  - `barakuda/devices/optical_tweezers/ui/panel.py`
  - `barakuda/devices/acquisition/ui/panel.py`
- existing validated OT analysis code:
  - OT pipeline/drag modules under `barakuda/devices/optical_tweezers/`

## 11. Suggested first implementation prompt

Copy-paste prompt for first tiny implementation:

```text
You are working on BARAKUDA.

Task type: very small implementation.
Goal: add two minimal launcher files for future split modes, without changing scientific logic.

Allowed files:
- main_acquisition.py (new)
- main_analysis.py (new)

Allowed reads:
- main.py
- barakuda/main.py

Forbidden:
- Do not edit any existing Python file.
- Do not change imports in existing files.
- Do not modify registry logic.
- Do not modify UI or scientific logic.

Expected output:
- Two new launcher files that each create QApplication and open ShellMainWindow.
- Keep behavior equivalent to current launcher (no mode filtering yet).

Checks:
- Both files import successfully.
- Existing main.py behavior is untouched.
- Report changed files.

Stop condition:
- Stop if implementation requires editing existing Python files or more than 2 files total.
```

## 12. Acceptance checklist

- [x] Plan created.
- [x] No Python/application files edited.
- [x] Current startup flow described.
- [x] Acquisition responsibilities defined.
- [x] Analysis responsibilities defined.
- [x] Shared core defined.
- [x] Minimal implementation sequence defined.
- [x] First future implementation prompt included.
- [x] Risks and stop conditions included.

## 13. Recommended next task

**audit this split plan**

Reason: this plan is architecture-governing and touches sensitive startup/module-boundary assumptions; a quick audit before implementation reduces risk of unnecessary code churn and keeps CP01 changes narrowly scoped.

---

## Update 2026-05-12 — Device filtering plan before implementation

### Current validated state

- Shared startup helper exists in `barakuda/startup.py`.
- `app_mode` seam exists: `run_app(app_mode: str = "full")` → `ShellMainWindow(app_mode=app_mode)`.
- `self._app_mode` is stored in `ShellMainWindow.__init__` (line 51) but never read.
- `main_acquisition.py` calls `run_app(app_mode="acquisition")`.
- `main_analysis.py` calls `run_app(app_mode="analysis")`.
- No filtering has been implemented yet.

### Code facts (grounding from actual files)

**`barakuda/devices/registry.py`** (23 lines):
- `list_devices()` builds `[OT, AFM]` unconditionally, then appends Acquisition if the import succeeds.
- Takes no arguments. Returns `List[DeviceSpec]`.

**`barakuda/devices/base.py`** (23 lines):
- `DeviceSpec` is a `frozen=True` dataclass with exactly three fields:
  `device_id: str`, `display_name: str`, `create_panel: Callable[[], QWidget]`.
- No mode metadata exists on the spec.

**`barakuda/shell/main_window.py`** — relevant `__init__` sequence:
- Line 51: `self._app_mode = app_mode` — stored, not yet used.
- Line 65: `self._devices: list[DeviceSpec] = list_devices()` — full, unfiltered list.
- Lines 139–140: `device_combo` is populated by iterating `self._devices`.
- The natural filter seam is therefore between line 65 and line 139.

---

### 1. Desired device visibility by mode

| app_mode | Optical Tweezers | AFM | Acquisition |
|---|---|---|---|
| `"full"` | ✅ | ✅ | ✅ if available |
| `"acquisition"` | ❌ | ❌ | ✅ (required) |
| `"analysis"` | ✅ | ✅ | ❌ |

**Rationale:**

- `"full"` = current behavior unchanged. This is the default and must not regress.
- `"acquisition"` = camera/run-creation workflow only. OT/AFM analysis panels are irrelevant and their presence creates operator confusion in a lab capture context.
- `"analysis"` = offline processing. Acquisition hardware is not required and should not appear in the device list to avoid confusion on analysis-only machines.

No deviation from the proposed target is suggested by the current code. The `device_id` values in the registry (`"optical_tweezers"`, `"afm"`, `"acquisition"`) are stable string identifiers already used elsewhere in the shell, making them safe filter keys.

---

### 2. Candidate filtering locations

#### Option A — Filter `self._devices` in `ShellMainWindow.__init__` after `list_devices()`

**Likely edit:** `barakuda/shell/main_window.py` only.

**Mechanism:**
Insert a one-liner filter between line 65 and line 139:
```python
self._devices = _filter_devices_by_mode(self._devices, self._app_mode)
```
where `_filter_devices_by_mode` is a small private helper (same file or a small inline expression).

**Pros:**
- Touches exactly one file (`main_window.py`).
- Filter lives at the only place that knows both `app_mode` and `self._devices`.
- `list_devices()` contract is completely unchanged — no registry edit needed.
- `DeviceSpec` is completely unchanged — no base edit needed.
- Rollback = delete three lines.
- `app_mode="full"` path remains current behavior (no filtering applied).
- Filter logic is plain list comprehension — easy to read and test.

**Cons:**
- `main_window.py` is large (1930 lines) — any edit there requires care.
- Filter is not visible from the registry or the launcher; someone reading `list_devices()` cannot see that some devices are hidden in certain modes.

**Risk level:** **low** — one file, additive-only change, easily reverted.

---

#### Option B — Add `app_mode` argument to `list_devices(app_mode)`

**Likely edits:** `barakuda/devices/registry.py` **and** `barakuda/shell/main_window.py`.

**Mechanism:**
Change `list_devices()` to `list_devices(app_mode: str = "full")` and apply filter inside the registry. The shell then passes `self._app_mode` when calling it.

**Pros:**
- Filter is visible at the source of device composition (registry), which is conceptually clean.
- Callers know exactly what device set they will receive.

**Cons:**
- Changes the `list_devices()` public contract — any other call site that imports it would need auditing.
- Requires editing `registry.py`, which the AGENTS.md rules mark as a sensitive boundary.
- Two files change instead of one.
- Registry is currently small and correct — touching it for a UI concern is mixing layers.
- Makes `list_devices()` aware of UI/startup mode concepts it currently doesn't need to know.

**Risk level:** **medium** — two files, changes a public contract, mixes concerns.

---

#### Option C — Add `allowed_modes` metadata field to `DeviceSpec`

**Likely edits:** `barakuda/devices/base.py`, `barakuda/devices/registry.py`, all three device `device.py` spec builders (`optical_tweezers`, `afm`, `acquisition`), and `barakuda/shell/main_window.py`.

**Mechanism:**
Add `allowed_modes: tuple[str, ...]` or similar to `DeviceSpec`. Each device spec builder populates it. Shell filters `self._devices` by checking `app_mode in spec.allowed_modes`.

**Pros:**
- Mode constraints are declared alongside the device, which is architecturally expressive.
- Easy to extend if a future device has complex mode membership.

**Cons:**
- Touches the most files: `base.py` (dataclass change), `registry.py`, three device spec builders, and `main_window.py`.
- `DeviceSpec` is `frozen=True` — adding a field with a default requires care in Python dataclasses (non-default fields cannot follow default fields; would require `field(default=...)` or reordering).
- Breaks import-level assumptions for any code that constructs `DeviceSpec` directly.
- Over-engineered for a three-device, three-mode system.

**Risk level:** **high** — four or more files, breaks the frozen dataclass contract, unnecessary for current scale.

---

### 3. Recommended filtering location

**Recommended: Option A — Filter `self._devices` in `ShellMainWindow.__init__` after `list_devices()`.**

Reasons:
- Single-file change.
- `list_devices()` contract stays unchanged.
- `DeviceSpec` stays unchanged.
- The seam already exists (`self._app_mode` on line 51, `self._devices` on line 65, combo loop on line 139).
- Filter logic is a trivial list comprehension — easy to audit and roll back.
- `app_mode="full"` returns the list unmodified, preserving current behavior exactly.

---

### 4. Exact future implementation scope

**Target file: `barakuda/shell/main_window.py` only.**

After `self._devices: list[DeviceSpec] = list_devices()` (current line 65), insert:

```python
self._devices = _apply_mode_device_filter(self._devices, self._app_mode)
```

And add a small private module-level helper (or top-of-class staticmethod):

```python
def _apply_mode_device_filter(
    devices: list[DeviceSpec], app_mode: str
) -> list[DeviceSpec]:
    if app_mode == "acquisition":
        return [d for d in devices if d.device_id == "acquisition"]
    if app_mode == "analysis":
        return [d for d in devices if d.device_id != "acquisition"]
    # "full" or any unrecognised mode: return unmodified (preserves current behavior)
    return devices
```

**Constraints on the future implementation:**
- Do not change `list_devices()`.
- Do not change `DeviceSpec` or any device spec builder.
- Do not change scientific, timing, report, batch, or hardware logic.
- Do not change acquisition hardware code.
- `app_mode="full"` must produce identical behavior to current default launch.
- `app_mode="acquisition"` must produce exactly one device in the list (Acquisition).
  - If Acquisition is not importable, the list will be empty — this is a known risk (see section 6).
- `app_mode="analysis"` must exclude any device with `device_id == "acquisition"`.

---

### 5. Validation strategy

Use explicit interpreter: `&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe"`

**Step 1 — Compile:**
```
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -m py_compile barakuda/shell/main_window.py
```

**Step 2 — Import:**
```
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "from barakuda.shell.main_window import ShellMainWindow; print('import ok')"
```

**Step 3 — Headless filter inspection (preferred, no GUI launch):**

The filter function `_apply_mode_device_filter` can be extracted to module scope (not a method), making it importable and testable without instantiating `ShellMainWindow` or creating a `QApplication`. Validation command:

```
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "
from barakuda.devices.base import DeviceSpec
from barakuda.shell.main_window import _apply_mode_device_filter

def _mk(id_): return DeviceSpec(device_id=id_, display_name=id_, create_panel=lambda: None)
devs = [_mk('optical_tweezers'), _mk('afm'), _mk('acquisition')]

full = _apply_mode_device_filter(devs, 'full')
acq  = _apply_mode_device_filter(devs, 'acquisition')
ana  = _apply_mode_device_filter(devs, 'analysis')

assert [d.device_id for d in full] == ['optical_tweezers', 'afm', 'acquisition'], full
assert [d.device_id for d in acq]  == ['acquisition'], acq
assert [d.device_id for d in ana]  == ['optical_tweezers', 'afm'], ana
print('filter logic ok')
"
```

This test requires no `QApplication`, no real hardware, and no GUI window.

**Note on full GUI launch:** Do not launch the full GUI as part of automated validation. The compile + import + headless filter test is sufficient to confirm correctness without hardware.

---

### 6. Risks and stop conditions

| Risk | Mitigation |
|---|---|
| `app_mode="acquisition"` produces an empty device list if Acquisition import fails | Document as known; the shell will open with an empty combo — acceptable for a headless/analysis machine, but operator-facing message may be needed in a later task |
| `main_window.py` edit accidentally disturbs surrounding `__init__` logic | Change is additive-only (insert after line 65); surrounding lines are untouched |
| `list_devices()` call side effects unknown | `list_devices()` only imports device specs; the filter acts on the returned list, not on the call itself — safe |
| Scientific/timing/report code coupling | None — filter is purely on `DeviceSpec.device_id` strings before any device panel is constructed |
| Registry contract change needed | Not needed under Option A — stop if this changes |

**Hard stop conditions:**

- Stop if filtering requires editing device implementation internals.
- Stop if `registry.py` or `list_devices()` must change (unexpected coupling found).
- Stop if `ShellMainWindow.__init__` needs broad refactor to accommodate the filter.
- Stop if scientific, timing, report, batch, or hardware logic would be touched.
- Stop if Acquisition mode raises an unhandled import-time error that prevents the shell from constructing when `get_acq_spec` fails (currently handled by `try/except` in registry — verify this remains safe).
- Stop if headless filter test cannot be written without a real `QApplication`.

---

### 7. Future implementation prompt

```text
You are working on the BARAKUDA repository.

Task type: tiny implementation.

Goal:
Implement device filtering by app_mode inside ShellMainWindow.__init__.
This is the filtering step planned in docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN.md
Update 2026-05-12.

Current validated state:
- app_mode seam exists in run_app() and ShellMainWindow.__init__.
- self._app_mode is stored (line 51) but never read.
- self._devices = list_devices() is called (line 65), unfiltered.
- device_combo is populated from self._devices (lines 139-140).
- No filtering exists yet.

Allowed Python files to edit:
- barakuda/shell/main_window.py

Forbidden actions:
- Do not edit barakuda/startup.py.
- Do not edit main.py, barakuda/main.py, main_acquisition.py, main_analysis.py.
- Do not edit barakuda/devices/registry.py or list_devices().
- Do not edit barakuda/devices/base.py or DeviceSpec.
- Do not edit device spec builders (optical_tweezers, afm, acquisition device.py files).
- Do not add filtering logic.
- Do not change scientific logic.
- Do not change timing logic.
- Do not change report generation.
- Do not change batch summary logic.
- Do not change acquisition hardware code.
- Do not change UI layout.
- Do not create new documentation files.
- Do not run git add. Do not commit.

Implementation requirements:

1. Add a module-level private function (not a method) in barakuda/shell/main_window.py:

def _apply_mode_device_filter(
    devices: list[DeviceSpec], app_mode: str
) -> list[DeviceSpec]:
    if app_mode == "acquisition":
        return [d for d in devices if d.device_id == "acquisition"]
    if app_mode == "analysis":
        return [d for d in devices if d.device_id != "acquisition"]
    return devices

Place it near the top of the module, after imports, before the class definition.

2. In ShellMainWindow.__init__, after the existing line:
    self._devices: list[DeviceSpec] = list_devices()
Insert exactly:
    self._devices = _apply_mode_device_filter(self._devices, self._app_mode)

3. No other changes.

Validation commands:

Compile:
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -m py_compile barakuda/shell/main_window.py

Import:
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "from barakuda.shell.main_window import ShellMainWindow; print('import ok')"

Headless filter test:
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "
from barakuda.devices.base import DeviceSpec
from barakuda.shell.main_window import _apply_mode_device_filter
def _mk(id_): return DeviceSpec(device_id=id_, display_name=id_, create_panel=lambda: None)
devs = [_mk('optical_tweezers'), _mk('afm'), _mk('acquisition')]
full = _apply_mode_device_filter(devs, 'full')
acq  = _apply_mode_device_filter(devs, 'acquisition')
ana  = _apply_mode_device_filter(devs, 'analysis')
assert [d.device_id for d in full] == ['optical_tweezers', 'afm', 'acquisition'], full
assert [d.device_id for d in acq]  == ['acquisition'], acq
assert [d.device_id for d in ana]  == ['optical_tweezers', 'afm'], ana
print('filter logic ok')
"

Do not launch the full GUI.

Documentation update after successful validation:

Update docs/agent_tasks/CP01_AGENT_QUEUE.md: add Task 008.
Update docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN.md: append dated section.
Do not create new documentation files.

Stop conditions:
- Stop if more than 1 Python file needs editing.
- Stop if registry.py or list_devices() must change.
- Stop if DeviceSpec or device spec builders must change.
- Stop if ShellMainWindow requires broad refactor.
- Stop if scientific/timing/report/batch/hardware logic would be touched.
- Stop if headless filter test cannot be written without QApplication.
```

---

---

## Update 2026-05-12 — Device filtering plan audit

### 1. Files inspected

| File | Purpose |
|---|---|
| `barakuda/shell/main_window.py` | Primary edit target; verified seam location, empty-list paths |
| `barakuda/devices/registry.py` | Confirmed `list_devices()` signature and acquisition try/except |
| `barakuda/devices/base.py` | Confirmed `DeviceSpec` frozen dataclass fields |
| `barakuda/startup.py` | Confirmed `run_app(app_mode)` → `ShellMainWindow(app_mode=app_mode)` |
| `main_acquisition.py` | Confirmed `run_app(app_mode="acquisition")` |
| `main_analysis.py` | Confirmed `run_app(app_mode="analysis")` |
| `docs/agent_tasks/ACQUISITION_ANALYSIS_SPLIT_PLAN.md` | Plan under audit |
| `docs/agent_tasks/CP01_AGENT_QUEUE.md` | Task sequence context |
| `docs/agent_tasks/STARTUP_CONSTRUCTOR_SEAM_REPORT.md` | Seam history |
| `AGENTS.md` | Governance rules |

---

### 2. Safety check

| Question | Answer |
|---|---|
| Was any Python/application code changed? | **No.** |
| Was any new document created? | **No.** |
| Was any filtering implemented? | **No.** |
| Were any risky git actions performed? | **No.** |

---

### 3. Recommended location review

**Recommendation under audit:** Option A — filter `self._devices` in `ShellMainWindow.__init__` after `list_devices()` (line 65), before the `device_combo` loop (lines 139–140).

| Question | Answer |
|---|---|
| Is this the safest filtering location? | **Yes.** The seam is precisely between line 65 (list assigned) and line 139 (combo populated). The filter inserts after the list is built, before it is consumed by any UI. No surrounding logic is disturbed. |
| Does it avoid changing `registry.py` / `list_devices()`? | **Yes.** `list_devices()` is called with no arguments and its return value is filtered in the shell, not inside the registry. |
| Does it avoid changing `DeviceSpec`? | **Yes.** The filter reads only `d.device_id`, which is an existing frozen field. |
| Does it avoid changing device implementations? | **Yes.** No device module is touched. |
| Does it preserve `full` mode behavior? | **Yes.** The helper returns the original list unmodified for `app_mode="full"`. |
| Is it easy to roll back? | **Yes.** Removing the one-line call and the ~8-line module-level helper restores the original state exactly. |
| Is there a better alternative? | **No.** Options B and C both require more files and more risk for no benefit at current scale. Option A is unambiguously the correct choice. |

---

### 4. Helper design review

**Helper under audit:**
```python
def _apply_mode_device_filter(
    devices: list[DeviceSpec], app_mode: str
) -> list[DeviceSpec]:
    if app_mode == "acquisition":
        return [d for d in devices if d.device_id == "acquisition"]
    if app_mode == "analysis":
        return [d for d in devices if d.device_id != "acquisition"]
    return devices
```

| Question | Answer |
|---|---|
| Is the logic correct for `full`/`acquisition`/`analysis`? | **Yes.** `acquisition` keeps only the acquisition device. `analysis` excludes it. `full` falls through to `return devices` — returns all. |
| Is returning the original list object for unknown modes acceptable? | **Yes, for now.** No code path mutates `self._devices` after construction; it is only iterated. A mutating caller would be a separate bug. |
| Should unknown modes raise an error instead? | **Not in this task.** Silent pass-through to `"full"` behavior is the safest default for a first implementation. An unknown-mode warning can be added in a later task if needed. Raising here would create a hard failure that could block future experimentation. |
| Is module-level placement good for headless testing? | **Yes.** A module-level function can be imported without instantiating `ShellMainWindow` or creating a `QApplication`. This is the key design property that makes headless validation possible. |
| Is there a risk from returning the same list object for `"full"`? | **No practical risk.** `self._devices` is never reassigned or mutated after `__init__` completes (confirmed by reading the file). The combo loop and `_set_device_by_index` only read from it. If this is ever a concern, `return list(devices)` can be added later as a defensive hardening step. It is not required now. |
| Should the function return `list(devices)` for defensive copying? | **Recommended as a minor improvement, but not blocking.** The plan prompt should suggest it as optional; the implementation agent may choose either. |
| Is using `device_id` strings acceptable? | **Yes.** `device_id` values (`"optical_tweezers"`, `"afm"`, `"acquisition"`) are already used as stable string keys throughout `_activate_device()` and the shell method selectors. They are the established identity token for devices in this codebase. |

**Minor improvement suggestion (non-blocking):** Consider adding a docstring to `_apply_mode_device_filter` so it is self-documenting when someone reads `main_window.py` in isolation. Not required for the first implementation.

---

### 5. Empty acquisition list risk

**Risk:** If `get_acq_spec` fails to import (hardware not available), `list_devices()` returns only `[OT, AFM]`. After the acquisition filter, `app_mode="acquisition"` would produce `[]` — an empty device list.

**Code paths verified:**

- `__init__` line 139–140: iterating `[]` is safe — the combo is simply left empty. No exception.
- `showEvent` line 342: calls `_set_device_by_index(0)`.
- `_set_device_by_index` line 597: guard is `if idx < 0 or idx >= len(self._devices): return`. With `len([]) == 0`, the condition `0 >= 0` is **True** → the method returns immediately. **No crash. No device is activated.**

| Question | Answer |
|---|---|
| Is this acceptable for the first filtering implementation? | **Yes.** The shell initialises safely with an empty combo. The window opens. No exception is raised. |
| Could it break `ShellMainWindow` initialization? | **No.** Verified from code: the combo loop and `_set_device_by_index` both handle empty lists correctly. |
| Does current UI code assume at least one device? | **No hard assumption found** in the `__init__` path. The combo is populated by a loop and the first device is activated only via `showEvent`→`_set_device_by_index(0)`, which has the empty-guard. |
| Should implementation stop if empty list handling is unsafe? | **No stop needed.** The existing guard makes it safe. |
| Should a user-facing warning be planned later? | **Yes — recommended as a follow-up task.** An operator launching `main_acquisition.py` on a machine without Acquisition hardware should see a clear message rather than a silent empty combo. This is a UX improvement, not a correctness blocker. |
| Should the first implementation include empty-list handling, or is that a separate task? | **Separate task.** The first filtering implementation should do only the filter. A user-visible empty-state message is a distinct, narrow follow-up task and must not be mixed in. |

---

### 6. Validation strategy review

**Proposed strategy:**
1. Compile `barakuda/shell/main_window.py`
2. Import `ShellMainWindow`
3. Run headless test of `_apply_mode_device_filter` using fake `DeviceSpec` objects
4. Do not launch full GUI

| Question | Answer |
|---|---|
| Is this sufficient for the first filtering step? | **Yes.** It verifies syntax, importability, and all three filter paths without hardware. |
| Does the headless test avoid `QApplication`? | **Yes.** `_apply_mode_device_filter` is a module-level function that only manipulates a Python list. No Qt objects are created in the test. |
| Are fake `DeviceSpec` objects safe here? | **Yes.** `DeviceSpec` is a plain frozen dataclass. `create_panel=lambda: None` is never called by the filter. The fake objects are sufficient to test `device_id` string matching. |
| Should validation also import `main_acquisition` and `main_analysis`? | **Yes — recommended addition.** This verifies the full launch chain compiles correctly after the edit and confirms no import-time side effect was introduced. Add: `import main_acquisition; import main_analysis; print('launchers still ok')` |
| Should validation include a check that `full` mode preserves original device order? | **Yes — the headless test already does this** (the `full` assert checks all three IDs in order). This is correctly included in the existing proposed validation command. |

**One minor addition to the validation strategy:** add an import check for both launchers after the filter step. Full recommended validation sequence:

```
# Step 1 — Compile
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -m py_compile barakuda/shell/main_window.py

# Step 2 — Import ShellMainWindow
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "from barakuda.shell.main_window import ShellMainWindow; print('ShellMainWindow import ok')"

# Step 3 — Headless filter logic test
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "
from barakuda.devices.base import DeviceSpec
from barakuda.shell.main_window import _apply_mode_device_filter
def _mk(id_): return DeviceSpec(device_id=id_, display_name=id_, create_panel=lambda: None)
devs = [_mk('optical_tweezers'), _mk('afm'), _mk('acquisition')]
full = _apply_mode_device_filter(devs, 'full')
acq  = _apply_mode_device_filter(devs, 'acquisition')
ana  = _apply_mode_device_filter(devs, 'analysis')
assert [d.device_id for d in full] == ['optical_tweezers', 'afm', 'acquisition'], full
assert [d.device_id for d in acq]  == ['acquisition'], acq
assert [d.device_id for d in ana]  == ['optical_tweezers', 'afm'], ana
print('filter logic ok')
"

# Step 4 — Launcher import chain
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "import main_acquisition; import main_analysis; print('launchers still ok')"
```

---

### 7. Future implementation prompt review

**Issue found:** The future implementation prompt in section 7 of the previous plan update contains this line in the Forbidden actions list:

> `- Do not add filtering logic.`

This directly contradicts the task goal, which is to add the `_apply_mode_device_filter` helper and one call inside `__init__`. An implementation agent reading this prompt literally would be unable to complete the task.

**Correction required:**

Replace:
```
- Do not add filtering logic.
```
With:
```
- Do not add any filtering beyond the minimal _apply_mode_device_filter described in Implementation requirements.
```

All other aspects of the prompt are reviewed below:

| Aspect | Assessment |
|---|---|
| Allowed files narrow enough? | **Yes.** Only `barakuda/shell/main_window.py`. |
| Forbidden files strict enough? | **Yes.** All registries, device specs, launchers, and scientific modules are explicitly forbidden. |
| Validation commands appropriate? | **Yes**, with the one addition of launcher import check noted in section 6. |
| Documentation update target is existing docs only? | **Yes.** `CP01_AGENT_QUEUE.md` and `ACQUISITION_ANALYSIS_SPLIT_PLAN.md` only. |
| Stop conditions strict enough? | **Yes.** Single-file limit, registry/DeviceSpec/device-module guards, scientific/hardware guards are all present. |

---

### 8. Recommended corrections before implementation

**One required correction:**

In the future implementation prompt (section 7 of Update 2026-05-12 — Device filtering plan before implementation), in the Forbidden actions list:

**Current (incorrect):**
```
- Do not add filtering logic.
```

**Corrected:**
```
- Do not add any filtering beyond the minimal _apply_mode_device_filter described in Implementation requirements.
```

**One recommended addition (non-blocking):**

Add Step 4 launcher import check to the validation commands in the future implementation prompt:
```
# Step 4 — Launcher import chain
&"$env:USERPROFILE\anaconda3\envs\barakuda\python.exe" -c "import main_acquisition; import main_analysis; print('launchers still ok')"
```

**All other plan content is correct.** No Python changes required to fix these.

---

### 9. Final audit verdict

**Verdict: approved for tiny implementation — with one prompt correction.**

The filtering approach (Option A, module-level helper, single-file edit) is architecturally sound and grounded in verified code behavior. The empty-list risk is safe due to the existing guard in `_set_device_by_index`. The headless validation strategy is correct and avoids hardware. The only issue is a self-contradicting line in the future implementation prompt ("Do not add filtering logic") which must be corrected in the next task prompt before the implementation agent sees it.

---

### 10. Recommended next task

**Implement device filtering in `ShellMainWindow` only.**

The plan is audited and approved. The filtering logic is minimal (one helper function, one call site). The validation strategy is clear and hardware-free. The only prerequisite is that the implementation task prompt corrects the self-contradicting forbidden-actions line identified in section 8 — which the user should apply when composing the next prompt.

---

### Update 2026-05-12 — Device filtering implemented

- File changed: `barakuda/shell/main_window.py` only.
- Helper added: `_apply_mode_device_filter(devices, app_mode)` at module scope, before the class definition.
- Filtering behavior:
  - `app_mode="full"` → returns `devices` unmodified (current behavior preserved).
  - `app_mode="acquisition"` → keeps only devices where `device_id == "acquisition"`.
  - `app_mode="analysis"` → excludes devices where `device_id == "acquisition"`.
  - unknown mode → behaves like `"full"` (safe fallthrough).
- Call site: one line inserted in `__init__` immediately after `self._devices = list_devices()`.
- `registry.py` / `list_devices()` not changed.
- `DeviceSpec` and `base.py` not changed.
- No device spec builders changed.
- No scientific, timing, report, batch, or hardware logic touched.
- Validation commands and results:
  - Compile `barakuda/shell/main_window.py` → exit 0 (pass).
  - Import `ShellMainWindow` → "ShellMainWindow import ok" (pass).
  - Headless filter assertions (PowerShell here-string) → "filter logic ok" (pass).
  - Launcher import → "launchers still ok" (pass).
- Next safe step: add startup/mode smoke tests or perform manual GUI sanity check for full/acquisition/analysis launch modes.


### Update 2026-05-12 — startup/mode smoke tests

- Test file created: `tests/test_startup_modes.py`.
- Tested filter modes:
  - `full` — all devices preserved, original order and list object preserved.
  - `acquisition` — only acquisition device kept; empty-list case (no acquisition importable) also tested.
  - `analysis` — acquisition device excluded; no-acquisition-in-list case also tested.
  - `unknown` — safe fallthrough to full list verified.
- Launcher import coverage: `main`, `barakuda.main`, `main_acquisition`, `main_analysis`, `barakuda.startup` — all import-tested without calling `main()` or `run_app()`.
- No `QApplication` created. No GUI launched. No hardware required.
- Validation results:
  - Compile `tests/test_startup_modes.py` → exit 0 (pass).
  - `pytest tests/test_startup_modes.py -q` → 12 passed, 0 failed, 6 warnings in 4.02s.
  - Warnings are pre-existing SWIG `DeprecationWarning` from hardware imports — unrelated to these tests.
- Next safe step: manual GUI sanity check for full/acquisition/analysis launch modes.

### Update 2026-05-12 — manual GUI sanity check passed

- `main.py` launched successfully as full BARAKUDA mode; dropdown shows the complete available device set.
- `main_acquisition.py` launched successfully as BARAKUDA Acquisition solo mode; acquisition solo mode works.
- `main_analysis.py` launched successfully as BARAKUDA Analysis solo mode; analysis solo mode works.
- No crashes or visible startup errors were observed in any mode.
- Current split goal is functionally validated at GUI sanity-check level.
- Remaining future work: packaging/entry points, better operator-facing naming, optional empty-acquisition warning if hardware is absent, deeper integration tests if needed.


