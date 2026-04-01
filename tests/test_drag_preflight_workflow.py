from __future__ import annotations

from pathlib import Path

from barakuda.devices.optical_tweezers.drag.io import evaluate_drag_preflight


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_drag_minimal_folder(folder: Path, basename: str) -> Path:
    _touch(folder / f"{basename}.raw", "raw")
    _touch(folder / f"{basename}_meta.json", "{}")
    _touch(folder / f"{basename}_timestamps.csv", "frame,timestamp_s\n0,1.0\n1,1.1\n")
    _touch(
        folder / f"{basename}_stage.json",
        '{"axis":"x","direction":"1","actual_travel_user":1.0,"actual_motion_duration_s":1.0,"actual_speed_user_s":1.0}',
    )
    _touch(folder / f"{basename}_stage_trace.csv", "t_s,event\n0.0,motion_start\n1.0,motion_stop\n")
    return folder / f"{basename}.raw"


def test_preflight_full_item_with_trajectory(tmp_path: Path) -> None:
    item_root = tmp_path / "items" / "Drag_water_1um_1"
    _touch(item_root / "item.json", "{}")
    drag_input = _make_drag_minimal_folder(item_root / "acquisition", "Drag_water_1um_1")
    _touch(item_root / "analysis" / "csv" / "Drag_water_1um_1_trajectory.csv", "frame,t_s,x_px,y_px,quality\n")

    res = evaluate_drag_preflight(
        current_drag_input_path=drag_input,
        run_dir=drag_input.parent,
        brownian_baseline_folder=tmp_path / "brownian",
    )
    assert res["drag_preflight_status"] == "ready_existing_trajectory"
    assert res["current_drag_item_root"] == str(item_root.resolve())
    assert str(res["current_drag_trajectory_path"]).endswith("_trajectory.csv")


def test_preflight_standalone_without_trajectory(tmp_path: Path) -> None:
    drag_input = _make_drag_minimal_folder(tmp_path / "standalone_drag", "DragStandalone")

    res = evaluate_drag_preflight(
        current_drag_input_path=drag_input,
        run_dir=drag_input.parent,
        brownian_baseline_folder=None,
    )
    assert res["drag_preflight_status"] == "ready_tracking_required_standalone"
    assert res["current_drag_item_root"] is None
    assert res["current_drag_trajectory_path"] is None
    assert "Tracking can generate trajectory" in res["drag_preflight_message"]


def test_preflight_standalone_with_trajectory_in_same_folder(tmp_path: Path) -> None:
    drag_input = _make_drag_minimal_folder(tmp_path / "standalone_drag2", "DragStandalone2")
    _touch(drag_input.parent / "DragStandalone2_trajectory.csv", "frame,t_s,x_px,y_px,quality\n")

    res = evaluate_drag_preflight(
        current_drag_input_path=drag_input,
        run_dir=drag_input.parent,
        brownian_baseline_folder=tmp_path / "brownian_ok",
    )
    assert res["drag_preflight_status"] == "ready_existing_trajectory"
    assert str(res["current_drag_trajectory_path"]).endswith("DragStandalone2_trajectory.csv")


def test_preflight_baseline_loaded_but_drag_trajectory_missing(tmp_path: Path) -> None:
    drag_input = _make_drag_minimal_folder(tmp_path / "standalone_drag3", "DragStandalone3")
    baseline = tmp_path / "brownian_loaded"
    baseline.mkdir(parents=True, exist_ok=True)

    res = evaluate_drag_preflight(
        current_drag_input_path=drag_input,
        run_dir=drag_input.parent,
        brownian_baseline_folder=baseline,
    )
    assert res["drag_preflight_status"] == "ready_tracking_required_standalone"
    assert "Brownian baseline folder is loaded correctly but is unrelated" in res["drag_preflight_message"]


def test_preflight_message_distinguishes_item_vs_standalone(tmp_path: Path) -> None:
    # item context without trajectory
    item_root = tmp_path / "items" / "Drag_item_no_traj"
    _touch(item_root / "item.json", "{}")
    drag_input_item = _make_drag_minimal_folder(item_root / "acquisition", "Drag_item_no_traj")
    item_res = evaluate_drag_preflight(
        current_drag_input_path=drag_input_item,
        run_dir=drag_input_item.parent,
        brownian_baseline_folder=tmp_path / "brownian",
    )
    assert item_res["drag_preflight_status"] == "ready_tracking_required_item"
    assert "Current drag item has no trajectory CSV yet" in item_res["drag_preflight_message"]

