# Acquisition Motion DRAG — Design Note

Internal reference document for the `test/acq-motion-drag-mvp` branch.
Return here when uncertain about scope, boundaries, or architecture decisions.

---

## 1. NOW Scope

Minimal, functional synchronization of stage motion with Basler camera recording
for the **constant_velocity_drag** DRAG experiment (diploma thesis).

Concrete deliverables:
- One **Motion section** added to `AcquisitionPanel` (Enable + motion parameters).
- One synchronized run mode: **Record + Motion**.
- Five output files in `runs/acquisition/<item_id>/acquisition/`:
  - `video.raw`
  - `video_meta.json`
  - `video_timestamps.csv`
  - `<basename>_stage.json`
  - `<basename>_stage_trace.csv`
- Stage event times are in the same **run clock domain** as orchestration (`run_t0`).
- DRAG pipeline can load the dataset with no manual alignment.

---

## 2. FUTURE Scope

Do not implement now. Design must not block these future directions:

- Additional motion modes: `step_response`, `oscillatory`, `multi_segment`, `frequency_sweep`.
- Active microrheology workflows.
- Hydrogel viscoelastic analysis: transient response, G'(ω), G''(ω), compliance, relaxation.
- Multi-axis orchestration.
- Full stage platform (home/stop/emergency).
- Custom protocol editor.
- Frequency sweep acquisition UI.

---

## 3. Acquisition Responsibility

Acquisition **owns**:
- Start / stop recording.
- Establishing and owning the shared **run clock** (`run_t0 = time.perf_counter()`).
- Motion enable / disable (user config).
- Triggering the motion recipe at the right time in the run sequence.
- Logging all orchestration events (recording_start, pre_hold_*, motion_start/stop, post_hold_*, recording_stop) with timestamps in the run clock domain.
- Storing all outputs into a single canonical run folder.
- Writing `<basename>_stage.json` and `<basename>_stage_trace.csv`.

Acquisition **must NOT** know about:
- Brownian physics.
- Drag force or viscosity.
- Trap stiffness κ.
- Rheology models.
- G', G'' or any microrheology interpretation.

---

## 4. Motion Layer Responsibility

The motion layer (`barakuda/devices/acquisition/motion/`) owns:
- The abstract stage interface (`AbstractStage`).
- The XIMC hardware backend (`XimcStage`) with lazy pyximc import.
- The `constant_velocity_drag` recipe: parameters (axis, direction, travel, speed, accel, decel)
  and the concrete command sequence to execute it.
- Reporting actual motion outcome (actual_travel, actual_duration, actual_speed).
- The `StageTraceRecorder`: accepts events with timestamps (from the shared `run_t0`),
  optionally stores sparse position/velocity samples, writes the trace CSV.

The motion layer **must NOT** know about:
- Video recording internals.
- DRAG physics.
- Bead tracking.
- Any analysis pipeline.

---

## 5. Drag Analysis Responsibility

`barakuda/devices/optical_tweezers/drag/` owns:
- Loading trajectory.
- Loading `<basename>_stage.json` and `<basename>_stage_trace.csv`.
- Defining baseline / steady-state windows.
- Computing alignment offset.
- Computing actual stage speed.
- Computing drag force and viscosity η.
- Quality control (QC flags).
- Future: active rheology interpretation.

Drag analysis **must NOT** know about:
- How stage motion was commanded.
- Camera acquisition internals.
- XIMC SDK.

---

## 6. What Must NOT Be Mixed

| Concern | Owner |
|---|---|
| Recording start/stop timing | Acquisition orchestration |
| run_t0 (shared clock reference) | Acquisition orchestration |
| Stage hardware commands | Motion layer |
| Physical stage event trace | Motion layer (written via StageTraceRecorder) |
| Brownian physics, drag force, η | Drag analysis only |
| Bead tracking | Drag analysis only |
| G', G'', viscoelasticity | Future analysis modules only |

Never put drag physics into Acquisition.
Never put recording orchestration into Drag analysis.
Never reconstruct events post-hoc — log them directly in the flow.

---

## 7. Key Experimental Metadata (NOW critical)

Must be present in `<basename>_stage.json`:
- `axis` (x or y)
- `direction`
- `travel_user_commanded`
- `speed_user_s_commanded`
- `accel_user_s2_commanded`
- `decel_user_s2_commanded`
- `actual_travel_user`
- `actual_motion_duration_s`
- `actual_speed_user_s`
- `pre_delay_s`, `post_delay_s`
- `sign_stage_to_image_x`, `sign_stage_to_image_y`
- `controller` (e.g. "ximc")
- `trace_file` (filename of the stage trace CSV)
- `recording_reference: "run_t0"` — documents that all stage times are relative to run_t0
- `motion_start_recording_s`, `motion_stop_recording_s` (in run_t0 domain)
- `stage_um_per_unit` (optional but valuable if known)

---

## 8. Long-term Direction (hydrogels / active rheology)

The architecture must support future workflows where:
- Multiple motion segments are executed during a single recording.
- Motion recipes produce oscillatory or step-response excitations.
- DRAG analysis transitions to active microrheology (frequency-domain analysis of bead response).
- Hydrogel experiments add viscoelastic interpretation layers (G'(ω), G''(ω), compliance).

To keep that future open:
- Motion recipes stay as isolated, callable units (no hard-coded single-mode logic in orchestration).
- StageTraceRecorder stays stateless — does not interpret physics, only records events.
- Acquisition orchestration stays generic: "execute recipe → record events → store outputs".
- All physics lives in analysis modules, never in the acquisition layer.

---

## 9. Why Synchronization via Acquisition (not manual alignment)

Current problem without this integration:
- Recording and stage scripts run independently.
- An uncertain time offset exists between the two.
- Stage files are stored in a separate location.
- Alignment is difficult and error-prone.
- Manual file matching is fragile for batch experiments.

With synchronized acquisition:
- `run_t0` is established once, before anything starts.
- Both recording orchestration and stage motion log events relative to `run_t0`.
- Stage files land automatically in the same canonical folder as the video.
- DRAG analysis gets `motion_start` as a precise, calibrated time in the same clock domain.
- No manual alignment is needed as the primary workflow.
- Experiment repeatability improves.
- Dataset is cleaner and auditable.

Note on clock domain: Camera frame timestamps in `video_timestamps.csv` are also
`time.perf_counter()` values (see `BaslerCamera.record_raw`). Since `run_t0` is set
just before `StartGrabbing()` in the same process, both axes share the same clock.
However, we do NOT use `video_timestamps.csv` for rebasing stage events — stage events
are logged directly relative to `run_t0`. This keeps the two axes independent and
avoids assuming perfect synchrony between first-frame capture and `run_t0`.

---

## 10. Architectural Principles to Preserve

1. **One shared clock per run.** `run_t0` is the single monotonic reference for all
   orchestration and stage events in a given acquisition run.
2. **Basename determines all output filenames.** Stage files always derive from the
   same basename as the video. No heuristic matching.
3. **Events are logged directly, not reconstructed.** The 8 mandatory trace events
   must be emitted by orchestration code at the exact moment they occur.
4. **Motion layer knows nothing about physics.** Recipes execute motion;
   analysis layers interpret the results.
5. **Each mode (`constant_velocity_drag`, future modes) is an isolated recipe.**
   Adding a new mode must not require rewriting orchestration logic.
6. **Failure is explicit and loud.** No run completes "OK" without a valid stage
   trace containing `motion_start`. Partial artifacts are preserved but clearly marked.
7. **Record-only path stays unchanged.** The existing `_RecordWorker` / `_on_record()`
   flow must not be broken or complicated by motion integration.
8. **Canonical folder is the single truth.** Stage files are written or copied to
   `runs/acquisition/<item_id>/acquisition/` — the same folder that already holds
   video, meta, and timestamps.
9. **Separation of concerns is hard.** If a piece of code "needs to know about"
   physics from another layer, that is a design bug, not a feature.
10. **Future modes plug in, they do not rewrite.** The MVP motion architecture
    is the minimum that must remain stable as the foundation for future workflows.
