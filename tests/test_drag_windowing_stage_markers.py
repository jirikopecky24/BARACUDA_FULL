from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from barakuda.devices.optical_tweezers.drag.analysis import analyze_drag_run
from barakuda.devices.optical_tweezers.drag.schema import DragAnalysisConfig, DragWindowParams
from barakuda.devices.optical_tweezers.drag.synthetic.harness import (
    SyntheticTiming,
    create_synthetic_constant_velocity_run,
)
from barakuda.devices.optical_tweezers.drag.windows import compute_windows


def _rewrite_stage_trace_with_deceleration(path: Path, decel_start_s: float) -> None:
    rows = list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))
    out: list[dict[str, str]] = []
    inserted = False
    for row in rows:
        if not inserted and row.get("event") == "motion_stop":
            out.append({"t_s": f"{decel_start_s:.9f}", "event": "deceleration_start"})
            inserted = True
        out.append({"t_s": str(row.get("t_s", "")), "event": str(row.get("event", ""))})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t_s", "event"])
        w.writeheader()
        w.writerows(out)


def test_compute_windows_uses_deceleration_marker_for_steady_end() -> None:
    params = DragWindowParams(
        baseline_duration_s=3.0,
        baseline_guard_s=0.5,
        steady_start_delay_s=2.0,
        steady_end_guard_s=0.3,
    )
    w = compute_windows(
        motion_start_video_s=10.0,
        motion_stop_video_s_stage_aligned=20.0,
        params=params,
        steady_state_start_video_s=10.5,
        deceleration_start_video_s=18.2,
    )
    assert w.baseline_end_s == pytest.approx(9.5)
    assert w.steady_start_s == pytest.approx(12.5)
    assert w.steady_end_s == pytest.approx(17.9)


def test_analysis_estimates_deceleration_start_from_stage_profile(tmp_path: Path) -> None:
    timing = SyntheticTiming(fps=80.0, baseline_end_s=2.0, motion_start_s=3.0, motion_duration_s=8.0)
    run_dir = create_synthetic_constant_velocity_run(
        tmp_path / "estimated_decel",
        basename="est_decel",
        timing=timing,
        stage_um_per_unit=0.1,
        stage_speed_user_s=20.0,
        offset_um=0.04,
        noise_px=0.005,
    )
    stage_json = run_dir / "est_decel_stage.json"
    payload = json.loads(stage_json.read_text(encoding="utf-8"))
    payload["speed_user_s_commanded"] = 20.0
    payload["decel_user_s2_commanded"] = 100.0
    stage_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(
            analysis_axis="x",
            um_per_px=0.1,
            eta_pa_s=0.001,
            bead_radius_um=1.0,
            window_params=DragWindowParams(steady_end_guard_s=0.1),
        ),
        allow_discovered_trajectory=True,
    )
    assert result.deceleration_start_source == "estimated_from_commanded_speed_decel"
    assert result.deceleration_start_video_s is not None
    assert result.expected_stage_stop_video_s is not None
    assert (result.expected_stage_stop_video_s - result.deceleration_start_video_s) == pytest.approx(0.2, abs=0.05)
    assert result.steady_end_marker_source == "deceleration_start_minus_guard"


def test_analysis_falls_back_to_motion_stop_when_deceleration_unknown(tmp_path: Path) -> None:
    timing = SyntheticTiming(fps=80.0, baseline_end_s=2.0, motion_start_s=3.0, motion_duration_s=8.0)
    run_dir = create_synthetic_constant_velocity_run(
        tmp_path / "fallback_decel",
        basename="fallback_decel",
        timing=timing,
        stage_um_per_unit=0.1,
        stage_speed_user_s=20.0,
        offset_um=0.04,
        noise_px=0.005,
    )
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(
            analysis_axis="x",
            um_per_px=0.1,
            eta_pa_s=0.001,
            bead_radius_um=1.0,
        ),
        allow_discovered_trajectory=True,
    )
    assert result.deceleration_start_source == "motion_stop_fallback"
    assert result.deceleration_start_video_s is None
    assert result.steady_end_marker_source == "motion_stop_minus_guard"


def test_baseline_clipping_no_longer_hard_fails_when_duration_is_usable(tmp_path: Path) -> None:
    timing = SyntheticTiming(fps=100.0, baseline_end_s=1.0, motion_start_s=1.2, motion_duration_s=10.0)
    run_dir = create_synthetic_constant_velocity_run(
        tmp_path / "clipped_baseline",
        basename="clipped_baseline",
        timing=timing,
        stage_um_per_unit=0.1,
        stage_speed_user_s=15.0,
        offset_um=0.05,
        noise_px=0.01,
    )
    trace_path = run_dir / "clipped_baseline_stage_trace.csv"
    _rewrite_stage_trace_with_deceleration(trace_path, decel_start_s=10.95)
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(
            analysis_axis="x",
            um_per_px=0.1,
            eta_pa_s=0.001,
            bead_radius_um=1.0,
        ),
        allow_discovered_trajectory=True,
    )
    assert result.window_clipping_applied is True
    assert "window_clipping_severe" not in str(result.final_drag_reason)
    assert result.physics_primary_gate in {"pass", "suspect"}
