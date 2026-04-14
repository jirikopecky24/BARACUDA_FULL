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


def format_record_motion_start_log(
    *,
    recipe: ConstantVelocityDragRecipe,
    metric_command: "MetricMotionCommand | None" = None,
    metric_mapping_profile: "XimcMetricCalibration | None" = None,
    stage_um_per_unit: float | None = None,
) -> str:
    """Return an explicit start log line with metric travel + raw register kinematics."""
    from .metric_conversion import (
        BackendMotionCommand,
        convert_metric_intent_to_backend_command,
    )

    if metric_command is not None:
        backend_cmd = convert_metric_intent_to_backend_command(
            legacy_travel_user=float(recipe.travel),
            legacy_direction=int(recipe.direction),
            legacy_speed_reg=float(recipe.speed),
            legacy_accel_reg=float(recipe.accel),
            legacy_decel_reg=float(recipe.decel),
            metric_command=metric_command,
            stage_um_per_unit=stage_um_per_unit,
            ximc_metric_calibration=metric_mapping_profile,
        )
    else:
        backend_cmd = BackendMotionCommand(
            travel_user=float(recipe.travel),
            speed_reg=float(recipe.speed),
            accel_reg=float(recipe.accel),
            decel_reg=float(recipe.decel),
            direction=int(recipe.direction),
            travel_source="legacy_travel_user",
            speed_source="legacy_speed_reg",
            accel_source="legacy_accel_reg",
            decel_source="legacy_decel_reg",
            warnings=(),
        )

    travel_um = (
        float(metric_command.travel_um)
        if metric_command is not None and metric_command.travel_um is not None
        else (
            float(backend_cmd.travel_user) * float(stage_um_per_unit)
            if stage_um_per_unit is not None and stage_um_per_unit > 0
            else None
        )
    )
    travel_metric_text = (
        f"{travel_um:.3f} µm"
        if travel_um is not None
        else "n/a µm"
    )
    return (
        f"Record+Motion starting — axis={recipe.axis}  dir={int(backend_cmd.direction):+d}  "
        f"travel_metric={travel_metric_text}  travel_user={float(backend_cmd.travel_user):.3f}  "
        f"speed_reg={int(round(float(backend_cmd.speed_reg)))}  "
        f"accel_reg={int(round(float(backend_cmd.accel_reg)))}  "
        f"decel_reg={int(round(float(backend_cmd.decel_reg)))}  "
        f"pre={float(recipe.pre_delay_s):.3f}s  post={float(recipe.post_delay_s):.3f}s"
    )


def resolve_unique_run_target(output_root: str | Path, requested_basename: str) -> tuple[str, Path]:
    """Return unique (basename, run_dir) to avoid silent overwrite."""
    root = Path(output_root)
    base = (requested_basename or "").strip() or time.strftime("Basler_%Y%m%d_%H%M%S")
    candidate = base
    idx = 1
    while (root / candidate).exists():
        candidate = f"{base}_r{idx:03d}"
        idx += 1
    run_dir = root / candidate
    run_dir.mkdir(parents=True, exist_ok=True)
    return candidate, run_dir


def _detect_speed_effect_invariant_against_recent_runs(
    *,
    output_path: Path,
    commanded_speed_raw: float | None,
    actual_speed_user_s: float | None,
) -> str | None:
    """Detect suspiciously invariant effective speed across different commanded speeds."""
    if commanded_speed_raw is None or actual_speed_user_s is None or actual_speed_user_s <= 0:
        return None
    parent = output_path.parent
    if not parent.exists():
        return None

    current_speed = float(commanded_speed_raw)
    current_actual = float(actual_speed_user_s)
    json_paths = sorted(parent.glob("*/*_stage.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    checked = 0
    for p in json_paths:
        if checked >= 10:
            break
        if p.parent == output_path:
            continue
        checked += 1
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        prev_cmd = payload.get("speed_reg_commanded_raw")
        prev_actual = payload.get("actual_speed_user_s")
        if prev_cmd is None or prev_actual is None:
            continue
        try:
            prev_cmd_f = float(prev_cmd)
            prev_actual_f = float(prev_actual)
        except Exception:
            continue
        # If commanded speed changed materially but measured speed barely moved, flag it.
        if abs(prev_cmd_f - current_speed) >= 5.0:
            denom = max(abs(current_actual), abs(prev_actual_f), 1e-9)
            rel_diff = abs(current_actual - prev_actual_f) / denom
            if rel_diff <= 0.05:
                return (
                    "speed_effect_invariant_vs_recent_run:"
                    f" prev_cmd={prev_cmd_f:g}, cur_cmd={current_speed:g}, "
                    f"prev_actual={prev_actual_f:.3f}, cur_actual={current_actual:.3f}"
                )
    return None


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
    metric_command: "MetricMotionCommand | None" = None,
    metric_mapping_profile: "XimcMetricCalibration | None" = None,
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
        metric_command: Optional metric-oriented motion intent (schema-first Phase2).
                        When provided, backend command resolution may use metric travel_um
                        if stage_um_per_unit is known. Metric speed/accel/decel mapping
                        requires a validated metric_mapping_profile.
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
    backend_cmd = None
    stage_um_per_unit_for_conversion = stage.get_stage_um_per_unit()
    metric_backend_conversion_warnings: list[str] = []
    try:
        # Legacy anchor: keep motion_start at command-issued time for backward
        # compatibility with existing loaders and datasets.
        from .metric_conversion import (
            BackendMotionCommand,
            convert_metric_intent_to_backend_command,
        )

        if metric_command is not None:
            backend_cmd = convert_metric_intent_to_backend_command(
                legacy_travel_user=float(recipe.travel),
                legacy_direction=int(recipe.direction),
                legacy_speed_reg=float(recipe.speed),
                legacy_accel_reg=float(recipe.accel),
                legacy_decel_reg=float(recipe.decel),
                metric_command=metric_command,
                stage_um_per_unit=stage_um_per_unit_for_conversion,
                ximc_metric_calibration=metric_mapping_profile,
            )
            metric_backend_conversion_warnings = list(backend_cmd.warnings)
        else:
            backend_cmd = BackendMotionCommand(
                travel_user=float(recipe.travel),
                speed_reg=float(recipe.speed),
                accel_reg=float(recipe.accel),
                decel_reg=float(recipe.decel),
                direction=int(recipe.direction),
                travel_source="legacy_travel_user",
                speed_source="legacy_speed_reg",
                accel_source="legacy_accel_reg",
                decel_source="legacy_decel_reg",
                warnings=(),
            )

        t_motion_command_issued = trace.log(
            "motion_command_issued",
            state="commanded",
        )
        t_motion_start = trace.log(
            "motion_start",
            state="moving",
        )
        _log(
            f"motion_start: direction={int(backend_cmd.direction):+d}  "
            f"travel_user={float(backend_cmd.travel_user):.3f}  "
            f"speed_reg={int(round(float(backend_cmd.speed_reg)))}  "
            f"accel_reg={int(round(float(backend_cmd.accel_reg)))}  "
            f"decel_reg={int(round(float(backend_cmd.decel_reg)))}"
        )
        _tr("move_constant_velocity CALL")  # #region agent log  #endregion
        motion_result = stage.move_constant_velocity(
            direction=int(backend_cmd.direction),
            travel=float(backend_cmd.travel_user),
            speed=float(backend_cmd.speed_reg),
            accel=float(backend_cmd.accel_reg),
            decel=float(backend_cmd.decel_reg),
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
        for sample in motion_result.motion_profile_samples:
            sample_t = t_motion_command_issued + float(sample.t_offset_s)
            if sample_t < t_motion_command_issued:
                continue
            trace.log(
                "motion_profile",
                t_override=sample_t,
                position_user=sample.position_user,
                velocity_user_s=sample.velocity_user_s,
                state=sample.state or "moving",
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
    _log("[MOTION-LIFECYCLE] finalize_recording: stop_record begin")
    camera.stop_record()
    _log("[MOTION-LIFECYCLE] finalize_recording: stop_record done")
    _tr("stop_record called")  # #region agent log  #endregion
    _log("[MOTION-LIFECYCLE] finalize_recording: join begin")
    rec_thread.join(timeout=max(10.0, duration_s + 5.0))
    _log("[MOTION-LIFECYCLE] finalize_recording: join done")
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
        _log("[MOTION-LIFECYCLE] artifact_write: stage_trace begin")
        trace.write_csv(stage_trace_path)
        _log("[MOTION-LIFECYCLE] artifact_write: stage_trace done")
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
    metric_command_travel_um = (
        float(metric_command.travel_um)
        if metric_command is not None and metric_command.travel_um is not None
        else None
    )
    metric_command_speed_um_s = (
        float(metric_command.speed_um_s)
        if metric_command is not None and metric_command.speed_um_s is not None
        else None
    )
    metric_command_accel_um_s2 = (
        float(metric_command.accel_um_s2)
        if metric_command is not None and metric_command.accel_um_s2 is not None
        else None
    )
    metric_command_decel_um_s2 = (
        float(metric_command.decel_um_s2)
        if metric_command is not None and metric_command.decel_um_s2 is not None
        else None
    )

    commanded_travel_um = (
        metric_command_travel_um
        if metric_command_travel_um is not None
        else (
            float(recipe.travel) * float(stage_um_per_unit)
            if stage_um_per_unit is not None
            else None
        )
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
    commanded_travel_um_source = (
        "metric_command.intent"
        if metric_command_travel_um is not None
        else (
            "stage_um_per_unit * legacy_recipe.travel"
            if stage_um_per_unit is not None
            else None
        )
    )
    speed_reg_commanded_raw = (
        float(backend_cmd.speed_reg) if backend_cmd is not None else float(recipe.speed)
    )
    speed_reg_readback_raw = (
        float(motion_result.speed_reg_readback_raw)
        if motion_result is not None and motion_result.speed_reg_readback_raw is not None
        else None
    )
    pre_motion_flags = (
        int(motion_result.pre_motion_flags)
        if motion_result is not None and motion_result.pre_motion_flags is not None
        else None
    )
    pre_motion_gpio_flags = (
        int(motion_result.pre_motion_gpio_flags)
        if motion_result is not None and motion_result.pre_motion_gpio_flags is not None
        else None
    )
    pre_motion_mv_cmd_sts = (
        int(motion_result.pre_motion_mv_cmd_sts)
        if motion_result is not None and motion_result.pre_motion_mv_cmd_sts is not None
        else None
    )
    pre_motion_alarm_nonfatal_allowed = (
        bool(motion_result.pre_motion_alarm_nonfatal_allowed)
        if motion_result is not None and motion_result.pre_motion_alarm_nonfatal_allowed is not None
        else None
    )

    speed_control_reasons: list[str] = []
    if pre_motion_flags is not None and (pre_motion_flags & 0x20):
        speed_control_reasons.append(f"pre_motion_alarm_flag_set:0x{pre_motion_flags:02X}")
    if (
        speed_reg_readback_raw is not None
        and abs(speed_reg_readback_raw - speed_reg_commanded_raw) > 0.5
    ):
        speed_control_reasons.append(
            f"speed_reg_readback_mismatch:{speed_reg_commanded_raw:g}->{speed_reg_readback_raw:g}"
        )
    if actual_speed <= 0:
        speed_control_reasons.append("actual_speed_nonpositive")
    invariant_reason = _detect_speed_effect_invariant_against_recent_runs(
        output_path=output_path,
        commanded_speed_raw=speed_reg_commanded_raw,
        actual_speed_user_s=float(actual_speed) if actual_speed is not None else None,
    )
    if invariant_reason:
        speed_control_reasons.append(invariant_reason)

    speed_effect_suspect = len(speed_control_reasons) > 0
    speed_control_validation_status = "suspect" if speed_effect_suspect else "pass"

    stage_meta: dict = {
        "schema_version": 1,
        "mode": recipe.mode,
        "axis": recipe.axis,
        "direction": recipe.direction,
        # Legacy keys retained for compatibility; values are raw XIMC register inputs.
        "travel_user_commanded": recipe.travel,
        "speed_user_s_commanded": recipe.speed,
        "accel_user_s2_commanded": recipe.accel,
        "decel_user_s2_commanded": recipe.decel,
        # Semantically explicit command keys (preferred for new readers).
        "travel_user_commanded_raw": recipe.travel,
        "speed_reg_commanded_raw": speed_reg_commanded_raw,
        "accel_reg_commanded_raw": float(backend_cmd.accel_reg) if backend_cmd is not None else float(recipe.accel),
        "decel_reg_commanded_raw": float(backend_cmd.decel_reg) if backend_cmd is not None else float(recipe.decel),
        "speed_reg_readback_raw": speed_reg_readback_raw,
        "actual_travel_user": actual_travel,
        "actual_motion_duration_s": actual_duration,
        "actual_speed_user_s": actual_speed,
        "pre_motion_status_flags": pre_motion_flags,
        "pre_motion_gpio_flags": pre_motion_gpio_flags,
        "pre_motion_mv_cmd_sts": pre_motion_mv_cmd_sts,
        "pre_motion_alarm_nonfatal_allowed": pre_motion_alarm_nonfatal_allowed,
        "speed_effect_suspect": speed_effect_suspect,
        "speed_control_validation_status": speed_control_validation_status,
        "speed_control_validation_reasons": list(speed_control_reasons),
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
                commanded_travel_um_source
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
            "note": "Metric speed/accel/decel intent is active only when conversion_mode=metric_validated_profile with an explicit mapping_validation_id.",
        },
        "commanded_metric": {
            "axis": metric_command.axis if metric_command is not None else recipe.axis,
            "direction": metric_command.direction if metric_command is not None else recipe.direction,
            "travel_um": commanded_travel_um,
            "speed_um_s": metric_command_speed_um_s,
            "accel_um_s2": metric_command_accel_um_s2,
            "decel_um_s2": metric_command_decel_um_s2,
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
                "speed_reg": float(backend_cmd.speed_reg) if backend_cmd is not None else float(recipe.speed),
                "accel_reg": float(backend_cmd.accel_reg) if backend_cmd is not None else float(recipe.accel),
                "decel_reg": float(backend_cmd.decel_reg) if backend_cmd is not None else float(recipe.decel),
            },
            "metric_backend_conversion": {
                "stage_um_per_unit_for_conversion": stage_um_per_unit_for_conversion,
                "backend_travel_user": float(backend_cmd.travel_user) if backend_cmd is not None else float(recipe.travel),
                "travel_source": backend_cmd.travel_source if backend_cmd is not None else "legacy_travel_user",
                "speed_source": backend_cmd.speed_source if backend_cmd is not None else "legacy_speed_reg",
                "accel_source": backend_cmd.accel_source if backend_cmd is not None else "legacy_accel_reg",
                "decel_source": backend_cmd.decel_source if backend_cmd is not None else "legacy_decel_reg",
                "conversion_mode": backend_cmd.conversion_mode if backend_cmd is not None else "legacy_raw_registers",
                "mapping_validation_id": backend_cmd.mapping_validation_id if backend_cmd is not None else None,
                "conversion_warnings": metric_backend_conversion_warnings,
            },
        },
    }
    if stage_um_per_unit is not None:
        stage_meta["stage_um_per_unit"] = stage_um_per_unit

    profile_rows = [row for row in trace.rows if row.event == "motion_profile"]
    vel_samples = sum(1 for row in profile_rows if row.velocity_user_s is not None)
    pos_samples = sum(1 for row in profile_rows if row.position_user is not None)
    stage_meta["stage_trace_sample_count"] = len(profile_rows)
    stage_meta["stage_trace_velocity_sample_count"] = vel_samples
    stage_meta["stage_trace_position_sample_count"] = pos_samples
    stage_meta["stage_trace_usable_for_windowing"] = bool(vel_samples >= 5 or pos_samples >= 6)

    _tr("writing stage JSON")  # #region agent log  #endregion
    try:
        _log("[MOTION-LIFECYCLE] artifact_write: stage_json begin")
        stage_json_path.write_text(
            json.dumps(stage_meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _log("[MOTION-LIFECYCLE] artifact_write: stage_json done")
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
