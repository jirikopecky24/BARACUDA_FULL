# Active Umbrella DRAG — Offline Implementation Note

## NOW (offline-first deliverables)

### 1) Stage-aware constant-velocity DRAG hardening (DRAG v1 foundation)
- `drag/` is the single source of truth for stage-aware alignment and windowing (onset detection from tracked signal + stage trace timing).
- Alignment diagnostics are now part of the structured result (`DragAnalysisResult.alignment_diagnostics`) and are exported as:
  - `{basename}_drag_summary.json` / `{basename}_drag_summary.csv` (QC-aligned summary fields)
  - optional `{basename}_alignment_diagnostics.json` (full candidate onset lists)
- Alignment debug plot remains opt-in via `DragAnalysisConfig.export_alignment_debug_plot`.

### 2) Active umbrella architecture under `drag/active_umbrella/`
- Protocol family exists conceptually and in code:
  - `constant_velocity` (delegates to DRAG v1 / stage-aware constant-velocity analysis)
  - `oscillatory` (implemented offline scaffolding: cycle segmentation, amplitude + phase lag estimation)
  - `step_response` (implemented as lightweight transient validation scaffold)
- Runner entrypoint:
  - `analyze_active_umbrella_run(run_dir, ActiveUmbrellaConfig, trajectory_path=None)`

### 3) Oscillatory scaffolding (diploma target mode)
- Protocol schema: `OscillatoryProtocolConfig`
  - frequency + drive amplitude source (explicit config or stage `protocol_params`)
  - cycle segmentation parameters (steady_start_cycles, max_cycles_to_use, min_samples_per_cycle)
  - baseline subtraction mode
- Analysis outputs:
  - per-cycle amplitude + phase
  - averaged phase lag (phasor-mean) and averaged amplitude
  - packaging of a complex-response placeholder for future mapping into `G'(omega)` / `G''(omega)`

### 4) Synthetic/offline test harness (no new lab data required)
- `drag/synthetic/harness.py` generates synthetic run folders that satisfy the DRAG loader contract:
  - dummy `{basename}.raw` (not used for analysis)
  - `{basename}_meta.json`
  - `{basename}_timestamps.csv`
  - `{basename}_stage.json` (including optional oscillatory protocol params)
  - `{basename}_stage_trace.csv`
  - `{basename}_trajectory.csv`
- Self-tests cover:
  - constant-velocity DRAG physics consistency (eta from known kappa + offset + stage speed)
  - oscillatory phase/amplitude recovery on synthetic sinusoidal response

### 5) Viscoelastic backend scaffolding
- `drag/viscoelastic/models.py` provides complex modulus models and storage/loss splitting:
  - Maxwell
  - Kelvin-Voigt
  - SLS / Zener
  - Jeffreys (via series compliance composition)
- Also includes time-domain API placeholders (currently scaffolded; suitable for future integration).

## DIPLOMA TARGET (what the oscillatory pipeline should enable)
- From a single-frequency oscillatory active drag run:
  - extract stable cycle-averaged response amplitude
  - extract stable cycle-averaged phase lag
  - package results as frequency-domain targets ready for a future mapping into `G*(omega)`, and later `G'(omega)` / `G''(omega)`
- Offline verification must be the default:
  - new segmentation / fitting algorithms can be validated against synthetic truth parameters
  - only after offline confidence should real lab data be used for calibration/validation

## FUTURE (requires real stage protocol metadata + physics validation)
- Parse and standardize oscillatory/step protocol metadata recorded by acquisition (stage protocol definitions).
- Integrate a validated motion-to-driving reference model (stage position vs image axis) for better phase fidelity.
- Connect oscillatory measured complex response to viscoelastic models with agreed microrheology geometry.
- Add full viscoelastic claim pipeline:
  - compute `G'(omega), G''(omega)` and confidence intervals
  - validate against known standards / reference fluids

