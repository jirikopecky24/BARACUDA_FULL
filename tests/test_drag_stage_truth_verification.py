"""Code-grounded checks that modern Drag timing/speed behavior matches stage-truth intent.

See DRAG_STAGE_TRUTH_VERIFICATION.md for the full narrative; these tests pin key branches.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from barakuda.devices.optical_tweezers.drag.analysis import analyze_drag_run
from barakuda.devices.optical_tweezers.drag.export import drag_result_to_dict
from barakuda.devices.optical_tweezers.drag.physics import compute_drag_force
from barakuda.devices.optical_tweezers.drag.schema import DragAnalysisConfig, DragWindowParams
from barakuda.devices.optical_tweezers.drag.synthetic.harness import (
    SyntheticTiming,
    create_synthetic_constant_velocity_run,
)


def _write_trace_start_only(run_dir: Path, basename: str, motion_start_stage_s: float) -> None:
    path = run_dir / f"{basename}_stage_trace.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "event"])
        w.writerow([0.0, "script_start"])
        w.writerow([motion_start_stage_s, "motion_start"])


def test_stage_validated_windows_use_expected_stage_time_not_detected_onset(tmp_path: Path) -> None:
    """CASE A: Video bead motion is late vs stage clock; windows still follow expected stage in video time."""
    run_dir = tmp_path / "st_offset"
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
    cfg = DragAnalysisConfig(
        analysis_axis="x",
        um_per_px=0.06,
        kappa_n_per_m=3e-5,
        bead_radius_um=0.5,
        drag_anchor_mode="auto",
    )
    r_stage = analyze_drag_run(run_dir, cfg)
    assert r_stage.drag_anchor_mode == "stage_validated"
    assert r_stage.primary_timing_source_for_windows == "expected_stage_start_stop"
    # Expected motion start in video time = t_first (0) + motion_start_stage (4.0)
    assert r_stage.expected_stage_start_video_s == pytest.approx(4.0)
    assert r_stage.motion_start_video_s_detected > 4.2  # onset follows delayed video step (~4.5)
    delay = float(cfg.window_params.steady_start_delay_s)
    assert r_stage.windows.steady_start_s == pytest.approx(4.0 + delay)

    r_det = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(
            analysis_axis="x",
            um_per_px=0.06,
            kappa_n_per_m=3e-5,
            bead_radius_um=0.5,
            drag_anchor_mode="detected_onset",
        ),
    )
    assert r_det.drag_anchor_mode == "detected_onset"
    assert r_det.windows.steady_start_s > r_stage.windows.steady_start_s + 0.2


def test_no_motion_stop_degrades_to_detected_onset_honest_summary(tmp_path: Path) -> None:
    """CASE B/C: Missing motion_stop → no validated stage window; auto and forced stage_validated fall back honestly."""
    run_dir = tmp_path / "st_no_stop"
    timing = SyntheticTiming(
        fps=100.0,
        baseline_end_s=3.0,
        motion_start_s=4.0,
        motion_duration_s=8.0,
    )
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="no_stop",
        timing=timing,
        offset_um=0.03,
        noise_px=0.01,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=20.0,
    )
    _write_trace_start_only(run_dir, "no_stop", motion_start_stage_s=timing.motion_start_s)

    r_auto = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, kappa_n_per_m=3e-5, bead_radius_um=0.5),
    )
    assert r_auto.drag_anchor_mode_requested == "auto"
    assert r_auto.drag_anchor_mode == "detected_onset"
    assert r_auto.primary_timing_source_for_windows == "trajectory_detected_onset"
    assert r_auto.stage_anchor_confidence == "low"

    r_forced = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(
            analysis_axis="x",
            um_per_px=0.06,
            kappa_n_per_m=3e-5,
            bead_radius_um=0.5,
            drag_anchor_mode="stage_validated",
        ),
    )
    assert r_forced.drag_anchor_mode_requested == "stage_validated"
    assert r_forced.drag_anchor_mode == "detected_onset"
    assert any(
        "stage_validated was requested" in w and "unavailable" in w for w in r_forced.warnings
    )
    d = drag_result_to_dict(r_forced)
    assert d["drag_anchor_mode_requested"] == "stage_validated"
    assert d["drag_anchor_mode_effective"] == "detected_onset"


def test_physics_speed_uses_actual_metric_not_trace_derived(tmp_path: Path) -> None:
    """Speed for v in Stokes path is stage.json actual_speed_um_s; trace-derived is QC only."""
    run_dir = tmp_path / "st_speed"
    timing = SyntheticTiming(
        fps=100.0,
        baseline_end_s=3.0,
        motion_start_s=4.0,
        motion_duration_s=8.0,
    )
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="spd",
        timing=timing,
        offset_um=0.03,
        noise_px=0.01,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=20.0,
        actual_travel_user=200.0,
    )
    stage_path = run_dir / "spd_stage.json"
    data = json.loads(stage_path.read_text(encoding="utf-8"))
    data["actual_metric"] = {"actual_speed_um_s": 1.234}
    stage_path.write_text(json.dumps(data), encoding="utf-8")

    r = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, eta_pa_s=0.001, bead_radius_um=0.5),
    )
    assert r.actual_speed_um_s == pytest.approx(1.234)
    assert r.speed_used_for_physics == pytest.approx(1.234)
    assert r.speed_trace_derived is not None
    assert abs(r.speed_trace_derived - 1.234) > 0.05  # trace uses travel/duration path → mismatch
    assert r.stage_speed_consistent is False
    assert r.kinematics_robustness_flag == "fail"
    assert r.drag_force_n is not None
    r_m = 0.5e-6
    v_m_s = 1.234e-6
    expect_f = compute_drag_force(0.001, r_m, v_m_s)
    assert r.drag_force_n == pytest.approx(expect_f, rel=1e-6)


def test_commanded_speed_is_provenance_only_not_physics_v(tmp_path: Path) -> None:
    """commanded_* refs come from stage protocol_params; physics v uses actual_speed_um_s."""
    run_dir = tmp_path / "st_cmd"
    timing = SyntheticTiming(
        fps=80.0,
        baseline_end_s=2.0,
        motion_start_s=3.0,
        motion_duration_s=8.0,
    )
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="cmd",
        timing=timing,
        offset_um=0.02,
        noise_px=0.005,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=12.0,
    )
    stage_path = run_dir / "cmd_stage.json"
    data = json.loads(stage_path.read_text(encoding="utf-8"))
    data["commanded_metric"] = {"commanded_speed_user_s": 999.0, "commanded_travel_user": 9999.0}
    stage_path.write_text(json.dumps(data), encoding="utf-8")

    r = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, eta_pa_s=0.001, bead_radius_um=0.5),
    )
    assert r.commanded_speed_user_s_ref == pytest.approx(999.0)
    assert r.speed_used_for_physics == pytest.approx(r.actual_speed_um_s)
    assert r.actual_speed_um_s != pytest.approx(999.0 * 0.06, abs=0.01)


def test_gates_remain_separate_from_numeric_physics_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Physics can compute (physics_status ready) while detection_qc_gate flags onset issues."""
    run_dir = tmp_path / "st_gate"
    timing = SyntheticTiming(
        fps=100.0,
        baseline_end_s=2.0,
        motion_start_s=3.0,
        motion_duration_s=6.0,
    )
    create_synthetic_constant_velocity_run(
        run_dir,
        basename="gate",
        timing=timing,
        offset_um=0.02,
        noise_px=0.0,
        drift_px_per_s=0.0,
        stage_um_per_unit=0.06,
        stage_speed_user_s=16.0,
    )
    from barakuda.devices.optical_tweezers.drag import analysis as analysis_mod

    orig = analysis_mod.detect_motion_onset

    def _shift_onset(*args, **kwargs):
        onset, diag = orig(*args, **kwargs)
        if onset is None:
            return onset, diag
        return float(onset) + 12.537, diag

    monkeypatch.setattr(analysis_mod, "detect_motion_onset", _shift_onset)
    r = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, eta_pa_s=0.001, bead_radius_um=0.5),
    )

    assert r.drag_anchor_mode == "stage_validated"
    assert r.physics_status == "ready"
    assert r.detection_qc_gate == "fail"
    assert r.final_drag_verdict == "suspect"
    assert r.physics_primary_gate in {"pass", "suspect"}
