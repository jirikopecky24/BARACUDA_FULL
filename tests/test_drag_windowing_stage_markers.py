from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from barakuda.devices.optical_tweezers.drag.analysis import analyze_drag_run
from barakuda.devices.optical_tweezers.drag.export import drag_result_to_dict
from barakuda.devices.optical_tweezers.drag.schema import DragAnalysisConfig, DragWindowParams
from barakuda.devices.optical_tweezers.drag.synthetic.harness import (
    SyntheticTiming,
    create_synthetic_constant_velocity_run,
)
from barakuda.devices.optical_tweezers.drag.windows import compute_windows
from barakuda.core.ot_report import build_ot_summary_rows


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


def _rewrite_stage_trace_with_velocity_profile(
    path: Path,
    *,
    motion_start_s: float,
    running_s: float,
    decel_start_s: float,
    motion_stop_s: float,
) -> None:
    rows: list[dict[str, str]] = []
    rows.append({"t_s": "0.0", "event": "script_start", "position_user": "", "velocity_user_s": "", "state": ""})
    rows.append({"t_s": f"{motion_start_s:.6f}", "event": "motion_start", "position_user": "", "velocity_user_s": "", "state": "moving"})
    rows.append(
        {
            "t_s": f"{running_s:.6f}",
            "event": "motion_running_confirmed",
            "position_user": "",
            "velocity_user_s": "",
            "state": "moving_confirmed",
        }
    )
    # synthetic profile points (steady then decel)
    t = running_s + 0.05
    pos = 0.0
    dt = 0.02
    while t < motion_stop_s - 0.01:
        if t < decel_start_s:
            vel = 20.0
        else:
            frac = min(1.0, (t - decel_start_s) / max(0.05, motion_stop_s - decel_start_s))
            vel = max(0.0, 20.0 * (1.0 - frac))
        pos += vel * dt
        rows.append(
            {
                "t_s": f"{t:.6f}",
                "event": "motion_profile",
                "position_user": f"{pos:.6f}",
                "velocity_user_s": f"{vel:.6f}",
                "state": "moving",
            }
        )
        t += dt
    rows.append(
        {
            "t_s": f"{motion_stop_s:.6f}",
            "event": "motion_stop",
            "position_user": f"{pos:.6f}",
            "velocity_user_s": "0.0",
            "state": "idle",
        }
    )
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t_s", "event", "position_user", "velocity_user_s", "state"])
        w.writeheader()
        w.writerows(rows)


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


def test_analysis_prefers_trace_velocity_profile_over_commanded_estimate(tmp_path: Path) -> None:
    timing = SyntheticTiming(fps=80.0, baseline_end_s=2.0, motion_start_s=3.0, motion_duration_s=8.0)
    run_dir = create_synthetic_constant_velocity_run(
        tmp_path / "trace_profile_decel",
        basename="trace_profile_decel",
        timing=timing,
        stage_um_per_unit=0.1,
        stage_speed_user_s=20.0,
        offset_um=0.04,
        noise_px=0.005,
    )
    trace = run_dir / "trace_profile_decel_stage_trace.csv"
    _rewrite_stage_trace_with_velocity_profile(
        trace,
        motion_start_s=timing.motion_start_s,
        running_s=timing.motion_start_s + 0.06,
        decel_start_s=timing.motion_start_s + 6.4,
        motion_stop_s=timing.motion_start_s + timing.motion_duration_s,
    )
    stage_json = run_dir / "trace_profile_decel_stage.json"
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
    assert result.deceleration_start_source == "stage_trace_velocity_profile"
    assert result.deceleration_start_stage_s is not None
    assert result.deceleration_start_stage_s == pytest.approx(timing.motion_start_s + 6.4, abs=0.15)
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
    assert "window_clipping_minor" not in str(result.final_drag_reason)
    assert result.physics_primary_gate in {"pass", "suspect"}


def test_stage_validated_relaxed_onset_is_qc_only_when_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    timing = SyntheticTiming(fps=100.0, baseline_end_s=2.0, motion_start_s=3.0, motion_duration_s=8.0)
    run_dir = create_synthetic_constant_velocity_run(
        tmp_path / "relaxed_qc_only",
        basename="relaxed_qc_only",
        timing=timing,
        stage_um_per_unit=0.1,
        stage_speed_user_s=20.0,
        offset_um=0.04,
        noise_px=0.005,
    )
    from barakuda.devices.optical_tweezers.drag import analysis as analysis_mod

    orig = analysis_mod.detect_motion_onset
    state = {"calls": 0}

    def _mock_onset(*args, **kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            _onset, diag = orig(*args, **kwargs)
            diag = type(diag)(
                baseline_end_s=diag.baseline_end_s,
                baseline_median=diag.baseline_median,
                baseline_mad=diag.baseline_mad,
                baseline_sigma=diag.baseline_sigma,
                onset_threshold_sigma=diag.onset_threshold_sigma,
                onset_threshold_abs=diag.onset_threshold_abs,
                onset_min_hold_s=diag.onset_min_hold_s,
                n_baseline_samples=diag.n_baseline_samples,
                n_total_samples=diag.n_total_samples,
                n_frames_outside_baseline=diag.n_frames_outside_baseline,
                candidate_onset_times_s=diag.candidate_onset_times_s,
                candidate_durations_s=diag.candidate_durations_s,
                failure_reason="no_segment_long_enough",
                message="forced first-pass failure",
            )
            return None, diag
        return orig(*args, **kwargs)

    monkeypatch.setattr(analysis_mod, "detect_motion_onset", _mock_onset)
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.1, eta_pa_s=0.001, bead_radius_um=1.0),
        allow_discovered_trajectory=True,
    )
    assert result.drag_anchor_mode == "stage_validated"
    assert result.relaxed_onset_used is True
    assert result.detection_qc_gate == "pass"
    assert "relaxed_onset_used" not in (result.final_drag_reason or "")


def test_marker_provenance_appears_in_export_and_report_rows(tmp_path: Path) -> None:
    timing = SyntheticTiming(fps=80.0, baseline_end_s=2.0, motion_start_s=3.0, motion_duration_s=8.0)
    run_dir = create_synthetic_constant_velocity_run(
        tmp_path / "marker_export",
        basename="marker_export",
        timing=timing,
        stage_um_per_unit=0.1,
        stage_speed_user_s=20.0,
        offset_um=0.04,
        noise_px=0.005,
    )
    stage_json = run_dir / "marker_export_stage.json"
    payload = json.loads(stage_json.read_text(encoding="utf-8"))
    payload["speed_user_s_commanded"] = 20.0
    payload["decel_user_s2_commanded"] = 100.0
    stage_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    result = analyze_drag_run(
        run_dir,
        DragAnalysisConfig(analysis_axis="x", um_per_px=0.1, eta_pa_s=0.001, bead_radius_um=1.0),
        allow_discovered_trajectory=True,
    )
    summary_dict = drag_result_to_dict(result)
    assert summary_dict["steady_start_marker_source"] is not None
    assert summary_dict["steady_end_marker_source"] is not None
    assert summary_dict["deceleration_start_source"] is not None

    summary_for_report = {
        "item_id": "marker_export",
        "status": "ok",
        "run_id": "marker_export",
        "source_input_path": str(run_dir / "marker_export.raw"),
        "metrics": {"mode": "DRAG", "kappa_drag_pn_per_um": 1.0},
        "diagnostics": {
            "report_source_kind": "drag_summary",
            "steady_start_marker_source": summary_dict["steady_start_marker_source"],
            "steady_end_marker_source": summary_dict["steady_end_marker_source"],
            "deceleration_start_source": summary_dict["deceleration_start_source"],
        },
    }
    rows = build_ot_summary_rows(summary_for_report)
    keys = {row[4] for row in rows}
    assert "steady_start_marker_source" in keys
    assert "steady_end_marker_source" in keys
    assert "deceleration_start_source" in keys


def test_manual_steady_end_override_caps_auto_window(tmp_path: Path) -> None:
    timing = SyntheticTiming(fps=100.0, baseline_end_s=2.0, motion_start_s=3.0, motion_duration_s=12.0)
    run_dir = create_synthetic_constant_velocity_run(
        tmp_path / "manual_end_cap",
        basename="manual_end_cap",
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
            steady_window_override_end_rel_s=9.0,
            steady_window_override_source="visual_stage_stability_by_concentration",
        ),
        allow_discovered_trajectory=True,
    )
    t0 = float(result.t_first_s or 0.0)
    assert result.windows.steady_end_s == pytest.approx(t0 + 9.0, abs=1e-6)
    assert result.steady_window_mode == "manual_override"
    assert result.steady_window_override_source == "visual_stage_stability_by_concentration"
    exported = drag_result_to_dict(result)
    assert exported["steady_window_mode"] == "manual_override"


def test_manual_steady_window_full_override_sets_start_and_end(tmp_path: Path) -> None:
    timing = SyntheticTiming(fps=100.0, baseline_end_s=2.0, motion_start_s=3.0, motion_duration_s=20.0)
    run_dir = create_synthetic_constant_velocity_run(
        tmp_path / "manual_window_full",
        basename="manual_window_full",
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
            steady_window_override_start_rel_s=8.0,
            steady_window_override_end_rel_s=23.0,
            steady_window_override_source="visual_stage_stability_by_concentration",
        ),
        allow_discovered_trajectory=True,
    )
    t0 = float(result.t_first_s or 0.0)
    assert result.windows.steady_start_s == pytest.approx(t0 + 8.0, abs=1e-6)
    assert result.windows.steady_end_s == pytest.approx(t0 + 23.0, abs=1e-6)
    assert result.steady_window_mode == "manual_override"
