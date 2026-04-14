# OT Brownian/Drag Mode Sync Audit

## Reproduction path

Observed chain that can desync UI method and runtime metadata:

1. User switches top-bar OT method to `Drag`.
2. `main_window` calls `set_calibration_mode("Drag")` on panel.
3. Per-item params may still contain stale `postprocess.calibration_mode="Brownian"` if no other widget change triggers `value_changed`.
4. `OTRunWorker.MockPanel` merges per-item postprocess over fallback snapshot, so stale item mode can override current UI mode.
5. `BatchController` reads `calibration_mode` from merged postprocess snapshot and separately writes `postprocess.physics_mode` defaulting to `BROWNIAN` when `physics_mode` key is missing.

Result: user-visible mode and runtime/audit mode can diverge, especially after repeated Brownian/Drag toggles.

## Root causes

- Missing immediate persistence on method-combo mode switch.
- Runtime merge precedence favored stale per-item `calibration_mode`.
- `physics_mode` in run metadata was not deterministically derived from effective calibration mode.

## Guardrail requirements

- Carry both requested and effective mode into runtime metadata.
- Force runtime mode from current UI snapshot for the run.
- Emit a warning when stale item mode had to be overridden.
