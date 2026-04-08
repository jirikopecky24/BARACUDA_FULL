from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from barakuda.core import ot_report
from barakuda.core.export_xlsx import export_ot_results_xlsx
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
                "current_drag_report_path": "C:/drag/current_report.pdf",
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
    assert values[("Provenance", "Current drag report path")] == "C:/drag/current_report.pdf"
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


def test_drag_cover_status_reflects_validation_gate_fail() -> None:
    summary = {
        "status": "success",
        "item_id": "drag_item",
        "run_id": "run_1",
        "source_input_path": "C:/data/run.raw",
        "metrics": {"kappa_drag_pn_per_um": 4.0},
        "diagnostics": {
            "drag_validation_gate": "fail",
            "physics_status": "suspect_alignment_sanity",
            "physics_primary_gate": "pass",
            "detection_qc_gate": "fail",
            "final_drag_verdict": "suspect",
            "drag_force_n": 1.0e-12,
            "eta_pa_s": 0.001,
            "actual_speed_um_s": 10.0,
            "offset_um": 0.25,
            "alignment_status": "detected",
        },
    }
    left, _right = ot_report._drag_cover_rows(summary)
    status_row = next((row for row in left if row[0] == "Status"), None)
    assert status_row is not None
    assert status_row[1] == "Fail"
    combined = left + _right
    assert any(row[0] == "Primary physics gate" for row in combined)
    assert any(row[0] == "Detection QC gate" for row in combined)
    assert any(row[0] == "Final drag verdict" for row in combined)


def test_drag_report_page3_split_into_readable_blocks(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "analysis"
    base = "drag_layout"
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
            "drag_validation_gate": "suspect",
            "drag_validation_reason": "alignment_sanity_fail",
            "current_drag_report_path": "C:/drag/analysis/reports/item.pdf",
        },
    )
    summary = build_ot_item_summary(
        run_dir=run_dir,
        base_name=base,
        item_id="drag_layout_item",
        source_input_path="drag.raw",
        status="success",
    )
    class _DummyPdf:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    page_titles: list[str] = []
    monkeypatch.setattr("matplotlib.backends.backend_pdf.PdfPages", lambda _p: _DummyPdf())
    monkeypatch.setattr(ot_report, "_render_cover_page", lambda *args, **kwargs: None)
    monkeypatch.setattr(ot_report, "_render_drag_theory_page", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ot_report,
        "_render_paginated_table",
        lambda _pdf, title, *_args, **_kwargs: page_titles.append(title),
    )
    monkeypatch.setattr(ot_report, "_render_plot_pages", lambda *args, **kwargs: None)

    ot_report.export_ot_item_pdf(tmp_path / "drag_layout.pdf", summary)
    assert "Drag Provenance" in page_titles
    assert "Drag Timing and Alignment" in page_titles
    assert "Drag QC and Confidence" in page_titles
    assert "Drag Warnings" in page_titles


def test_drag_report_trace_page_prefers_relative_time_axis(tmp_path: Path) -> None:
    trace = tmp_path / "trace.csv"
    trace.write_text("video_time_rel_s,video_time_s,axis_px\n0.0,10.0,1.0\n", encoding="utf-8")
    entry = ot_report._build_plot_entry(
        "Annotated drag trace",
        str(trace),
        ("video_time_rel_s", "video_time_s", "stage_time_aligned_s"),
        ("axis_px",),
        "Time from video start [s]",
        "Axis position [px]",
        False,
        False,
    )
    assert entry is not None
    assert entry[2][0] == "video_time_rel_s"
    assert entry[4] == "Time from video start [s]"


def test_current_drag_report_path_prefers_pdf_over_summary_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "analysis"
    base = "drag_pdf_path"
    _write(
        run_dir / "audit" / "run_protocol.json",
        {
            "provenance": {
                "current_drag_report_path": "C:/drag/reports/final_report.pdf",
                "current_drag_summary_json_path": "C:/drag/audit/drag_pdf_path_drag_summary.json",
            }
        },
    )
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
        },
    )
    summary = build_ot_item_summary(
        run_dir=run_dir,
        base_name=base,
        item_id="drag_pdf_item",
        source_input_path="drag.raw",
        status="success",
    )
    assert summary["diagnostics"].get("current_drag_report_path") == "C:/drag/reports/final_report.pdf"


def test_trace_page_renders_primary_and_qc_markers(tmp_path: Path, monkeypatch) -> None:
    trace = tmp_path / "trace.csv"
    trace.write_text(
        "video_time_rel_s,video_time_s,axis_px\n0.0,10.0,1.0\n1.0,11.0,1.1\n2.0,12.0,1.2\n",
        encoding="utf-8",
    )
    summary = {
        "diagnostics": {
            "baseline_start_s": 0.0,
            "baseline_end_s": 0.5,
            "steady_start_s": 1.2,
            "steady_end_s": 1.8,
            "expected_stage_start_video_s": 11.0,
            "expected_stage_stop_video_s": 12.0,
            "detected_stage_start_video_s": 11.4,
            "detected_stage_stop_video_s": 12.4,
            "t_first_s": 10.0,
        }
    }
    labels: list[str] = []
    import matplotlib.axes

    original_axvline = matplotlib.axes.Axes.axvline

    def _capture_axvline(self, x=0, *args, **kwargs):
        label = kwargs.get("label")
        if isinstance(label, str):
            labels.append(label)
        return original_axvline(self, x, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "axvline", _capture_axvline)

    class _DummyPdf:
        def savefig(self, _fig):
            return None

    ot_report._render_drag_trace_page(_DummyPdf(), trace, summary)
    assert "expected stage start" in labels
    assert "expected stage stop" in labels
    assert "detected onset (QC)" in labels
    assert "detected stop (QC)" in labels


def test_xlsx_drag_sheet_exposes_gate_and_verdict_fields(tmp_path: Path) -> None:
    base = "drag_xlsx"
    run_dir = tmp_path / "analysis"
    output_dir = run_dir / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_dir = run_dir / "csv"
    audit_dir = run_dir / "audit"
    csv_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    traj = csv_dir / f"{base}_trajectory.csv"
    traj.write_text("frame,t_s,x_px,y_px\n0,0.0,1.0,1.0\n1,0.1,1.1,1.1\n", encoding="utf-8")
    _write(
        audit_dir / f"{base}_drag_summary.json",
        {
            "drag_force_n": 1.0e-12,
            "eta_pa_s": 0.0012,
            "physics_primary_gate": "suspect",
            "detection_qc_gate": "fail",
            "final_drag_verdict": "suspect",
            "stage_anchor_confidence": "high",
            "detected_onset_consistency_flag": False,
            "baseline_strategy_difference_ratio": 1.01,
            "speed_consistency_error_pct": 0.74,
            "measured_offset_um": 0.028,
            "expected_offset_if_eta_1mPas_um": 0.023,
        },
    )
    _write(
        audit_dir / "run_protocol.json",
        {"provenance": {"current_drag_report_path": "C:/drag/reports/drag_xlsx.pdf"}},
    )

    xlsx_path = export_ot_results_xlsx(
        output_dir=output_dir,
        base_name=base,
        trajectory_csv_path=traj,
    )
    wb = load_workbook(xlsx_path)
    ws = wb["DRAG"]
    pairs = {}
    for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
        key, value = row
        if key is None:
            continue
        pairs[str(key)] = value
    assert pairs.get("drag.physics_primary_gate") == "suspect"
    assert pairs.get("drag.detection_qc_gate") == "fail"
    assert pairs.get("drag.final_drag_verdict") == "suspect"
    assert pairs.get("drag.stage_anchor_confidence") == "high"
    assert pairs.get("drag.detected_onset_consistency_flag") in {"False", False}
    assert pairs.get("drag.baseline_strategy_difference_ratio") is not None
    assert pairs.get("drag.speed_consistency_error_pct") is not None
    assert pairs.get("drag.measured_offset_um") is not None
    assert pairs.get("drag.expected_offset_if_eta_1mPas_um") is not None
    assert pairs.get("provenance.current_drag_report_path") == "C:/drag/reports/drag_xlsx.pdf"


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
            "baseline_strategy_primary": "near_onset_baseline",
            "baseline_strategy_alt": "long_premotion_baseline_reference",
            "offset_primary_um": 0.2,
            "offset_alt_um": 0.31,
            "eta_primary_pa_s": 0.001,
            "eta_alt_pa_s": 0.0016,
            "baseline_strategy_difference_ratio": 1.6,
            "onset_confidence_class": "medium",
            "speed_stage_json": 82.0,
            "speed_trace_derived": 80.1,
            "speed_used_for_physics": 82.0,
            "speed_consistency_error_pct": 2.3,
            "drag_validation_gate": "suspect",
            "drag_validation_reason": "baseline_suspect,kinematics_suspect",
            "alignment_sanity_flag": False,
            "alignment_sanity_message": "detected_stop_after_video_end",
            "expected_stage_start_video_s": 1.2,
            "expected_stage_stop_video_s": 9.8,
            "detected_stage_start_video_s": 1.25,
            "detected_stage_stop_video_s": 10.3,
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
    rows = build_ot_summary_rows(summary)
    row_map = {(g, m): v for g, m, v, _u, _n in rows}
    assert row_map[("Drag", "Drag validation gate")] == "suspect"
    assert row_map[("Drag", "Baseline strategy difference ratio")] == pytest.approx(1.6)
    assert row_map[("Drag", "Alignment sanity flag")] is False


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


def test_brownian_conditions_qc_do_not_include_drag_na_ballast() -> None:
    summary = {
        "metrics": {
            "mode": "BROWNIAN",
            "fps": 1000.0,
            "um_per_px": 0.06042,
            "scale_source": "dataset",
            "temperature_c": 25.0,
            "bead_diameter_um": 2.0,
            "bead_radius_um": 1.0,
            "bead_source": "run_config",
        },
        "diagnostics": {
            "effective_fps": 999.0,
            "elapsed_time_s": 10.0,
            "timing_source": "timestamps",
            "selected_calibration_path": "C:/run/audit/c.json",
            "selected_trajectory_path": "C:/run/csv/t.csv",
            "selected_timestamps_path": "C:/run/raw/ts.csv",
            "report_source_kind": "brownian",
            "report_source_path": "C:/run/audit/run.json",
            "lost_fraction": 0.01,
            "camera_dropped_frames": 0,
            "tracking_lost_frames": 2,
            "timestamp_validation_pass": True,
            "timestamp_validation_message": "ok",
            "warning_count": 0,
        },
        "warnings": [],
    }
    cond_rows = ot_report._conditions_rows(summary)
    cond_labels = [r[0] for r in cond_rows]
    assert "Current drag input" not in cond_labels
    assert "Brownian baseline folder" not in cond_labels

    qc_rows = ot_report._qc_rows(summary)
    qc_labels = [r[0] for r in qc_rows]
    assert "Drag force [N]" not in qc_labels
    assert "Alignment offset [s]" not in qc_labels


def test_brownian_preview_selection_is_representative_and_limited() -> None:
    previews = [Path(f"C:/run/raw/video_preview_{i:02d}.png") for i in range(1, 11)]
    selected = ot_report._select_representative_preview_paths(previews, max_images=6)
    assert len(selected) == 6
    assert selected[0].name == "video_preview_01.png"
    assert selected[-1].name == "video_preview_10.png"


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
