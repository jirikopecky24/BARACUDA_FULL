from __future__ import annotations

import json
from pathlib import Path

from barakuda.devices.optical_tweezers.drag.analysis import analyze_drag_run
from barakuda.devices.optical_tweezers.drag.schema import DragAnalysisConfig
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
