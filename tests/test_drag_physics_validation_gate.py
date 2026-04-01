from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from barakuda.devices.optical_tweezers.drag.analysis import analyze_drag_run
from barakuda.devices.optical_tweezers.drag.plotting import plot_drag_diagnostic
from barakuda.devices.optical_tweezers.drag.schema import DragAnalysisConfig, DragWindowParams
from barakuda.devices.optical_tweezers.drag.synthetic.harness import (
    SyntheticTiming,
    create_synthetic_constant_velocity_run,
)


def test_baseline_comparison_and_eta_dual_outputs_exist(tmp_path: Path) -> None:
    run_dir = tmp_path / "drag_baseline_compare"
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="drag_a",
        timing=SyntheticTiming(fps=100.0, baseline_end_s=3.0, motion_start_s=4.0, motion_duration_s=8.0),
        offset_um=0.03,
        noise_px=0.01,
        drift_px_per_s=0.02,
        stage_um_per_unit=0.06,
        stage_speed_user_s=20.0,
    )
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, kappa_n_per_m=3e-5, bead_radius_um=0.5),
    )
    assert result.baseline_strategy_primary == "near_onset_baseline"
    assert result.baseline_strategy_alt == "long_premotion_baseline_reference"
    assert result.offset_primary_um is not None
    assert result.offset_alt_um is not None
    assert result.eta_primary_pa_s is not None
    assert result.eta_alt_pa_s is not None
    assert result.baseline_strategy_difference_ratio is not None


def test_speed_consistency_and_validation_gate_fail_on_kinematics_mismatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "drag_speed_mismatch"
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="drag_b",
        timing=SyntheticTiming(fps=80.0, baseline_end_s=2.0, motion_start_s=2.5, motion_duration_s=8.0),
        offset_um=0.02,
        noise_px=0.005,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=10.0,
    )
    stage_meta_path = run_dir / "drag_b_stage.json"
    stage_meta = json.loads(stage_meta_path.read_text(encoding="utf-8"))
    stage_meta["actual_speed_user_s"] = 50.0
    stage_meta_path.write_text(json.dumps(stage_meta, indent=2), encoding="utf-8")

    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, kappa_n_per_m=3e-5, bead_radius_um=0.5),
    )
    assert result.speed_stage_json is not None
    assert result.speed_trace_derived is not None
    assert result.speed_consistency_error_pct is not None
    assert result.kinematics_robustness_flag == "fail"
    assert result.drag_validation_gate == "fail"


def test_replay_audit_fixture_flags_baseline_sensitivity(tmp_path: Path) -> None:
    run_dir = tmp_path / "drag_replay_fixture"
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="drag_c",
        timing=SyntheticTiming(fps=120.0, baseline_end_s=2.0, motion_start_s=3.0, motion_duration_s=10.0),
        offset_um=0.02,
        noise_px=0.01,
        drift_px_per_s=0.09,
        stage_um_per_unit=0.06,
        stage_speed_user_s=18.0,
    )
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, kappa_n_per_m=3e-5, bead_radius_um=0.5),
    )
    assert result.baseline_strategy_difference_ratio is not None
    assert result.baseline_strategy_difference_ratio > 1.0
    assert result.drag_validation_gate in {"suspect", "fail"}


def test_expected_stage_markers_follow_video_timing_truth(tmp_path: Path) -> None:
    run_dir = tmp_path / "drag_stage_markers"
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="drag_d",
        timing=SyntheticTiming(fps=60.0, baseline_end_s=2.0, motion_start_s=2.5, motion_duration_s=6.0),
        offset_um=0.02,
        noise_px=0.0,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=8.0,
    )
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, kappa_n_per_m=3e-5, bead_radius_um=0.5),
    )
    assert result.t_first_s is not None
    assert result.expected_stage_start_video_s == pytest.approx(result.t_first_s + result.motion_start_stage_s)
    assert result.expected_stage_stop_video_s == pytest.approx(result.t_first_s + float(result.motion_stop_stage_s))


def test_impossible_aligned_stop_triggers_alignment_sanity_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "drag_bad_stop"
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="drag_e",
        timing=SyntheticTiming(fps=80.0, baseline_end_s=2.0, motion_start_s=2.5, motion_duration_s=8.0),
        offset_um=0.02,
        noise_px=0.01,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=9.0,
    )
    stage_trace_path = run_dir / "drag_e_stage_trace.csv"
    stage_rows = []
    with stage_trace_path.open("r", encoding="utf-8", newline="") as sf:
        for row in csv.DictReader(sf):
            if row.get("event") == "motion_stop":
                row["t_s"] = "1000.0"
            stage_rows.append(row)
    with stage_trace_path.open("w", encoding="utf-8", newline="") as sf:
        w = csv.DictWriter(sf, fieldnames=["t_s", "event", "position_user", "velocity_user_s", "state"])
        w.writeheader()
        for row in stage_rows:
            w.writerow(row)
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, kappa_n_per_m=3e-5, bead_radius_um=0.5),
    )
    assert result.alignment_sanity_flag is False
    assert result.drag_validation_gate in {"suspect", "fail"}
    assert "detected_stop_after_video_end" in str(result.alignment_sanity_message)


def test_windows_outside_video_trigger_suspect_or_fail_gate(tmp_path: Path) -> None:
    run_dir = tmp_path / "drag_window_outside"
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="drag_f",
        timing=SyntheticTiming(fps=80.0, baseline_end_s=1.5, motion_start_s=2.0, motion_duration_s=7.0),
        offset_um=0.02,
        noise_px=0.0,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=7.0,
    )
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(
            analysis_axis="x",
            um_per_px=0.06,
            kappa_n_per_m=3e-5,
            bead_radius_um=0.5,
            manual_offset_s=0.0,
            window_params=DragWindowParams(baseline_duration_s=4.0, baseline_guard_s=0.5, steady_start_delay_s=0.5, steady_end_guard_s=0.2),
        ),
    )
    assert result.window_clipping_applied is True
    assert result.alignment_sanity_flag is False
    assert result.drag_validation_gate in {"suspect", "fail"}


def test_diagnostic_plot_uses_relative_time_primary_axis(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "drag_plot_relative"
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="drag_g",
        timing=SyntheticTiming(fps=50.0, baseline_end_s=2.0, motion_start_s=2.5, motion_duration_s=6.0),
        offset_um=0.02,
        noise_px=0.01,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=10.0,
    )
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, kappa_n_per_m=3e-5, bead_radius_um=0.5),
    )
    traj_t = []
    traj_x = []
    with (run_dir / "drag_g_timestamps.csv").open("r", encoding="utf-8", newline="") as tf:
        tr = csv.DictReader(tf)
        for row in tr:
            traj_t.append(float(row["timestamp_s"]))
    with (run_dir / "drag_g_trajectory.csv").open("r", encoding="utf-8", newline="") as xf:
        xr = csv.DictReader(xf)
        for row in xr:
            traj_x.append(float(row["x_px"]))

    captured = {"xlabel": None, "xlim_calls": []}
    import matplotlib.axes

    orig_xlabel = matplotlib.axes.Axes.set_xlabel
    orig_xlim = matplotlib.axes.Axes.set_xlim

    def _capture_xlabel(self, xlabel, *args, **kwargs):
        captured["xlabel"] = xlabel
        return orig_xlabel(self, xlabel, *args, **kwargs)

    def _capture_xlim(self, left=None, right=None, *args, **kwargs):
        captured["xlim_calls"].append(left)
        return orig_xlim(self, left, right, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "set_xlabel", _capture_xlabel)
    monkeypatch.setattr(matplotlib.axes.Axes, "set_xlim", _capture_xlim)

    out = tmp_path / "plots"
    p = plot_drag_diagnostic(traj_t, traj_x, result, out)
    assert p.is_file()
    assert captured["xlabel"] == "time from video start [s]"
    normalized_lefts = []
    for left in captured["xlim_calls"]:
        if isinstance(left, (list, tuple)):
            normalized_lefts.append(float(left[0]))
        elif left is not None:
            normalized_lefts.append(float(left))
    assert any(abs(v - 0.0) < 1e-12 for v in normalized_lefts)
