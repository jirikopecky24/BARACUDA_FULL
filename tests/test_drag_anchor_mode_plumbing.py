from __future__ import annotations

from pathlib import Path

from barakuda.devices.optical_tweezers.drag.analysis import analyze_drag_run
from barakuda.devices.optical_tweezers.drag.export import drag_result_to_dict
from barakuda.devices.optical_tweezers.drag.schema import DragAnalysisConfig, parse_drag_anchor_mode_param
from barakuda.devices.optical_tweezers.drag.synthetic.harness import (
    SyntheticTiming,
    create_synthetic_constant_velocity_run,
)


def test_parse_drag_anchor_mode_param_defaults_and_aliases() -> None:
    assert parse_drag_anchor_mode_param(None) == "auto"
    assert parse_drag_anchor_mode_param("") == "auto"
    assert parse_drag_anchor_mode_param("  stage_validated ") == "stage_validated"
    assert parse_drag_anchor_mode_param("DETECTED_ONSET") == "detected_onset"
    assert parse_drag_anchor_mode_param("not_a_mode") == "auto"


def test_auto_anchor_records_requested_auto_effective_stage_validated_when_valid(tmp_path: Path) -> None:
    run_dir = tmp_path / "drag_anchor_auto"
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="da_auto",
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
    assert result.drag_anchor_mode_requested == "auto"
    assert result.drag_anchor_mode == "stage_validated"
    d = drag_result_to_dict(result)
    assert d["drag_anchor_mode_requested"] == "auto"
    assert d["drag_anchor_mode_effective"] == "stage_validated"
    assert d["drag_anchor_mode"] == "stage_validated"


def test_detected_onset_requested_forces_effective_detected_onset(tmp_path: Path) -> None:
    run_dir = tmp_path / "drag_anchor_det"
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="da_det",
        timing=SyntheticTiming(fps=100.0, baseline_end_s=3.0, motion_start_s=4.0, motion_duration_s=8.0),
        offset_um=0.03,
        noise_px=0.01,
        drift_px_per_s=0.02,
        stage_um_per_unit=0.06,
        stage_speed_user_s=20.0,
    )
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(
            analysis_axis="x",
            um_per_px=0.06,
            kappa_n_per_m=3e-5,
            bead_radius_um=0.5,
            drag_anchor_mode="detected_onset",
        ),
    )
    assert result.drag_anchor_mode_requested == "detected_onset"
    assert result.drag_anchor_mode == "detected_onset"
    assert result.primary_timing_source_for_windows == "trajectory_detected_onset"
    d = drag_result_to_dict(result)
    assert d["drag_anchor_mode_requested"] == "detected_onset"
    assert d["drag_anchor_mode_effective"] == "detected_onset"
