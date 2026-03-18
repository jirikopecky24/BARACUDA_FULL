# OT DRAG Architecture Note

## 1. Current mode & goals (NOW scope)

- **Current DRAG mode**: `constant_velocity` steady-state drag for simple Newtonian liquids (water/glycerol-like).
- **Current main scientific output**: viscosity \(\eta\) estimated from a steady offset under constant-velocity stage motion.
- **Division of roles**:
  - **Brownian**: provides trap stiffness \(\kappa\) under the same optical and bead conditions.
  - **DRAG**: provides viscosity \(\eta\) using \(\kappa\), steady offset \(x\) and actual stage speed \(v\).
- **Stage metadata** (JSON + trace) are first-class experimental data, not auxiliary files.
- **Future hydrogel / active microrheology support** is a **future extension**, not a current deliverable.
- **Tracking** is shared OT infrastructure (video → trajectory), **not** Brownian logic.
- Everything after tracked signal creation (alignment, windows, offsets, physics, exports) is **owned by `drag/`**.


## 2. NOW scope vs FUTURE scope

### NOW scope

For a single RAW run folder (one video + matching stage files):

1. Load run assets:
   - `<basename>.raw`
   - `<basename>_meta.json`
   - `<basename>_timestamps.csv`
   - `<basename>_stage.json`
   - `<basename>_stage_trace.csv`
2. Internally run shared OT tracking to generate `<basename>_trajectory.csv`.
3. Load stage metadata and stage trace.
4. Align stage motion to the tracked bead signal via onset detection.
5. Select baseline and steady-state windows.
6. Compute steady-state offset (raw + stage-signed).
7. Use **actual measured stage speed**, not commanded speed.
8. If \(\kappa\) is available (Brownian), reconstruct drag force and **viscosity \(\eta\)**.
9. Export:
   - trajectory CSV,
   - drag summary JSON,
   - drag summary CSV,
   - drag diagnostic plot.

**Primary physics path (NOW):**

\[
\kappa x = 6 \pi \eta R v
\Rightarrow
\eta = \frac{\kappa x}{6 \pi R v}
\]

where:
- \(\kappa\): Brownian-derived stiffness (N/m),
- \(x\): steady-state stage-consistent offset (µm),
- \(R\): bead radius (m),
- \(v\): actual stage speed (µm/s → m/s).

DRAG also reports:
- offset (raw + stage-signed, in px/µm),
- actual speed (user units, and µm/s when stage scale is known),
- drag force,
- QC/validity flags and alignment quality.

### FUTURE scope (not implemented now)

Future DRAG/active OT protocols will extend beyond simple constant-velocity drag:

- **Protocols**:
  - `constant_velocity` (extended, more QC + rich diagnostics),
  - `step_response`,
  - `oscillatory`,
  - `multi_segment` / custom protocol,
  - `creep` / relaxation,
  - `frequency_sweep`.
- **Physics goals**:
  - viscoelastic response,
  - relaxation times,
  - compliance-like metrics,
  - \(G'(\omega)\), \(G''(\omega)\),
  - future hydrogel-specific metrics.

These protocols must build on the same **motion-aware and stage-aware foundations** as DRAG:
- stage protocol + trace + tracked signal → motion interpretation layer,
- force reconstruction → viscoelastic analysis.


## 3. Shared OT infrastructure (NOT Brownian-specific)

Shared OT core is the technical layer that both Brownian and DRAG can use:

- RAW/video loading (`VideoReader`).
- Acquisition timestamps loading (CSV).
- Particle tracking:
  - tracking methods (`TrackingMethod`),
  - polarity detection (`choose_tracking_polarity`),
  - ROI management (`Roi`, `roi_follow_center`),
  - detectors (`track_particle`, etc.).
- Trajectory generation:
  - minimal trajectory CSV schema (`frame`, `t_s`, `x_px`, `y_px`, `quality`, + optional derived cols).
- Common QC utilities and optional drift correction as generic post-process.

**Key point**: tracking & trajectory generation are **shared OT infrastructure**, not Brownian logic.


## 4. DRAG-specific responsibilities

Once a tracked signal exists, everything downstream for DRAG is fully owned by `drag/`:

- Stage metadata loading:
  - `<basename>_stage.json` → axis, direction, travel, duration, actual_speed_user_s, sign_stage_to_image_x/y, optional `stage_um_per_unit`.
- Stage trace loading:
  - `<basename>_stage_trace.csv` → events (script start/stop, motion start/stop, holds).
- Motion interpretation:
  - stage axis + direction,
  - motion_start_stage_s / motion_stop_stage_s,
  - future protocol/segment metadata.
- Alignment stage ↔ video:
  - onset detection from tracked signal (baseline, robust sigma, hold time),
  - manual offset fallback.
- Signal analysis:
  - baseline and steady windows,
  - medians, offsets (raw and stage-signed),
  - baseline and steady noise metrics.
- Force reconstruction:
  - drag force from \(\kappa x\) or \(6\pi \eta R v\).
- Physics layer:
  - NOW: \(\eta\) from constant-velocity steady-state regime,
  - FUTURE: transient/oscillatory/viscoelastic metrics.
- QC and diagnostics:
  - QC flags and warnings,
  - diagnostic plots.
- Exports:
  - DRAG-specific summary and plots only (no Brownian report structures).


## 5. Strict separation from Brownian physics

In new DRAG workflows:

- Do **NOT** use Brownian-specific physics as DRAG core:
  - no PSD/Welch as DRAG physics kernel,
  - no Lorentzian fit as DRAG physics,
  - no equipartition-based DRAG stiffness.
- Do **NOT** reuse old legacy drag logic that assumes “second half median”.
- Do **NOT** write DRAG physics into Brownian-oriented export structures:
  - no DRAG metrics inside Brownian `ot_summary.json`,
  - no mixing into Brownian report layouts.

Brownian and DRAG share only the **tracking/trajectory/QC infrastructure**, not the physics.


## 6. Stage metadata as first-class data

Stage JSON and stage trace are **core parts of the experiment**, not side artifacts:

- Required inputs for DRAG:
  - `axis` (x / y),
  - `direction`,
  - `actual_travel_user`,
  - `actual_motion_duration_s`,
  - `actual_speed_user_s` (or derived from travel/duration),
  - `sign_stage_to_image_x`, `sign_stage_to_image_y`,
  - `motion_start_stage_s`, `motion_stop_stage_s`,
  - optional `stage_um_per_unit`.

In the future, stage protocol definitions (type, segments, parameters) are expected to be recorded as part of acquisition datasets:
- video metadata,
- stage protocol definition,
- stage trace,
- stage events.

DRAG’s architecture is designed now to treat these stage inputs as first-class and to support richer motion protocols later.


## 7. Physics: kappa / eta relationship (NOW)

The main practical physics path for current DRAG:

- **Brownian** calibration:
  - provides \(\kappa\) for each axis in N/m under the same optical, bead and medium conditions.
- **DRAG** constant-velocity experiment:
  - uses that \(\kappa\) and steady-state offset \(x\) and stage speed \(v\) to estimate \(\eta\).

Formula:

\[
\kappa x = 6 \pi \eta R v
\quad\Rightarrow\quad
\eta = \frac{\kappa x}{6 \pi R v}
\]

Inputs required for absolute \(\eta\):
- \(x\): steady-state stage-consistent offset in µm,
- \(v\): actual stage speed in µm/s,
- \(R\): bead radius in m,
- \(\kappa\): Brownian-derived stiffness in N/m,
- `um_per_px`: same image scale as Brownian (for the same setup), with explicit override allowed,
- `stage_um_per_unit`: stage scale to convert from user units/s to µm/s.

If any of these key inputs is missing:
- DRAG still returns **signal-level** and **kinematics-level** results,
- `physics_status` is marked as `"incomplete_inputs"`,
- absolute \(\eta\) and force are not reported.

**Primary NOW output**: \(\eta\) (viscosity) when inputs are complete.  
**Secondary path**: known \(\eta\) + DRAG kinematics may be used to recompute \(\kappa\) (optional).


## 8. Result levels

DRAG results are layered:

1. **Tracking-level**:
   - existence and validity of `trajectory.csv`,
   - frame/time axis, raw x/y signals, basic QC,
   - this layer is shared with Brownian but not owned by it.
2. **Signal- & kinematics-level (DRAG)**:
   - alignment_status, windows, baseline/steady positions,
   - offsets (raw and stage-signed),
   - actual_travel_user, actual_motion_duration_s,
   - actual_speed_user_s, optional actual_speed_um_s,
   - SNR, noise, alignment quality and steady-duration checks.
3. **Physics-level (DRAG)**:
   - drag_force_n (and drag_force_pn when useful),
   - kappa_n_per_m (when provided),
   - eta_pa_s (when inputs are complete),
   - `physics_status` reflecting readiness of physics outputs.

These levels must remain conceptually separate in both code and exports.


## 9. Future protocols & rheology (not NOW)

Future DRAG/active OT features will extend on top of this architecture:

- **Protocols**:
  - `constant_velocity` (richer QC, multi-segment),
  - `step_response` (time-domain transient analysis),
  - `oscillatory` (single frequency, multi-frequency sweeps),
  - `creep` / relaxation experiments,
  - `frequency_sweep` protocols (broadband rheology).

- **Rheology outputs**:
  - viscoelastic response,
  - relaxation times and spectra,
  - compliance and modulus metrics,
  - storage and loss moduli \(G'(\omega)\) and \(G''(\omega)\).

All of these must:
- use the same **motion-aware foundations** (stage protocol + trace + tracked signal),
- consume stage protocol data and motion metadata,
- remain method-specific layers on top of shared tracking infrastructure.


## 10. Non-goals for NOW scope

For the initial DRAG implementation, the following are **explicitly out of scope**:

- GUI integration.
- Acquisition / dataset browser integration.
- Batch processing / multi-run orchestration.
- Full \(G'(\omega)\) / \(G''(\omega)\) computation.
- Young’s modulus or other solid-mechanics metrics.
- Any claim that current constant-velocity DRAG already provides full viscoelastic characterization.

Current constant-velocity DRAG for water/glycerol is **not** yet a full viscoelastic characterization method.  
It is a strong steady-state active drag method with viscosity as the main physics output, while future extensions may add transient and oscillatory rheology metrics.


## 11. Architectural principles for further development

- DRAG is a **first-class OT method**, not a Brownian hack or post-hoc script.
- Shared tracking/trajectory infrastructure is OT core; Brownian and DRAG sit on top with their own physics/analysis layers.
- DRAG-specific logic (stage-aware motion interpretation, offsets, force, \(\eta\), QC, exports) must stay within `drag/`.
- New active protocols (step, oscillatory, creep, hydrogels) must:
  - reuse the same tracking and stage-aware foundations,
  - add their own analysis/physics modules without entangling with Brownian physics.

