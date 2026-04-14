from __future__ import annotations

from dataclasses import dataclass
import csv
import json
import logging
from pathlib import Path
from typing import Any

from barakuda.core.truth_resolvers import load_and_validate_timestamps_csv
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


_LOG = logging.getLogger(__name__)


def _find_item_root_context(input_dir: Path) -> Path | None:
    current = input_dir.resolve()
    for _ in range(4):
        if (current / "item.json").is_file():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def _build_scoped_dirs(
    *,
    input_dir: Path,
    item_root: Path | None,
    relative_candidates: tuple[str, ...],
) -> list[Path]:
    dirs: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        rp = p.resolve()
        key = str(rp).lower()
        if key in seen:
            return
        if not rp.is_dir():
            return
        if item_root is not None:
            try:
                rp.relative_to(item_root)
            except Exception:
                return
        seen.add(key)
        dirs.append(rp)

    _add(input_dir.resolve())
    if item_root is not None:
        _add(item_root)
        for rel in relative_candidates:
            _add(item_root / rel)
    return dirs


def _unique_files(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        rp = p.resolve()
        key = str(rp).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(rp)
    return sorted(out)


def _select_item_scoped_artifact(
    *,
    artifact_key: str,
    expected_kind: str,
    basename: str,
    item_stem: str | None,
    search_dirs: list[Path],
    exact_suffix: str,
    pattern: str,
    allow_single_candidate_fallback: bool = True,
) -> tuple[Path, str, str | None, list[Path]]:
    exact_basename_name = f"{basename}{exact_suffix}"
    exact_item_name = f"{item_stem}{exact_suffix}" if item_stem else None

    exact_basename_hits: list[Path] = []
    exact_item_hits: list[Path] = []
    pattern_hits: list[Path] = []
    for d in search_dirs:
        p_base = d / exact_basename_name
        if p_base.is_file():
            exact_basename_hits.append(p_base.resolve())
        if exact_item_name:
            p_item = d / exact_item_name
            if p_item.is_file():
                exact_item_hits.append(p_item.resolve())
        pattern_hits.extend([p.resolve() for p in d.glob(pattern) if p.is_file()])

    exact_basename_hits = _unique_files(exact_basename_hits)
    exact_item_hits = _unique_files(exact_item_hits)
    pattern_hits = _unique_files(pattern_hits)

    if len(exact_basename_hits) == 1:
        return exact_basename_hits[0], "exact_basename_match", None, pattern_hits
    if len(exact_basename_hits) > 1:
        names = ", ".join(str(p) for p in exact_basename_hits)
        raise DragIoError(
            f"Ambiguous {expected_kind}: multiple exact basename matches found "
            f"for {exact_basename_name!r} in current item scope: {names}"
        )

    if len(exact_item_hits) == 1:
        return (
            exact_item_hits[0],
            "exact_item_stem_match",
            f"Using item-stem fallback {exact_item_name!r} instead of {exact_basename_name!r}.",
            pattern_hits,
        )
    if len(exact_item_hits) > 1:
        names = ", ".join(str(p) for p in exact_item_hits)
        raise DragIoError(
            f"Ambiguous {expected_kind}: multiple exact item-stem matches found "
            f"for {exact_item_name!r} in current item scope: {names}"
        )

    if not allow_single_candidate_fallback:
        raise DragIoError(
            f"Missing {expected_kind}: no exact basename/item-stem match found "
            f"for {exact_basename_name!r} in current item scope."
        )

    if len(pattern_hits) == 1:
        return (
            pattern_hits[0],
            "item_scoped_single_candidate",
            (
                f"Fallback selection for {expected_kind}: exact names "
                f"{exact_basename_name!r}"
                + (f" or {exact_item_name!r}" if exact_item_name else "")
                + " not found, selected the only item-scoped candidate."
            ),
            pattern_hits,
        )

    if len(pattern_hits) > 1:
        names = ", ".join(str(p) for p in pattern_hits)
        raise DragIoError(
            f"Ambiguous {expected_kind}: exact names not found and multiple item-scoped "
            f"candidates match pattern {pattern!r}: {names}"
        )

    raise DragIoError(
        f"Missing {expected_kind}: no candidate found in item-scoped directories for "
        f"exact names {exact_basename_name!r}"
        + (f" or {exact_item_name!r}" if exact_item_name else "")
        + f" and pattern {pattern!r}."
    )


def _log_artifact_discovery(
    *,
    input_path: Path,
    item_root: Path | None,
    artifact_key: str,
    expected_kind: str,
    search_dirs: list[Path],
    candidates: list[Path],
    selected: Path | None,
    mode: str,
    warning: str | None,
) -> None:
    _LOG.info(
        "[DRAG discovery] input=%s item_root=%s artifact=%s kind=%s searched=%s candidates=%s selected=%s mode=%s warning=%s",
        str(input_path),
        str(item_root) if item_root is not None else None,
        artifact_key,
        expected_kind,
        [str(p) for p in search_dirs],
        [str(p) for p in candidates],
        str(selected) if selected is not None else None,
        mode,
        warning,
    )


def _require_single_raw(run_dir: Path) -> tuple[str, Path]:
    raw_files = sorted(p for p in run_dir.glob("*.raw") if p.is_file())
    if not raw_files:
        raise DragIoError(f"No .raw file found in run folder: {run_dir}")
    if len(raw_files) > 1:
        names = ", ".join(p.name for p in raw_files)
        raise DragIoError(f"Expected exactly one .raw file in run folder, found: {names}")
    raw_path = raw_files[0]
    return raw_path.stem, raw_path


def discover_drag_run_paths(
    run_dir: Path,
    trajectory_path: Path | None = None,
    *,
    require_trajectory: bool = True,
    include_trajectory_discovery: bool = True,
) -> DragRunPaths:
    """Discover all required DRAG files in a run directory.

    When ``include_trajectory_discovery`` is False and no ``trajectory_path`` is
    provided, trajectory CSV is left unset (used for Drag's default RAW→tracking
    flow where tracking generates the file).

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
    item_root = _find_item_root_context(run_dir)
    if item_root is None:
        _LOG.warning(
            "[DRAG discovery] unresolved item context for input=%s; discovery limited to provided directory",
            str(run_dir),
        )

    run_scoped_dirs = _build_scoped_dirs(
        input_dir=run_dir,
        item_root=item_root,
        relative_candidates=("acquisition", "raw"),
    )
    analysis_scoped_dirs = _build_scoped_dirs(
        input_dir=run_dir,
        item_root=item_root,
        relative_candidates=("analysis/csv", "analysis/results", "analysis", "acquisition", "raw"),
    )

    # Discover raw in item/run scope first.
    raw_candidates: list[Path] = []
    for d in run_scoped_dirs:
        raw_candidates.extend([p.resolve() for p in d.glob("*.raw") if p.is_file()])
    raw_candidates = _unique_files(raw_candidates)
    if not raw_candidates:
        raise DragIoError(
            "Missing required file for DRAG run: no .raw candidate found in current item/run context. "
            f"input={run_dir}, item_root={item_root}, searched={[str(p) for p in run_scoped_dirs]}"
        )
    if len(raw_candidates) > 1:
        raise DragIoError(
            "Ambiguous DRAG run raw input: multiple .raw files found in current item/run context: "
            + ", ".join(str(p) for p in raw_candidates)
        )
    raw_path = raw_candidates[0]
    basename = raw_path.stem
    item_stem = item_root.name if item_root is not None else None
    used_fallbacks: dict[str, str] = {}
    artifact_selection: dict[str, dict[str, Any]] = {}

    def _record(
        key: str,
        expected_kind: str,
        selected: Path,
        mode: str,
        warning: str | None,
        candidates: list[Path],
        searched_dirs: list[Path],
    ) -> None:
        artifact_selection[key] = {
            "selected_artifact_path": str(selected),
            "artifact_selection_mode": mode,
            "artifact_selection_warning": warning,
            "candidate_files": [str(p) for p in candidates],
            "searched_directories": [str(p) for p in searched_dirs],
        }
        _log_artifact_discovery(
            input_path=run_dir,
            item_root=item_root,
            artifact_key=key,
            expected_kind=expected_kind,
            search_dirs=searched_dirs,
            candidates=candidates,
            selected=selected,
            mode=mode,
            warning=warning,
        )
        if mode != "exact_basename_match":
            used_fallbacks[key] = mode

    # meta
    meta_path, meta_mode, meta_warn, meta_candidates = _select_item_scoped_artifact(
        artifact_key="meta_path",
        expected_kind="video metadata JSON",
        basename=basename,
        item_stem=item_stem,
        search_dirs=run_scoped_dirs,
        exact_suffix="_meta.json",
        pattern="*_meta.json",
        allow_single_candidate_fallback=True,
    )
    _record("meta_path", "video metadata JSON", meta_path, meta_mode, meta_warn, meta_candidates, run_scoped_dirs)

    # timestamps
    timestamps_path, ts_mode, ts_warn, ts_candidates = _select_item_scoped_artifact(
        artifact_key="timestamps_path",
        expected_kind="video timestamps CSV",
        basename=basename,
        item_stem=item_stem,
        search_dirs=run_scoped_dirs,
        exact_suffix="_timestamps.csv",
        pattern="*_timestamps.csv",
        allow_single_candidate_fallback=True,
    )
    _record("timestamps_path", "video timestamps CSV", timestamps_path, ts_mode, ts_warn, ts_candidates, run_scoped_dirs)

    # stage meta
    stage_meta_path, sm_mode, sm_warn, sm_candidates = _select_item_scoped_artifact(
        artifact_key="stage_meta_path",
        expected_kind="stage metadata JSON",
        basename=basename,
        item_stem=item_stem,
        search_dirs=run_scoped_dirs,
        exact_suffix="_stage.json",
        pattern="*stage*.json",
        allow_single_candidate_fallback=True,
    )
    _record("stage_meta_path", "stage metadata JSON", stage_meta_path, sm_mode, sm_warn, sm_candidates, run_scoped_dirs)

    # stage trace
    stage_trace_path, st_mode, st_warn, st_candidates = _select_item_scoped_artifact(
        artifact_key="stage_trace_path",
        expected_kind="stage trace CSV/TXT",
        basename=basename,
        item_stem=item_stem,
        search_dirs=run_scoped_dirs,
        exact_suffix="_stage_trace.csv",
        pattern="*stage_trace.*",
        allow_single_candidate_fallback=True,
    )
    _record("stage_trace_path", "stage trace CSV/TXT", stage_trace_path, st_mode, st_warn, st_candidates, run_scoped_dirs)

    resolved_traj: Path | None = None
    if trajectory_path is not None:
        resolved_traj = Path(trajectory_path).resolve()
        if not resolved_traj.is_file():
            raise DragIoError(f"Provided trajectory CSV does not exist: {resolved_traj}")
        if item_root is not None:
            try:
                resolved_traj.relative_to(item_root)
            except Exception as exc:
                raise DragIoError(
                    "Provided trajectory CSV is outside current item context and cannot be used: "
                    f"{resolved_traj} (item_root={item_root})"
                ) from exc
        artifact_selection["trajectory_path"] = {
            "selected_artifact_path": str(resolved_traj),
            "artifact_selection_mode": "provided_path_in_item_scope",
            "artifact_selection_warning": None,
            "candidate_files": [str(resolved_traj)],
            "searched_directories": [str(p) for p in analysis_scoped_dirs],
        }
        _log_artifact_discovery(
            input_path=run_dir,
            item_root=item_root,
            artifact_key="trajectory_path",
            expected_kind="trajectory CSV",
            search_dirs=analysis_scoped_dirs,
            candidates=[resolved_traj],
            selected=resolved_traj,
            mode="provided_path_in_item_scope",
            warning=None,
        )
    elif include_trajectory_discovery:
        try:
            resolved_traj, tr_mode, tr_warn, tr_candidates = _select_item_scoped_artifact(
                artifact_key="trajectory_path",
                expected_kind="trajectory CSV",
                basename=basename,
                item_stem=item_stem,
                search_dirs=analysis_scoped_dirs,
                exact_suffix="_trajectory.csv",
                pattern="*_trajectory.csv",
                allow_single_candidate_fallback=True,
            )
            artifact_selection["trajectory_path"] = {
                "selected_artifact_path": str(resolved_traj),
                "artifact_selection_mode": tr_mode,
                "artifact_selection_warning": tr_warn,
                "candidate_files": [str(p) for p in tr_candidates],
                "searched_directories": [str(p) for p in analysis_scoped_dirs],
            }
            _log_artifact_discovery(
                input_path=run_dir,
                item_root=item_root,
                artifact_key="trajectory_path",
                expected_kind="trajectory CSV",
                search_dirs=analysis_scoped_dirs,
                candidates=tr_candidates,
                selected=resolved_traj,
                mode=tr_mode,
                warning=tr_warn,
            )
            if tr_mode != "exact_basename_match":
                used_fallbacks["trajectory_path"] = tr_mode
        except DragIoError as exc:
            if require_trajectory:
                raise DragIoError(
                    f"{exc} input={run_dir}, item_root={item_root}, "
                    f"searched={[str(p) for p in analysis_scoped_dirs]}"
                ) from exc
            # Keep trajectory as optional at discovery layer (run_raw can generate it).
            artifact_selection["trajectory_path"] = {
                "selected_artifact_path": None,
                "artifact_selection_mode": "missing_or_ambiguous",
                "artifact_selection_warning": str(exc),
                "candidate_files": [],
                "searched_directories": [str(p) for p in analysis_scoped_dirs],
            }
            _log_artifact_discovery(
                input_path=run_dir,
                item_root=item_root,
                artifact_key="trajectory_path",
                expected_kind="trajectory CSV",
                search_dirs=analysis_scoped_dirs,
                candidates=[],
                selected=None,
                mode="missing_or_ambiguous",
                warning=str(exc),
            )
    else:
        resolved_traj = None
        artifact_selection["trajectory_path"] = {
            "selected_artifact_path": None,
            "artifact_selection_mode": "skipped_for_drag_generated_trajectory",
            "artifact_selection_warning": None,
            "candidate_files": [],
            "searched_directories": [str(p) for p in analysis_scoped_dirs],
        }
        _log_artifact_discovery(
            input_path=run_dir,
            item_root=item_root,
            artifact_key="trajectory_path",
            expected_kind="trajectory CSV",
            search_dirs=analysis_scoped_dirs,
            candidates=[],
            selected=None,
            mode="skipped_for_drag_generated_trajectory",
            warning=None,
        )

    return DragRunPaths(
        run_dir=run_dir,
        basename=basename,
        raw_path=raw_path,
        meta_path=meta_path,
        timestamps_path=timestamps_path,
        stage_meta_path=stage_meta_path,
        stage_trace_path=stage_trace_path,
        trajectory_path=resolved_traj,
        used_fallbacks=used_fallbacks,
        artifact_selection=artifact_selection,
    )


def evaluate_drag_preflight(
    *,
    current_drag_input_path: Path,
    run_dir: Path,
    brownian_baseline_folder: Path | None,
) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    current_drag_input_path = Path(current_drag_input_path).resolve()
    item_root = _find_item_root_context(run_dir)
    baseline_folder = Path(brownian_baseline_folder).resolve() if brownian_baseline_folder else None
    baseline_selection_mode = "explicit_ui_folder" if baseline_folder else "missing"

    try:
        paths = discover_drag_run_paths(
            run_dir,
            trajectory_path=None,
            require_trajectory=False,
            include_trajectory_discovery=False,
        )
    except Exception as exc:
        return {
            "current_drag_input_path": str(current_drag_input_path),
            "current_drag_item_root": str(item_root) if item_root is not None else None,
            "current_drag_trajectory_path": None,
            "brownian_baseline_folder": str(baseline_folder) if baseline_folder is not None else None,
            "baseline_selection_mode": baseline_selection_mode,
            "drag_preflight_status": "failed_invalid_run_context",
            "drag_preflight_message": f"Current drag input context is invalid: {exc}",
            "artifact_selection": {},
        }

    traj_info = paths.artifact_selection.get("trajectory_path") or {}

    # Default Drag workflow does not use preflight to gate on any pre-existing trajectory CSV.
    if item_root is None:
        status = "ready_drag_sidecars_standalone"
        if baseline_folder is not None:
            msg = (
                "Drag RAW and sidecars are present in this folder. The batch will run Drag tracking on the RAW "
                "video, then load the paired Brownian folder for calibration/κ only (Brown is not used to pick "
                "a trajectory)."
            )
        else:
            msg = (
                "Drag RAW and sidecars are present. Tracking will run on the Drag RAW video; configure a Brownian "
                "baseline folder for Drag calibration after tracking."
            )
    else:
        status = "ready_drag_sidecars_item"
        msg = (
            "Drag RAW and sidecars are present in the item. The batch will run Drag tracking on the Drag RAW "
            "video, then apply Brownian calibration from the paired baseline folder (not for trajectory selection)."
        )
    warn = traj_info.get("artifact_selection_warning")
    if warn:
        msg = f"{msg} Discovery detail: {warn}"

    return {
        "current_drag_input_path": str(current_drag_input_path),
        "current_drag_item_root": str(item_root) if item_root is not None else None,
        "current_drag_trajectory_path": None,
        "brownian_baseline_folder": str(baseline_folder) if baseline_folder is not None else None,
        "baseline_selection_mode": baseline_selection_mode,
        "drag_preflight_status": status,
        "drag_preflight_message": msg,
        "artifact_selection": dict(paths.artifact_selection),
    }


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
            "actual_metric",
            "raw_internal",
            "metric_schema_version",
            "metric_provenance",
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
        # Metric-first kinematics (optional): prefer explicit actual_metric if present and valid.
        actual_metric = data.get("actual_metric") if isinstance(data.get("actual_metric"), dict) else {}
        _atu = actual_metric.get("actual_travel_um") if isinstance(actual_metric, dict) else None
        _asu = actual_metric.get("actual_speed_um_s") if isinstance(actual_metric, dict) else None
        actual_travel_um = float(_atu) if _atu is not None else None
        actual_speed_um_s = float(_asu) if _asu is not None else None
        if actual_travel_um is not None and not (actual_travel_um == actual_travel_um):  # NaN
            actual_travel_um = None
        if actual_speed_um_s is not None and not (actual_speed_um_s == actual_speed_um_s):  # NaN
            actual_speed_um_s = None
        kinematics_source = "actual_metric" if (actual_travel_um is not None or actual_speed_um_s is not None) else "legacy_user_units"
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
        actual_travel_um=actual_travel_um,
        actual_speed_um_s=actual_speed_um_s,
        kinematics_source=kinematics_source,
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
        elif name == "motion_command_issued":
            timing = DragStageTiming(**{**timing.__dict__, "motion_command_issued_s": e.t_s})
        elif name == "motion_running_confirmed":
            timing = DragStageTiming(**{**timing.__dict__, "motion_running_confirmed_s": e.t_s})
        elif name in {"steady_state_start", "steady_start"}:
            timing = DragStageTiming(**{**timing.__dict__, "steady_state_start_stage_s": e.t_s})
        elif name in {"deceleration_start", "motion_deceleration_start", "decel_start"}:
            timing = DragStageTiming(**{**timing.__dict__, "deceleration_start_stage_s": e.t_s})
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

    # Legacy compatibility: old runs only have motion_start; newer runs may expose
    # motion_command_issued and motion_running_confirmed explicitly.
    if (
        timing.motion_start_stage_s is None
        and timing.motion_running_confirmed_s is None
        and timing.motion_command_issued_s is None
    ):
        raise DragIoError(
            f"Stage trace {stage_trace_path.name} does not contain any motion start anchor event"
        )

    return events, timing


def _load_video_timestamps(timestamps_path: Path) -> tuple[list[int], list[float], bool, str]:
    try:
        frames, times, _ = load_and_validate_timestamps_csv(timestamps_path)
        return frames, times, True, "timestamps validated"
    except Exception as exc:
        raise DragIoError(
            f"Timestamps CSV validation failed for {timestamps_path.name}: {exc}"
        ) from exc


def load_drag_run(
    run_dir: Path,
    trajectory_path: Path | None = None,
    *,
    allow_discover_trajectory: bool = True,
) -> DragRunLoaded:
    """Load all required inputs for a DRAG analysis from a run folder.

    With an explicit ``trajectory_path``, on-disk trajectory discovery is skipped
    (thesis-safe path after Drag-generated tracking).

    With ``trajectory_path=None`` and ``allow_discover_trajectory=True``, a CSV
    is discovered as before (debug / legacy reuse only). With
    ``allow_discover_trajectory=False``, trajectory must be supplied separately.
    """
    if trajectory_path is not None:
        paths = discover_drag_run_paths(
            run_dir,
            trajectory_path=Path(trajectory_path).resolve(),
            require_trajectory=False,
            include_trajectory_discovery=False,
        )
    else:
        paths = discover_drag_run_paths(
            run_dir,
            trajectory_path=None,
            require_trajectory=allow_discover_trajectory,
            include_trajectory_discovery=allow_discover_trajectory,
        )
    if paths.trajectory_path is None:
        raise DragIoError(
            "DRAG v1 requires a trajectory CSV. "
            "Provide trajectory_path (e.g. from Drag tracking output), or pass "
            "allow_discover_trajectory=True to reuse an on-disk trajectory (non-default)."
        )

    stage_meta = _load_stage_meta(paths.stage_meta_path)
    stage_events, stage_timing = _load_stage_trace(paths.stage_trace_path)
    (
        frame_indices,
        frame_timestamps_s,
        ts_validation_pass,
        ts_validation_msg,
    ) = _load_video_timestamps(paths.timestamps_path)

    return DragRunLoaded(
        paths=paths,
        stage_meta=stage_meta,
        stage_events=stage_events,
        stage_timing=stage_timing,
        frame_indices=frame_indices,
        frame_timestamps_s=frame_timestamps_s,
        timestamp_validation_pass=ts_validation_pass,
        timestamp_validation_message=ts_validation_msg,
    )

