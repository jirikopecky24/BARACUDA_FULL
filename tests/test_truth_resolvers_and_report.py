from __future__ import annotations

import json
from pathlib import Path

import pytest

from barakuda.core import ot_report
from barakuda.core.ot_report import build_ot_item_summary, build_ot_summary_rows
from barakuda.core.truth_resolvers import (
    build_collision_safe_export_path,
    load_and_validate_timestamps_csv,
    resolve_bead_parameters_for_run,
    resolve_scale_for_run,
    resolve_timing_truth_for_run,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_timing_truth_with_valid_timestamps(tmp_path: Path) -> None:
    video = tmp_path / "run.raw"
    video.write_bytes(b"\x00" * 16)
    ts = tmp_path / "run_timestamps.csv"
    ts.write_text(
        "frame,timestamp_s\n0,10.0\n1,10.5\n2,11.0\n",
        encoding="utf-8",
    )
    truth = resolve_timing_truth_for_run(
        video_path=video,
        frame_count=3,
        fps_hint=100.0,
        meta={"timestamps_path": str(ts)},
    )
    assert truth.timing_source == "timestamps"
    assert truth.frame_count == 3
    assert truth.elapsed_time_s == pytest.approx(1.0)
    assert truth.effective_fps == pytest.approx(2.0)


def test_timing_truth_without_timestamps_falls_back_estimated(tmp_path: Path) -> None:
    video = tmp_path / "run.raw"
    video.write_bytes(b"\x00" * 16)
    truth = resolve_timing_truth_for_run(
        video_path=video,
        frame_count=50,
        fps_hint=25.0,
        meta={},
    )
    assert truth.timing_source == "estimated"
    assert truth.elapsed_time_s == pytest.approx(2.0)
    assert truth.timestamp_validation_pass is False


def test_timing_truth_corrupted_timestamps_not_silently_accepted(tmp_path: Path) -> None:
    bad = tmp_path / "bad_timestamps.csv"
    bad.write_text(
        "frame,timestamp_s\n0,1.0\n1,0.9\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_and_validate_timestamps_csv(bad)

    video = tmp_path / "run.raw"
    video.write_bytes(b"\x00" * 16)
    truth = resolve_timing_truth_for_run(
        video_path=video,
        frame_count=2,
        fps_hint=20.0,
        meta={"timestamps_path": str(bad)},
    )
    assert truth.timing_source == "estimated"
    assert "validation failed" in truth.timestamp_validation_message


def test_bead_provenance_explicit_values() -> None:
    b1 = resolve_bead_parameters_for_run(
        bead_diameter_um=1.0,
        bead_radius_um=None,
        bead_source="run_config",
        allow_fallback=False,
    )
    assert b1.bead_diameter_um == pytest.approx(1.0)
    assert b1.bead_radius_um == pytest.approx(0.5)
    assert b1.fallback_used is False

    b2 = resolve_bead_parameters_for_run(
        bead_diameter_um=2.0,
        bead_radius_um=None,
        bead_source="run_config",
        allow_fallback=False,
    )
    assert b2.bead_diameter_um == pytest.approx(2.0)
    assert b2.bead_radius_um == pytest.approx(1.0)


def test_bead_provenance_missing_fails_fast() -> None:
    with pytest.raises(ValueError):
        resolve_bead_parameters_for_run(
            bead_diameter_um=None,
            bead_radius_um=None,
            bead_source="missing",
            allow_fallback=False,
        )


def test_drag_summary_precedence_over_legacy(tmp_path: Path) -> None:
    run_dir = tmp_path / "analysis"
    base = "item1"
    _write(
        run_dir / "audit" / "run.json",
        {"config": {"tracking": {}, "postprocess": {}, "calibration": {}}},
    )
    _write(
        run_dir / "audit" / f"{base}_drag_summary.json",
        {"drag_force_n": 1.23, "abs_offset_um": 4.56, "kappa_pn_per_um": 7.89},
    )
    _write(
        run_dir / "audit" / f"{base}_drag.json",
        {"dragging": {"drag_force_n": 9.99}, "means_um": {"offset_um": 8.88}},
    )
    _write(
        run_dir / "audit" / f"{base}_compare.json",
        {"dragging": {"kappa_pn_per_um": 6.66}, "delta": {"ratio_drag_over_brownian": 1.1}},
    )

    summary = build_ot_item_summary(
        run_dir=run_dir,
        base_name=base,
        item_id="i1",
        source_input_path="input.raw",
        status="success",
    )
    diagnostics = summary["diagnostics"]
    metrics = summary["metrics"]
    assert diagnostics["report_source_kind"] == "drag_summary"
    assert diagnostics["drag_force_n"] == pytest.approx(1.23)
    assert diagnostics["offset_um"] == pytest.approx(4.56)
    assert metrics["kappa_drag_pn_per_um"] == pytest.approx(7.89)


def test_drag_report_reads_provenance_and_alignment_from_summary(tmp_path: Path) -> None:
    run_dir = tmp_path / "analysis"
    base = "drag_item"
    _write(
        run_dir / "audit" / "run.json",
        {"config": {"tracking": {}, "postprocess": {}, "calibration": {}}, "provenance": {}},
    )
    _write(
        run_dir / "audit" / f"{base}_drag_summary.json",
        {
            "drag_force_n": 1.23e-12,
            "abs_offset_um": 0.45,
            "kappa_pn_per_um": 6.7,
            "current_drag_input_path": "C:/drag/input.raw",
            "brownian_baseline_folder": "C:/baseline",
            "selected_calibration_path": "C:/baseline/analysis/audit/b_calibration.json",
            "selected_trajectory_path": "C:/drag/analysis/csv/drag_item_trajectory.csv",
            "selected_timestamps_path": "C:/drag/drag_item_timestamps.csv",
            "report_source_kind": "drag_summary",
            "report_source_path": "C:/drag/analysis/audit/drag_item_drag_summary.json",
            "alignment_status": "detected",
            "alignment_message": "onset detected",
            "baseline_start_s": 0.0,
            "baseline_end_s": 1.0,
            "steady_start_s": 2.0,
            "steady_end_s": 3.0,
            "actual_speed_um_s": 12.0,
            "eta_pa_s": 0.0012,
            "analysis_status": "ok",
            "physics_status": "ready",
            "warnings": ["warn1"],
        },
    )
    _write(
        run_dir / "audit" / f"{base}_alignment_diagnostics.json",
        {
            "baseline_end_s": 1.0,
            "baseline_median": 10.1,
            "baseline_mad": 0.2,
            "baseline_sigma": 0.3,
            "onset_threshold_sigma": 5.0,
            "onset_threshold_abs": 1.5,
            "onset_min_hold_s": 0.3,
            "n_baseline_samples": 100,
            "n_total_samples": 500,
            "n_frames_outside_baseline": 50,
            "candidate_onset_times_s": [2.1],
            "candidate_durations_s": [0.7],
            "failure_reason": "",
            "message": "ok",
        },
    )

    summary = build_ot_item_summary(
        run_dir=run_dir,
        base_name=base,
        item_id="i3",
        source_input_path="input.raw",
        status="success",
    )
    diagnostics = summary["diagnostics"]
    assert diagnostics["report_source_kind"] == "drag_summary"
    assert diagnostics["selected_calibration_path"] is not None
    assert diagnostics["selected_trajectory_path"] is not None
    assert diagnostics["alignment_status"] == "detected"
    assert diagnostics["alignment_baseline_sigma"] == pytest.approx(0.3)
    assert diagnostics["analysis_status"] == "ok"
    assert "warn1" in summary["warnings"]


def test_drag_summary_rows_are_drag_mode_and_include_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "analysis"
    base = "drag_item_rows"
    _write(
        run_dir / "audit" / "run.json",
        {"config": {"tracking": {}, "postprocess": {}, "calibration": {}}, "provenance": {}},
    )
    _write(
        run_dir / "audit" / "run_protocol.json",
        {
            "provenance": {
                "current_drag_input_path": "C:/drag/current_input.raw",
                "brownian_baseline_folder": "C:/baseline",
                "report_source_kind": "drag_summary",
                "report_source_path": "C:/drag/analysis/audit/drag_item_rows_drag_summary.json",
            }
        },
    )
    _write(
        run_dir / "audit" / f"{base}_drag_summary.json",
        {
            "drag_force_n": 1.5e-12,
            "abs_offset_um": 0.4,
            "kappa_pn_per_um": 5.5,
            "actual_speed_um_s": 8.0,
            "eta_pa_s": 0.0011,
            "analysis_status": "ok",
            "physics_status": "ready",
            "report_source_kind": "drag_summary",
            "report_source_path": "C:/drag/analysis/audit/drag_item_rows_drag_summary.json",
        },
    )
    summary = build_ot_item_summary(
        run_dir=run_dir,
        base_name=base,
        item_id="dr1",
        source_input_path="drag.raw",
        status="success",
    )
    assert ot_report._is_drag_report(summary) is True
    rows = build_ot_summary_rows(summary)
    values = {(group, metric): value for group, metric, value, _unit, _notes in rows}
    assert values[("Drag", "Analysis mode")] == "DRAG"
    assert values[("Drag", "Drag force")] == pytest.approx(1.5e-12)
    assert values[("Drag", "Viscosity")] == pytest.approx(0.0011)
    assert values[("Drag", "Actual speed")] == pytest.approx(8.0)
    assert values[("Drag", "Absolute offset")] == pytest.approx(0.4)
    assert values[("Provenance", "Current drag input")] == "C:/drag/current_input.raw"
    assert values[("Provenance", "Brownian baseline folder")] == "C:/baseline"
    assert values[("Provenance", "Report source kind")] == "drag_summary"


def test_drag_pdf_uses_drag_pages_not_brownian(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "analysis"
    base = "drag_pdf"
    _write(
        run_dir / "audit" / "run.json",
        {"config": {"tracking": {}, "postprocess": {}, "calibration": {}}, "provenance": {}},
    )
    _write(
        run_dir / "audit" / f"{base}_drag_summary.json",
        {
            "drag_force_n": 1.0e-12,
            "abs_offset_um": 0.2,
            "kappa_pn_per_um": 4.2,
            "actual_speed_um_s": 6.5,
            "eta_pa_s": 0.0010,
            "report_source_kind": "drag_summary",
            "report_source_path": "C:/drag/analysis/audit/drag_pdf_drag_summary.json",
        },
    )
    summary = build_ot_item_summary(
        run_dir=run_dir,
        base_name=base,
        item_id="drag_pdf_item",
        source_input_path="drag.raw",
        status="success",
    )

    class _DummyPdf:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    calls: list[str] = []

    monkeypatch.setattr("matplotlib.backends.backend_pdf.PdfPages", lambda _p: _DummyPdf())
    monkeypatch.setattr(ot_report, "_render_cover_page", lambda *args, **kwargs: calls.append("cover"))
    monkeypatch.setattr(ot_report, "_render_drag_theory_page", lambda *args, **kwargs: calls.append("drag_theory"))
    monkeypatch.setattr(ot_report, "_render_theory_page", lambda *args, **kwargs: calls.append("brownian_theory"))
    monkeypatch.setattr(ot_report, "_render_trajectory_heatmap_page", lambda *args, **kwargs: calls.append("trajectory"))
    monkeypatch.setattr(ot_report, "_render_histogram_r_and_msd_page", lambda *args, **kwargs: calls.append("hist_msd"))
    monkeypatch.setattr(ot_report, "_render_plot_pages", lambda *args, **kwargs: calls.append("plot"))
    monkeypatch.setattr(ot_report, "_render_paginated_table", lambda *args, **kwargs: calls.append("table"))
    monkeypatch.setattr(ot_report, "_render_dual_table_page", lambda *args, **kwargs: calls.append("dual"))

    ot_report.export_ot_item_pdf(tmp_path / "drag_report.pdf", summary)
    assert "drag_theory" in calls
    assert "brownian_theory" not in calls
    assert "trajectory" not in calls
    assert "hist_msd" not in calls


def test_drag_summary_parses_physics_confidence_fields(tmp_path: Path) -> None:
    run_dir = tmp_path / "analysis"
    base = "drag_conf"
    _write(
        run_dir / "audit" / "run.json",
        {"config": {"tracking": {}, "postprocess": {}, "calibration": {}}, "provenance": {}},
    )
    _write(
        run_dir / "audit" / f"{base}_drag_summary.json",
        {
            "drag_force_n": 1.0e-12,
            "abs_offset_um": 0.2,
            "kappa_pn_per_um": 4.2,
            "actual_speed_um_s": 5.5,
            "eta_pa_s": 0.001,
            "report_source_kind": "drag_summary",
            "drag_physics_confidence": "medium",
            "drag_physics_warning": "baseline sensitivity",
            "baseline_robustness_flag": "weak",
            "onset_robustness_flag": "weak",
            "kinematics_robustness_flag": "legacy_units_risky",
            "eta_current_windows": 0.001,
            "eta_alt_baseline": 0.0016,
            "offset_current_windows_um": 0.2,
            "offset_alt_baseline_um": 0.31,
            "stage_speed_from_trace_um_s": 80.1,
            "stage_speed_relative_diff": 0.02,
            "stage_speed_consistent": True,
        },
    )
    summary = build_ot_item_summary(
        run_dir=run_dir,
        base_name=base,
        item_id="c1",
        source_input_path="drag.raw",
        status="success",
    )
    diagnostics = summary["diagnostics"]
    assert diagnostics["drag_physics_confidence"] == "medium"
    assert diagnostics["baseline_robustness_flag"] == "weak"
    assert diagnostics["eta_alt_baseline"] == pytest.approx(0.0016)
    assert diagnostics["stage_speed_consistent"] is True


def test_dropped_frames_semantics_kept_separate(tmp_path: Path) -> None:
    run_dir = tmp_path / "analysis"
    base = "item2"
    _write(
        run_dir / "audit" / "run.json",
        {
            "config": {
                "tracking": {},
                "postprocess": {},
                "calibration": {},
                "acquisition": {"camera_dropped_frames": 3},
            }
        },
    )
    _write(
        run_dir / "audit" / f"{base}_postprocess.json",
        {"summary": {"qc": {"lost_frames": 11, "lost_fraction": 0.11}}},
    )
    summary = build_ot_item_summary(
        run_dir=run_dir,
        base_name=base,
        item_id="i2",
        source_input_path="input.raw",
        status="success",
    )
    diagnostics = summary["diagnostics"]
    assert diagnostics["camera_dropped_frames"] == pytest.approx(3.0)
    assert diagnostics["tracking_lost_frames"] == pytest.approx(11.0)
    assert diagnostics["lost_fraction"] == pytest.approx(0.11)


def test_scale_resolution_explicit_and_fallback() -> None:
    ok = resolve_scale_for_run(explicit_scale_um_per_px=0.06042, scale_source="dataset_sidecar")
    assert ok.um_per_px == pytest.approx(0.06042)
    assert ok.scale_source == "dataset_sidecar"
    assert ok.scale_warning is None

    missing = resolve_scale_for_run(explicit_scale_um_per_px=None, scale_source="none")
    assert missing.um_per_px is None
    assert missing.scale_warning is not None


def test_export_collision_protection(tmp_path: Path) -> None:
    exports_dir = tmp_path / "exports"
    first, coll1 = build_collision_safe_export_path(exports_dir, "results/summary.csv")
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("a", encoding="utf-8")
    second, coll2 = build_collision_safe_export_path(exports_dir, "results/summary.csv")
    assert coll1 is False
    assert coll2 is True
    assert second != first
    assert second.name.startswith("summary__dup")
