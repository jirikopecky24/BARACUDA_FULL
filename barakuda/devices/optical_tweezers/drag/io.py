from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any

from .schema import (
    DragRunPaths,
    DragStageMeta,
    DragStageTraceEvent,
    DragStageTiming,
    DragRunLoaded,
    Axis,
)


class DragIoError(RuntimeError):
    """User-facing error for problems loading a DRAG run folder."""


def _require_single_raw(run_dir: Path) -> tuple[str, Path]:
    raw_files = sorted(p for p in run_dir.glob("*.raw") if p.is_file())
    if not raw_files:
        raise DragIoError(f"No .raw file found in run folder: {run_dir}")
    if len(raw_files) > 1:
        names = ", ".join(p.name for p in raw_files)
        raise DragIoError(f"Expected exactly one .raw file in run folder, found: {names}")
    raw_path = raw_files[0]
    return raw_path.stem, raw_path


def discover_drag_run_paths(run_dir: Path, trajectory_path: Path | None = None) -> DragRunPaths:
    """Discover all required DRAG files in a run directory.

    Preferred convention:
      <basename>.raw
      <basename>_meta.json
      <basename>_timestamps.csv
      <basename>_stage.json
      <basename>_stage_trace.csv

    For compatibility with current acquisition layout, this function also
    supports:
      - meta:           video_meta.json
      - timestamps:     video_timestamps.csv
      - stage meta:     ot_drag*.json
      - stage trace:    matching ot_drag*.csv or ot_drag*.txt
    """
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise DragIoError(f"Run folder does not exist or is not a directory: {run_dir}")

    basename, raw_path = _require_single_raw(run_dir)

    # --- video meta / timestamps ---
    meta_path = run_dir / f"{basename}_meta.json"
    if not meta_path.is_file():
        # Fallback: video_meta.json
        fallback = run_dir / "video_meta.json"
        if fallback.is_file():
            meta_path = fallback
        else:
            raise DragIoError("Missing required file for DRAG run: video_meta.json")

    timestamps_path = run_dir / f"{basename}_timestamps.csv"
    if not timestamps_path.is_file():
        # Fallback: video_timestamps.csv
        fallback = run_dir / "video_timestamps.csv"
        if fallback.is_file():
            timestamps_path = fallback
        else:
            raise DragIoError("Missing required file for DRAG run: video_timestamps.csv")

    # --- stage meta / trace ---
    preferred_stage_meta = run_dir / f"{basename}_stage.json"
    if preferred_stage_meta.is_file():
        stage_meta_path = preferred_stage_meta
    else:
        # Fallback: any ot_drag*.json or *stage*.json
        candidates = sorted(run_dir.glob("ot_drag*.json")) or sorted(run_dir.glob("*stage*.json"))
        if not candidates:
            raise DragIoError("Missing required file for DRAG run: stage metadata JSON (e.g. ot_drag*.json)")
        stage_meta_path = candidates[0]

    preferred_stage_trace = run_dir / f"{basename}_stage_trace.csv"
    stage_trace_path = preferred_stage_trace if preferred_stage_trace.is_file() else None
    if stage_trace_path is None:
        # Try to find a trace file matching the stage meta stem with csv/txt
        stem = stage_meta_path.stem
        for ext in (".csv", ".txt"):
            cand = run_dir / f"{stem}{ext}"
            if cand.is_file():
                stage_trace_path = cand
                break
    if stage_trace_path is None:
        # Last resort: any ot_drag*.csv/txt
        candidates = (
            sorted(run_dir.glob("ot_drag*.csv"))
            or sorted(run_dir.glob("ot_drag*.txt"))
        )
        if not candidates:
            raise DragIoError("Missing required file for DRAG run: stage trace CSV/TXT (e.g. ot_drag*.txt)")
        stage_trace_path = candidates[0]

    resolved_traj: Path | None = None
    if trajectory_path is not None:
        resolved_traj = Path(trajectory_path).resolve()
        if not resolved_traj.is_file():
            raise DragIoError(f"Provided trajectory CSV does not exist: {resolved_traj}")
    else:
        candidate = run_dir / f"{basename}_trajectory.csv"
        if candidate.is_file():
            resolved_traj = candidate

    return DragRunPaths(
        run_dir=run_dir,
        basename=basename,
        raw_path=raw_path,
        meta_path=meta_path,
        timestamps_path=timestamps_path,
        stage_meta_path=stage_meta_path,
        stage_trace_path=stage_trace_path,
        trajectory_path=resolved_traj,
    )


def _load_stage_meta(stage_meta_path: Path) -> DragStageMeta:
    data = json.loads(stage_meta_path.read_text(encoding="utf-8"))

    try:
        # Keep all unknown keys so active protocols (oscillatory/step) can evolve
        # without breaking DRAG v1 stage loading.
        protocol_params: dict[str, Any] = {}
        known_keys = {
            "axis",
            "direction",
            "actual_travel_user",
            "actual_motion_duration_s",
            "actual_speed_user_s",
            "sign_stage_to_image_x",
            "sign_stage_to_image_y",
            "pre_delay_s",
            "post_delay_s",
            "stage_um_per_unit",
        }
        for k, v in data.items():
            if k not in known_keys:
                protocol_params[str(k)] = v

        axis_raw = str(data["axis"]).lower().strip()
        if axis_raw not in ("x", "y"):
            raise ValueError(f"axis must be 'x' or 'y', got {axis_raw!r}")
        axis: Axis = "x" if axis_raw == "x" else "y"

        direction = str(data.get("direction", ""))
        actual_travel_user = float(data["actual_travel_user"])
        actual_motion_duration_s = float(data["actual_motion_duration_s"])
        actual_speed_user_s = float(
            data.get("actual_speed_user_s", actual_travel_user / actual_motion_duration_s)
        )
        sign_stage_to_image_x = int(data.get("sign_stage_to_image_x", 1))
        sign_stage_to_image_y = int(data.get("sign_stage_to_image_y", 1))
        pre_delay_s = float(data.get("pre_delay_s", 0.0))
        post_delay_s = float(data.get("post_delay_s", 0.0))
        stage_um_per_unit = (
            float(data["stage_um_per_unit"]) if "stage_um_per_unit" in data else None
        )
    except KeyError as e:
        raise DragIoError(f"Stage metadata missing required field: {e}") from e
    except Exception as e:  # noqa: BLE001
        raise DragIoError(f"Failed to parse stage metadata {stage_meta_path.name}: {e}") from e

    if actual_motion_duration_s <= 0:
        raise DragIoError("Stage metadata has non-positive actual_motion_duration_s")

    return DragStageMeta(
        axis=axis,
        direction=direction,
        actual_travel_user=actual_travel_user,
        actual_motion_duration_s=actual_motion_duration_s,
        actual_speed_user_s=actual_speed_user_s,
        sign_stage_to_image_x=sign_stage_to_image_x,
        sign_stage_to_image_y=sign_stage_to_image_y,
        pre_delay_s=pre_delay_s,
        post_delay_s=post_delay_s,
        stage_um_per_unit=stage_um_per_unit,
        protocol_params=protocol_params,
    )


def _load_stage_trace(stage_trace_path: Path) -> tuple[list[DragStageTraceEvent], DragStageTiming]:
    events: list[DragStageTraceEvent] = []
    with stage_trace_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "t_s" not in (reader.fieldnames or []) or "event" not in (reader.fieldnames or []):
            raise DragIoError(
                f"Stage trace {stage_trace_path.name} must contain at least 't_s' and 'event' columns"
            )
        for row in reader:
            if not row:
                continue
            try:
                t_s = float(row.get("t_s", "nan"))
            except Exception:  # noqa: BLE001
                continue
            ev = str(row.get("event", "")).strip()
            extra = {k: v for k, v in row.items() if k not in {"t_s", "event"}}
            events.append(DragStageTraceEvent(t_s=t_s, event=ev, extra=extra))

    timing = DragStageTiming()
    for e in events:
        name = e.event.lower()
        if name == "script_start":
            timing = DragStageTiming(**{**timing.__dict__, "script_start_s": e.t_s})
        elif name == "pre_hold_start":
            timing = DragStageTiming(**{**timing.__dict__, "pre_hold_start_s": e.t_s})
        elif name == "pre_hold_end":
            timing = DragStageTiming(**{**timing.__dict__, "pre_hold_end_s": e.t_s})
        elif name == "motion_start":
            timing = DragStageTiming(**{**timing.__dict__, "motion_start_stage_s": e.t_s})
        elif name == "motion_stop":
            timing = DragStageTiming(**{**timing.__dict__, "motion_stop_stage_s": e.t_s})
        elif name == "post_hold_start":
            timing = DragStageTiming(**{**timing.__dict__, "post_hold_start_s": e.t_s})
        elif name == "post_hold_end":
            timing = DragStageTiming(**{**timing.__dict__, "post_hold_end_s": e.t_s})
        elif name == "script_end":
            timing = DragStageTiming(**{**timing.__dict__, "script_end_s": e.t_s})

    if timing.motion_start_stage_s is None:
        raise DragIoError(
            f"Stage trace {stage_trace_path.name} does not contain a 'motion_start' event"
        )

    return events, timing


def _load_video_timestamps(timestamps_path: Path) -> tuple[list[int], list[float]]:
    frames: list[int] = []
    times: list[float] = []
    with timestamps_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "frame" not in (reader.fieldnames or []) or "timestamp_s" not in (
            reader.fieldnames or []
        ):
            raise DragIoError(
                f"Timestamps CSV {timestamps_path.name} must contain 'frame' and 'timestamp_s' columns"
            )
        for row in reader:
            if not row:
                continue
            try:
                fi = int(row.get("frame", "0"))
                ts = float(row.get("timestamp_s", "nan"))
            except Exception:  # noqa: BLE001
                continue
            frames.append(fi)
            times.append(ts)

    if len(frames) < 2:
        raise DragIoError(
            f"Timestamps CSV {timestamps_path.name} has too few rows for analysis "
            "(need at least 2 frames)"
        )

    return frames, times


def load_drag_run(run_dir: Path, trajectory_path: Path | None = None) -> DragRunLoaded:
    """Load all required inputs for a DRAG analysis from a run folder.

    Note: DRAG v1 requires a trajectory CSV; if none is discovered or provided,
    this function raises DragIoError with a user-facing explanation.
    """
    paths = discover_drag_run_paths(run_dir, trajectory_path=trajectory_path)
    if paths.trajectory_path is None:
        raise DragIoError(
            "DRAG v1 requires an existing trajectory CSV. "
            f"No trajectory was provided and {paths.basename}_trajectory.csv "
            f"was not found in {paths.run_dir}."
        )

    stage_meta = _load_stage_meta(paths.stage_meta_path)
    stage_events, stage_timing = _load_stage_trace(paths.stage_trace_path)
    frame_indices, frame_timestamps_s = _load_video_timestamps(paths.timestamps_path)

    return DragRunLoaded(
        paths=paths,
        stage_meta=stage_meta,
        stage_events=stage_events,
        stage_timing=stage_timing,
        frame_indices=frame_indices,
        frame_timestamps_s=frame_timestamps_s,
    )

