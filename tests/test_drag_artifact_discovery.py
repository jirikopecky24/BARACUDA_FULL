from __future__ import annotations

from pathlib import Path

import pytest

from barakuda.devices.optical_tweezers.drag.io import DragIoError, discover_drag_run_paths


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_minimal_item(item_root: Path, basename: str) -> Path:
    _touch(item_root / "item.json", "{}")
    acq = item_root / "acquisition"
    _touch(acq / f"{basename}.raw", "raw")
    _touch(acq / f"{basename}_meta.json", "{}")
    _touch(acq / f"{basename}_timestamps.csv", "frame,timestamp_s\n0,1.0\n1,1.1\n")
    _touch(
        acq / f"{basename}_stage.json",
        '{"axis":"x","direction":"1","actual_travel_user":1.0,"actual_motion_duration_s":1.0,"actual_speed_user_s":1.0}',
    )
    _touch(acq / f"{basename}_stage_trace.csv", "t_s,event\n0.0,motion_start\n1.0,motion_stop\n")
    return acq


def test_discovery_exact_basename_match(tmp_path: Path) -> None:
    acq = _create_minimal_item(tmp_path / "item_A", "run_A")
    _touch(tmp_path / "item_A" / "analysis" / "csv" / "run_A_trajectory.csv", "frame,t_s,x_px,y_px,quality\n")

    paths = discover_drag_run_paths(acq)
    traj_info = paths.artifact_selection["trajectory_path"]
    assert paths.trajectory_path is not None
    assert paths.trajectory_path.name == "run_A_trajectory.csv"
    assert traj_info["artifact_selection_mode"] == "exact_basename_match"
    assert traj_info["artifact_selection_warning"] is None


def test_discovery_single_candidate_fallback_for_trajectory(tmp_path: Path) -> None:
    acq = _create_minimal_item(tmp_path / "item_B", "run_B")
    _touch(tmp_path / "item_B" / "analysis" / "csv" / "Brown_water_1um_1_trajectory.csv", "frame,t_s,x_px,y_px,quality\n")

    paths = discover_drag_run_paths(acq)
    traj_info = paths.artifact_selection["trajectory_path"]
    assert paths.trajectory_path is not None
    assert paths.trajectory_path.name == "Brown_water_1um_1_trajectory.csv"
    assert traj_info["artifact_selection_mode"] == "item_scoped_single_candidate"
    assert "Fallback selection for trajectory CSV" in str(traj_info["artifact_selection_warning"])


def test_discovery_trajectory_ambiguity_fails(tmp_path: Path) -> None:
    acq = _create_minimal_item(tmp_path / "item_C", "run_C")
    csv_dir = tmp_path / "item_C" / "analysis" / "csv"
    _touch(csv_dir / "a_trajectory.csv", "frame,t_s,x_px,y_px,quality\n")
    _touch(csv_dir / "b_trajectory.csv", "frame,t_s,x_px,y_px,quality\n")

    with pytest.raises(DragIoError, match="Ambiguous trajectory CSV"):
        discover_drag_run_paths(acq)


def test_discovery_no_trajectory_candidate_fails(tmp_path: Path) -> None:
    acq = _create_minimal_item(tmp_path / "item_D", "run_D")
    with pytest.raises(DragIoError, match="Missing trajectory CSV"):
        discover_drag_run_paths(acq)


def test_discovery_ignores_outside_item_candidates(tmp_path: Path) -> None:
    acq = _create_minimal_item(tmp_path / "item_E", "run_E")
    outside = tmp_path / "other_batch" / "analysis" / "csv"
    _touch(outside / "run_E_trajectory.csv", "frame,t_s,x_px,y_px,quality\n")

    with pytest.raises(DragIoError, match="Missing trajectory CSV"):
        discover_drag_run_paths(acq)


def test_discovery_provenance_fields_present(tmp_path: Path) -> None:
    acq = _create_minimal_item(tmp_path / "item_F", "run_F")
    _touch(tmp_path / "item_F" / "analysis" / "csv" / "run_F_trajectory.csv", "frame,t_s,x_px,y_px,quality\n")

    paths = discover_drag_run_paths(acq)
    for key in ("meta_path", "timestamps_path", "stage_meta_path", "stage_trace_path", "trajectory_path"):
        assert key in paths.artifact_selection
        info = paths.artifact_selection[key]
        assert info.get("selected_artifact_path")
        assert info.get("artifact_selection_mode")
        assert "searched_directories" in info
        assert "candidate_files" in info
