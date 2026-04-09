"""Focused checks for Drag RAW→own tracking→Brown-in-postprocess workflow."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from barakuda.devices.optical_tweezers.drag.analysis import analyze_drag_run
from barakuda.devices.optical_tweezers.drag.export import drag_result_to_dict
from barakuda.devices.optical_tweezers.drag.io import DragIoError, discover_drag_run_paths
from barakuda.devices.optical_tweezers.drag.schema import DragAnalysisConfig, DragWindowParams
from barakuda.devices.optical_tweezers.drag.synthetic.harness import (
    SyntheticTiming,
    create_synthetic_constant_velocity_run,
)


def test_default_analyze_requires_explicit_trajectory(tmp_path: Path) -> None:
    run_dir = tmp_path / "cv"
    create_synthetic_constant_velocity_run(run_dir, basename="nodisc", axis="x")
    cfg = DragAnalysisConfig(analysis_axis="x", um_per_px=1.0, kappa_n_per_m=0.1, bead_radius_um=1.0)
    with pytest.raises(DragIoError, match="trajectory_path"):
        analyze_drag_run(run_dir, cfg)


def test_allow_discovered_trajectory_is_explicit_reuse_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "cv2"
    create_synthetic_constant_velocity_run(run_dir, basename="reuse", axis="x")
    cfg = DragAnalysisConfig(analysis_axis="x", um_per_px=1.0, kappa_n_per_m=0.1, bead_radius_um=1.0)
    r = analyze_drag_run(run_dir, cfg, allow_discovered_trajectory=True)
    assert r.trajectory_source_kind == "reused_existing_trajectory"
    assert r.trajectory_generated_in_this_workflow is False


def test_explicit_generated_kind_records_provenance(tmp_path: Path) -> None:
    run_dir = tmp_path / "cv3"
    basename = "gen"
    create_synthetic_constant_velocity_run(run_dir, basename=basename, axis="x")
    traj = run_dir / f"{basename}_trajectory.csv"
    cfg = DragAnalysisConfig(analysis_axis="x", um_per_px=1.0, kappa_n_per_m=0.1, bead_radius_um=1.0)
    r = analyze_drag_run(
        run_dir,
        cfg,
        trajectory_path=traj,
        trajectory_source_kind="generated_from_drag_raw",
        trajectory_generated_in_this_workflow=True,
    )
    assert r.trajectory_source_kind == "generated_from_drag_raw"
    assert r.trajectory_generated_in_this_workflow is True
    d = drag_result_to_dict(r)
    assert d["trajectory_source_kind"] == "generated_from_drag_raw"
    assert d["trajectory_generated_in_this_workflow"] is True
    assert d["selected_trajectory_path"]


def test_discover_without_trajectory_scan_ignores_existing_csv(tmp_path: Path) -> None:
    run_dir = tmp_path / "disc"
    run_dir.mkdir(parents=True, exist_ok=True)
    basename = "DragX"
    (run_dir / f"{basename}.raw").write_bytes(b"")
    (run_dir / f"{basename}_meta.json").write_text('{"fps":30,"frame_count":2,"width":10,"height":10}', encoding="utf-8")
    (run_dir / f"{basename}_timestamps.csv").write_text("frame,timestamp_s\n0,0\n1,0.1\n", encoding="utf-8")
    (run_dir / f"{basename}_stage.json").write_text(
        '{"axis":"x","direction":"1","actual_travel_user":1,"actual_motion_duration_s":1,"actual_speed_user_s":1}',
        encoding="utf-8",
    )
    (run_dir / f"{basename}_stage_trace.csv").write_text("t_s,event\n0,motion_start\n1,motion_stop\n", encoding="utf-8")
    (run_dir / f"{basename}_trajectory.csv").write_text("frame,t_s,x_px,y_px,quality\n0,0,0,0,1\n", encoding="utf-8")

    paths = discover_drag_run_paths(
        run_dir,
        trajectory_path=None,
        require_trajectory=False,
        include_trajectory_discovery=False,
    )
    assert paths.trajectory_path is None
    sel = paths.artifact_selection.get("trajectory_path") or {}
    assert sel.get("artifact_selection_mode") == "skipped_for_drag_generated_trajectory"


def test_generate_trajectory_never_calls_brown_calibration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from barakuda.devices.optical_tweezers.drag import pipeline as pipeline_mod

    called: list[str] = []

    def _fake_run(raw_path: Path, output_dir: Path, tracking_config=None):
        called.append("tracking")
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        p = output_dir / f"{raw_path.stem}_trajectory.csv"
        p.write_text("frame,t_s,x_px,y_px,quality\n0,0,0,0,1\n", encoding="utf-8")
        return p

    monkeypatch.setattr(pipeline_mod, "_run_tracking_to_trajectory", _fake_run)

    basename = "TrkOnly"
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{basename}.raw").write_bytes(b"")
    (run_dir / f"{basename}_meta.json").write_text('{"fps":30,"frame_count":2,"width":10,"height":10}', encoding="utf-8")
    (run_dir / f"{basename}_timestamps.csv").write_text("frame,timestamp_s\n0,0\n1,0.1\n", encoding="utf-8")
    (run_dir / f"{basename}_stage.json").write_text(
        '{"axis":"x","direction":"1","actual_travel_user":1,"actual_motion_duration_s":1,"actual_speed_user_s":1}',
        encoding="utf-8",
    )
    (run_dir / f"{basename}_stage_trace.csv").write_text("t_s,event\n0,motion_start\n1,motion_stop\n", encoding="utf-8")

    out_csv = tmp_path / "out_csv"
    traj = pipeline_mod.generate_drag_trajectory_from_raw(run_dir, out_csv)
    assert traj.is_file()
    assert called == ["tracking"]


def test_batch_drag_calibration_after_generate_order() -> None:
    import barakuda.shell.batch_controller as bc

    lines = Path(bc.__file__).read_text(encoding="utf-8").splitlines()
    drag_i = next(i for i, ln in enumerate(lines) if ln.strip() == 'if calibration_mode == "Drag":')
    window = "\n".join(lines[drag_i : drag_i + 250])
    g = window.find("generate_drag_trajectory_from_raw")
    b = window.find("load_brownian_calibration_from_folder")
    f = window.find("finalize_drag_run_from_trajectory")
    assert 0 <= g < b < f


def test_analyze_allow_discovered_default_is_false() -> None:
    sig = inspect.signature(analyze_drag_run)
    assert sig.parameters["allow_discovered_trajectory"].default is False


def test_stage_truth_first_behavior_with_explicit_drag_trajectory(tmp_path: Path) -> None:
    """Stage-truth windows with thesis-safe explicit trajectory (same case as stage-truth suite)."""
    run_dir = tmp_path / "st_explicit"
    timing = SyntheticTiming(
        fps=100.0,
        baseline_end_s=3.0,
        motion_start_s=4.0,
        motion_duration_s=8.0,
    )
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="st_off",
        timing=timing,
        offset_um=0.03,
        noise_px=0.005,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=20.0,
        timing_offset_s=0.5,
    )
    traj = run_dir / "st_off_trajectory.csv"
    cfg = DragAnalysisConfig(
        analysis_axis="x",
        um_per_px=0.06,
        kappa_n_per_m=3e-5,
        bead_radius_um=0.5,
        drag_anchor_mode="auto",
        window_params=DragWindowParams(),
    )
    r_stage = analyze_drag_run(
        run_dir,
        cfg,
        trajectory_path=traj,
        trajectory_source_kind="generated_from_drag_raw",
    )
    assert r_stage.drag_anchor_mode == "stage_validated"
    assert r_stage.primary_timing_source_for_windows == "expected_stage_start_stop"
    assert r_stage.motion_timing_primary_source == "expected_stage_timing"
    assert r_stage.detected_onset_diagnostic_only is True
    assert r_stage.expected_stage_start_video_s == pytest.approx(4.0)
    assert r_stage.motion_start_video_s_detected == pytest.approx(4.0)
