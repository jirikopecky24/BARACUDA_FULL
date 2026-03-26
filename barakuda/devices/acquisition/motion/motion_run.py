"""Synchronized Record + Motion orchestration.

Implements the deterministic 12-step flow defined in the design note:
  1.  create_run_context
  2.  establish run_t0
  3.  start recording (camera runs in a background thread)
  4.  log recording_start
  5.  log pre_hold_start → sleep pre_delay_s
  6.  log pre_hold_end
  7.  log motion_start → execute stage move
  8.  log motion_stop  (after move completes)
  9.  log post_hold_start → sleep post_delay_s
  10. log post_hold_end
  11. stop recording
  12. log recording_stop

Clock domain:
  run_t0 = time.perf_counter() taken immediately before camera StartGrabbing.
  All stage and orchestration events are logged as (perf_counter() - run_t0).
  video_timestamps.csv frame times are also perf_counter() values from the same
  process — they are NOT used for rebasing stage events; both axes share the clock
  but remain independent in the output files.

Failure semantics:
  - Stage not connected → raises MotionRunError before recording starts.
  - Recording start raises → propagates as MotionRunError.
  - Stage move fails after recording started → records motion_error in trace,
    stops recording (best effort), raises MotionRunError (partial artifacts preserved).
  - Trace/JSON write fails → raises MotionRunError after stopping recording.
  - No silent success without a valid trace containing motion_start.
"""
from __future__ import annotations

import json
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from barakuda.devices.acquisition.camera import BaslerCamera, RecordResult
from .recipes import ConstantVelocityDragRecipe
from .stage_base import AbstractStage
from .trace import StageTraceRecorder


class MotionRunError(RuntimeError):
    """Raised on any fatal error during a synchronized Record+Motion run."""


@dataclass
class MotionRunResult:
    """Structured result of a completed (or partially failed) Record+Motion run."""
    record_result: RecordResult
    stage_json_path: Path
    stage_trace_path: Path
    motion_start_s: float          # relative to run_t0
    motion_stop_s: Optional[float] # None if motion failed
    run_t0: float                  # absolute perf_counter reference


def run_record_and_motion(
    *,
    camera: BaslerCamera,
    stage: AbstractStage,
    recipe: ConstantVelocityDragRecipe,
    output_dir: str,
    basename: str,
    duration_s: float,
    roi: tuple[int, int, int, int],
    exposure_us: float,
    gain: Optional[float],
    fps_hint: float,
    pixel_format: str,
    progress_callback: Optional[Callable[[int, float], None]] = None,
    log_fn: Optional[Callable[[str], None]] = None,
) -> MotionRunResult:
    """Execute a single synchronized Record + Motion run.

    This function is designed to run inside a QThread worker.
    It is a plain function (not a method) to make unit-testing easier.

    Args:
        camera: Connected BaslerCamera instance (caller must ensure it's connected).
        stage: Connected AbstractStage instance.
        recipe: Fully validated ConstantVelocityDragRecipe.
        output_dir: Directory where the camera will write the raw video and related files.
                    Stage files are also written here, then copied to the canonical folder.
        basename: Filename stem (without extension). Determines ALL output filenames.
        duration_s: Maximum recording duration (0 = unlimited).
        roi, exposure_us, gain, fps_hint, pixel_format: camera parameters.
        progress_callback: Optional callback(frames, elapsed) forwarded to camera.
        log_fn: Optional callable(str) for UI log messages.

    Returns:
        MotionRunResult on success.
    Raises:
        MotionRunError on any fatal error.
    """

    # #region agent log — freeze tracer
    import json as _json, pathlib as _pl, time as _time
    def _tr(step, data=None):
        e = _json.dumps({"sessionId":"a34608","ts":_time.perf_counter(),"step":step,"data":data or {}})
        _pl.Path("debug-a34608.log").open("a").write(e+"\n")
    _tr("run_record_and_motion ENTER")
    # #endregion

    def _log(msg: str) -> None:
        if log_fn is not None:
            try:
                log_fn(f"[MOTION] {msg}")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Pre-flight validation
    # ------------------------------------------------------------------
    if not stage.is_connected:
        raise MotionRunError("Stage is not connected. Cannot start Record+Motion run.")

    errors = recipe.validate()
    if errors:
        raise MotionRunError(f"Recipe validation failed: {'; '.join(errors)}")

    output_path = Path(output_dir)

    # ------------------------------------------------------------------
    # Step 1-2: create run context, establish run_t0
    # The run_t0 is captured here, before StartGrabbing, so both recording
    # and stage share the same monotonic reference.
    # ------------------------------------------------------------------
    _log(f"Starting Record+Motion run — basename={basename}  recipe={recipe.mode}")
    run_t0 = time.perf_counter()
    trace = StageTraceRecorder(run_t0)
    stop_event = threading.Event()
    record_result_holder: list[Optional[RecordResult]] = [None]
    record_error_holder: list[Optional[str]] = [None]

    # ------------------------------------------------------------------
    # Step 3: start recording in background thread
    # ------------------------------------------------------------------
    def _recording_thread() -> None:
        _tr("record_raw ENTER")  # #region agent log  #endregion
        try:
            result = camera.record_raw(
                output_dir=output_dir,
                basename=basename,
                duration_s=duration_s,
                roi=roi,
                exposure_us=exposure_us,
                gain=gain,
                fps_hint=fps_hint,
                pixel_format=pixel_format,
                progress_callback=progress_callback,
            )
            _tr("record_raw DONE", {"ok": True})  # #region agent log  #endregion
            record_result_holder[0] = result
        except Exception as exc:
            _tr("record_raw EXCEPTION", {"err": str(exc)})  # #region agent log  #endregion
            record_error_holder[0] = str(exc)

    rec_thread = threading.Thread(target=_recording_thread, daemon=True, name="motion-rec")
    _tr("recording thread starting")  # #region agent log
    rec_thread.start()
    _tr("recording thread started")   # #endregion

    # Give camera a moment to start grabbing, then capture run_t0-relative start time.
    # We wait up to 2 s for the camera to produce at least one frame (or fail fast).
    t_wait_start = time.perf_counter()
    while time.perf_counter() - t_wait_start < 2.0:
        if record_error_holder[0] is not None:
            rec_thread.join(timeout=5.0)
            raise MotionRunError(
                f"Recording failed to start: {record_error_holder[0]}"
            )
        # Camera writes first frame shortly after StartGrabbing succeeds.
        # We treat the thread being alive as "recording started" after a brief settle.
        time.sleep(0.05)
        if time.perf_counter() - t_wait_start > 0.15:
            break

    # Check again after settle
    if record_error_holder[0] is not None:
        rec_thread.join(timeout=5.0)
        raise MotionRunError(f"Recording failed: {record_error_holder[0]}")

    _tr("camera settled, recording_start")  # #region agent log  #endregion

    # ------------------------------------------------------------------
    # Step 4: log recording_start
    # ------------------------------------------------------------------
    trace.log("recording_start")
    _log("recording_start logged")

    # ------------------------------------------------------------------
    # Steps 5-6: pre-hold
    # ------------------------------------------------------------------
    try:
        trace.log("pre_hold_start")
        _log(f"pre_hold: waiting {recipe.pre_delay_s:.2f} s")
        _tr("pre_hold sleep START")  # #region agent log  #endregion
        time.sleep(recipe.pre_delay_s)
        _tr("pre_hold sleep DONE")   # #region agent log  #endregion
        trace.log("pre_hold_end")
    except Exception as exc:
        _abort_recording(camera, stop_event, rec_thread, trace, _log)
        raise MotionRunError(f"Pre-hold failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Steps 7-8: motion
    # ------------------------------------------------------------------
    motion_stop_s: Optional[float] = None
    motion_result = None
    try:
        # Legacy anchor: keep motion_start at command-issued time for backward
        # compatibility with existing loaders and datasets.
        t_motion_command_issued = trace.log(
            "motion_command_issued",
            state="commanded",
        )
        t_motion_start = trace.log(
            "motion_start",
            state="moving",
        )
        _log(
            f"motion_start: direction={recipe.direction:+d}  travel={recipe.travel}  "
            f"XIMC Speed_reg={int(recipe.speed)}  Accel={int(recipe.accel)}  "
            f"(Speed=1,Accel=20 → ~20s for travel=1500)"
        )
        _tr("move_constant_velocity CALL")  # #region agent log  #endregion
        motion_result = stage.move_constant_velocity(
            direction=recipe.direction,
            travel=recipe.travel,
            speed=recipe.speed,
            accel=recipe.accel,
            decel=recipe.decel,
            stop_event=stop_event,
        )
        motion_running_confirmed_s: Optional[float] = None
        if motion_result.running_confirmed_delay_s is not None:
            motion_running_confirmed_s = (
                t_motion_command_issued + float(motion_result.running_confirmed_delay_s)
            )
            if motion_running_confirmed_s > t_motion_command_issued:
                trace.log(
                    "motion_running_confirmed",
                    t_override=motion_running_confirmed_s,
                    state="moving_confirmed",
                )
        motion_stop_s = trace.log(
            "motion_stop",
            position_user=motion_result.actual_travel_user,
            state="idle",
        )
        _log(
            f"motion_stop: actual_travel={motion_result.actual_travel_user:.3f}  "
            f"duration={motion_result.actual_duration_s:.3f} s  "
            f"speed={motion_result.actual_speed_user_s:.3f}"
        )
    except Exception as exc:
        # Motion failed after recording started — log error, preserve artifacts
        trace.log("motion_error", state="error")
        _log(f"Stage motion failed: {exc}")
        _abort_recording(camera, stop_event, rec_thread, trace, _log)
        _try_write_partial_trace(trace, output_path, basename, _log)
        raise MotionRunError(f"Stage motion failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Steps 9-10: post-hold
    # ------------------------------------------------------------------
    try:
        trace.log("post_hold_start")
        _log(f"post_hold: waiting {recipe.post_delay_s:.2f} s")
        time.sleep(recipe.post_delay_s)
        trace.log("post_hold_end")
    except Exception as exc:
        _abort_recording(camera, stop_event, rec_thread, trace, _log)
        raise MotionRunError(f"Post-hold failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Steps 11-12: stop recording + log recording_stop
    # ------------------------------------------------------------------
    camera.stop_record()
    _tr("stop_record called")  # #region agent log  #endregion
    rec_thread.join(timeout=max(10.0, duration_s + 5.0))
    _tr("rec_thread joined")  # #region agent log  #endregion
    trace.log("recording_stop")
    _log("recording_stop logged")

    if record_error_holder[0] is not None:
        raise MotionRunError(f"Recording failed during motion run: {record_error_holder[0]}")
    if record_result_holder[0] is None:
        raise MotionRunError("Recording thread finished without a result (unknown error).")

    record_result = record_result_holder[0]
    _log(
        f"Recording done — frames={record_result.frames_written}  "
        f"fps_eff={record_result.fps_effective:.1f}  dropped={record_result.dropped}"
    )

    # ------------------------------------------------------------------
    # Write stage_trace.csv and stage.json into output_dir
    # (Same location as video.raw — dataset home creation will copy them)
    # ------------------------------------------------------------------
    stage_trace_path = output_path / f"{basename}_stage_trace.csv"
    stage_json_path = output_path / f"{basename}_stage.json"

    _tr("writing trace CSV")  # #region agent log  #endregion
    try:
        trace.write_csv(stage_trace_path)
        _log(f"Stage trace written: {stage_trace_path}")
    except Exception as exc:
        raise MotionRunError(f"Failed to write stage trace CSV: {exc}") from exc
    _tr("trace CSV written")  # #region agent log  #endregion

    # Validate that motion_start is present (mandatory for DRAG loader)
    motion_start_s = trace.get_event_time("motion_start")
    if motion_start_s is None:
        raise MotionRunError(
            "BUG: motion_start event was not recorded in trace. "
            "This would produce an invalid DRAG dataset."
        )

    # Build stage.json
    actual_speed = (
        motion_result.actual_speed_user_s if motion_result is not None else 0.0
    )
    actual_travel = (
        motion_result.actual_travel_user if motion_result is not None else 0.0
    )
    actual_duration = (
        motion_result.actual_duration_s if motion_result is not None else 0.0
    )
    controller = (
        motion_result.controller if motion_result is not None else "unknown"
    )
    stage_um_per_unit = (
        motion_result.stage_um_per_unit if motion_result is not None else None
    )

    # Metric-oriented blocks (schema-first migration):
    # - commanded_metric: what the user intended in metric units (when stage scale is known)
    # - actual_metric: measured motion outcome in metric units (when stage scale is known)
    # - raw_internal: explicit backend/controller values (never pretend they're metric)
    metric_schema_version = 1
    commanded_travel_um = (
        float(recipe.travel) * float(stage_um_per_unit)
        if stage_um_per_unit is not None
        else None
    )
    actual_travel_um = (
        float(actual_travel) * float(stage_um_per_unit)
        if stage_um_per_unit is not None
        else None
    )
    actual_speed_um_s = (
        float(actual_speed) * float(stage_um_per_unit)
        if stage_um_per_unit is not None
        else None
    )
    metric_stage_um_source = (
        "ximc_stage_instance_ui" if stage_um_per_unit is not None else None
    )

    stage_meta: dict = {
        "schema_version": 1,
        "mode": recipe.mode,
        "axis": recipe.axis,
        "direction": recipe.direction,
        "travel_user_commanded": recipe.travel,
        "speed_user_s_commanded": recipe.speed,
        "accel_user_s2_commanded": recipe.accel,
        "decel_user_s2_commanded": recipe.decel,
        "actual_travel_user": actual_travel,
        "actual_motion_duration_s": actual_duration,
        "actual_speed_user_s": actual_speed,
        "pre_delay_s": recipe.pre_delay_s,
        "post_delay_s": recipe.post_delay_s,
        "sign_stage_to_image_x": recipe.sign_stage_to_image_x,
        "sign_stage_to_image_y": recipe.sign_stage_to_image_y,
        "controller": controller,
        "trace_file": stage_trace_path.name,
        # Recording-timeline binding
        "recording_reference": "run_t0",
        "motion_start_semantics": "legacy_command_issued",
        "motion_command_issued_recording_s": t_motion_command_issued,
        "motion_running_confirmed_recording_s": motion_running_confirmed_s,
        "motion_start_recording_s": motion_start_s,
        "motion_stop_recording_s": motion_stop_s,
        # Metric-units migration scaffolding (do not change legacy fields yet).
        "metric_schema_version": metric_schema_version,
        "metric_provenance": {
            "stage_um_per_unit_source": metric_stage_um_source,
            "commanded_travel_um_source": (
                "stage_um_per_unit * recipe.travel"
                if stage_um_per_unit is not None
                else None
            ),
            "actual_travel_um_source": (
                "stage_um_per_unit * motion_result.actual_travel_user"
                if stage_um_per_unit is not None
                else None
            ),
            "actual_speed_um_s_source": (
                "stage_um_per_unit * motion_result.actual_speed_user_s"
                if stage_um_per_unit is not None
                else None
            ),
            "note": "commanded_metric.speed_um_s and accel/decel are not populated in Phase 1 because speed_reg->speed_um_s mapping is not robust yet",
        },
        "commanded_metric": {
            "axis": recipe.axis,
            "direction": recipe.direction,
            "travel_um": commanded_travel_um,
            "speed_um_s": None,
            "accel_um_s2": None,
            "decel_um_s2": None,
            "pre_delay_s": recipe.pre_delay_s,
            "post_delay_s": recipe.post_delay_s,
        },
        "actual_metric": {
            "actual_travel_um": actual_travel_um,
            "actual_speed_um_s": actual_speed_um_s,
            "actual_motion_duration_s": actual_duration,
        },
        "raw_internal": {
            "controller": controller,
            "commanded_motion_registers": {
                "speed_reg": recipe.speed,
                "accel_reg": recipe.accel,
                "decel_reg": recipe.decel,
            },
        },
    }
    if stage_um_per_unit is not None:
        stage_meta["stage_um_per_unit"] = stage_um_per_unit

    _tr("writing stage JSON")  # #region agent log  #endregion
    try:
        stage_json_path.write_text(
            json.dumps(stage_meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _log(f"Stage meta written: {stage_json_path}")
    except Exception as exc:
        raise MotionRunError(f"Failed to write stage JSON: {exc}") from exc
    _tr("stage JSON written")  # #region agent log  #endregion

    _tr("returning MotionRunResult")  # #region agent log  #endregion
    return MotionRunResult(
        record_result=record_result,
        stage_json_path=stage_json_path,
        stage_trace_path=stage_trace_path,
        motion_start_s=motion_start_s,
        motion_stop_s=motion_stop_s,
        run_t0=run_t0,
    )


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _abort_recording(
    camera: BaslerCamera,
    stop_event: threading.Event,
    rec_thread: threading.Thread,
    trace: StageTraceRecorder,
    log_fn: Callable[[str], None],
) -> None:
    """Stop the recording thread cleanly (best-effort)."""
    try:
        stop_event.set()
        camera.stop_record()
        rec_thread.join(timeout=8.0)
        trace.log("recording_stop", state="aborted")
        log_fn("Recording stopped (aborted).")
    except Exception as exc:
        log_fn(f"Warning: could not cleanly stop recording: {exc}")


def _try_write_partial_trace(
    trace: StageTraceRecorder,
    output_path: Path,
    basename: str,
    log_fn: Callable[[str], None],
) -> None:
    """Best-effort write of partial trace on error path."""
    try:
        p = output_path / f"{basename}_stage_trace_partial.csv"
        trace.write_csv(p)
        log_fn(f"Partial stage trace preserved: {p}")
    except Exception as exc:
        log_fn(f"Warning: could not write partial trace: {exc}")
