from __future__ import annotations

import json
from pathlib import Path

from barakuda.core.ot_report import build_ot_item_summary
from barakuda.devices.optical_tweezers.drag.pipeline import run_drag_from_raw
from barakuda.devices.optical_tweezers.drag.schema import (
    AlignmentDiagnostics,
    DragAnalysisConfig,
    DragAnalysisResult,
    DragQCFlags,
    DragWindows,
)


def _touch(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _prepare_input_run(run_dir: Path, basename: str) -> Path:
    _touch(run_dir / f"{basename}.raw", "raw")
    _touch(run_dir / f"{basename}_meta.json", "{}")
    _touch(run_dir / f"{basename}_timestamps.csv", "frame,timestamp_s\n0,1.0\n1,1.1\n")
    _touch(
        run_dir / f"{basename}_stage.json",
        '{"axis":"x","direction":"1","actual_travel_user":1.0,"actual_motion_duration_s":1.0,"actual_speed_user_s":1.0}',
    )
    _touch(run_dir / f"{basename}_stage_trace.csv", "t_s,event\n0.0,motion_start\n1.0,motion_stop\n")
    return run_dir / f"{basename}.raw"


def _fake_drag_result(base: str, cfg: DragAnalysisConfig) -> DragAnalysisResult:
    return DragAnalysisResult(
        basename=base,
        axis="x",
        alignment_offset_s=0.1,
        motion_start_stage_s=0.0,
        motion_stop_stage_s=1.0,
        motion_start_video_s_detected=0.1,
        motion_stop_video_s_stage_aligned=1.1,
        windows=DragWindows(0.0, 0.5, 0.6, 1.0),
        baseline_position_px=10.0,
        steady_position_px=12.0,
        baseline_position_um=1.0,
        steady_position_um=1.2,
        offset_px_raw=2.0,
        offset_um_raw=0.2,
        offset_px_stage_signed=2.0,
        offset_um_stage_signed=0.2,
        abs_offset_um=0.2,
        actual_travel_user=1.0,
        actual_motion_duration_s=1.0,
        actual_speed_user_s=1.0,
        actual_travel_um=1.25,
        actual_speed_um_s=1.25,
        drag_force_n=1e-12,
        kappa_n_per_m=1e-6,
        kappa_pn_per_um=1.0,
        eta_pa_s=1e-3,
        analysis_status="ok",
        alignment_status="detected",
        physics_status="ready",
        qc_flags=DragQCFlags(),
        warnings=[],
        notes=[],
        alignment_diagnostics=AlignmentDiagnostics(
            baseline_end_s=0.5,
            baseline_median=10.0,
            baseline_mad=0.1,
            baseline_sigma=0.15,
            onset_threshold_sigma=5.0,
            onset_threshold_abs=0.75,
            onset_min_hold_s=0.3,
            n_baseline_samples=10,
            n_total_samples=20,
            n_frames_outside_baseline=5,
            candidate_onset_times_s=(0.7,),
            candidate_durations_s=(0.4,),
            failure_reason="",
            message="ok",
        ),
        protocol_type="constant_velocity",
        analysis_axis="x",
        stage_axis="x",
        um_per_px_source=cfg.um_per_px_source,
        stage_um_per_unit_source=cfg.stage_um_per_unit_source,
        kappa_source=cfg.kappa_source,
        selected_calibration_path=cfg.selected_calibration_path,
        selected_stage_meta_path=None,
        selected_stage_trace_path=None,
        selected_timestamps_path=None,
        selected_trajectory_path=None,
        current_drag_input_path=cfg.current_drag_input_path,
        current_drag_item_root=cfg.current_drag_item_root,
        brownian_baseline_folder=cfg.brownian_baseline_folder,
        baseline_selection_mode=cfg.baseline_selection_mode,
        drag_preflight_status=cfg.drag_preflight_status,
        drag_preflight_message=cfg.drag_preflight_message,
        current_drag_output_root=cfg.current_drag_output_root,
        current_drag_report_path=None,
        current_drag_summary_json_path=None,
        current_drag_summary_csv_path=None,
        current_drag_diagnostic_png_path=None,
        current_drag_alignment_json_path=None,
        used_fallbacks={},
        artifact_selection={},
        timing_source="timestamps",
        motion_kinematics_source="actual_metric",
        timestamp_validation_pass=True,
        timestamp_validation_message="timestamps validated",
    )


def _patch_pipeline(monkeypatch, basename: str):
    from barakuda.devices.optical_tweezers.drag import pipeline as mod
    from barakuda.devices.optical_tweezers.drag import plotting as plotting_mod

    def _fake_tracking(raw_path: Path, output_dir: Path, tracking_config=None):
        p = Path(output_dir) / f"{basename}_trajectory.csv"
        _touch(p, "frame,t_s,x_px,y_px,quality\n0,0.0,1,1,1\n1,0.1,1.1,1.1,1\n")
        return p

    def _fake_analyze(run_dir: Path, config: DragAnalysisConfig, trajectory_path: Path | None = None):
        return _fake_drag_result(basename, config)

    def _fake_plot(t_video_s, response_um, result, output_dir):
        p = Path(output_dir) / f"{basename}_drag_diagnostic.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"png")
        return p

    monkeypatch.setattr(mod, "_run_tracking_to_trajectory", _fake_tracking)
    monkeypatch.setattr(mod, "analyze_drag_run", _fake_analyze)
    monkeypatch.setattr(plotting_mod, "plot_drag_diagnostic", _fake_plot)


def test_item_based_drag_outputs_go_to_item_analysis_tree(tmp_path: Path, monkeypatch) -> None:
    item_root = tmp_path / "items" / "Item1"
    _touch(item_root / "item.json", "{}")
    in_run = item_root / "acquisition"
    basename = "Item1"
    _prepare_input_run(in_run, basename)
    _patch_pipeline(monkeypatch, basename)

    cfg = DragAnalysisConfig(
        analysis_axis="x",
        um_per_px=0.06,
        kappa_n_per_m=1e-6,
    )
    output_root = item_root / "analysis"
    result, outputs = run_drag_from_raw(in_run, cfg, output_root=output_root)

    assert str(outputs["trajectory"]).startswith(str(output_root / "csv"))
    assert str(outputs["summary_json"]).startswith(str(output_root / "audit"))
    assert str(outputs["summary_csv"]).startswith(str(output_root / "csv"))
    assert str(outputs["diagnostic_png"]).startswith(str(output_root / "results"))
    assert str(outputs["alignment_diagnostics_json"]).startswith(str(output_root / "audit"))
    assert str(outputs["windows_csv"]).startswith(str(output_root / "csv"))
    assert str(outputs["trace_annotated_csv"]).startswith(str(output_root / "csv"))
    assert (output_root / "audit").is_dir()
    assert (output_root / "csv").is_dir()
    assert (output_root / "results").is_dir()
    assert result.current_drag_output_root == str(output_root.resolve())


def test_standalone_drag_outputs_go_to_canonical_analysis_tree(tmp_path: Path, monkeypatch) -> None:
    in_run = tmp_path / "DragStandalone"
    basename = "DragStandalone"
    _prepare_input_run(in_run, basename)
    _patch_pipeline(monkeypatch, basename)

    cfg = DragAnalysisConfig(
        analysis_axis="x",
        um_per_px=0.06,
        kappa_n_per_m=1e-6,
        brownian_baseline_folder=str(tmp_path / "baseline"),
    )
    output_root = in_run / "analysis"
    result, outputs = run_drag_from_raw(in_run, cfg, output_root=output_root)

    assert str(outputs["trajectory"]).startswith(str(output_root / "csv"))
    assert not str(outputs["trajectory"]).startswith(str(in_run / f"{basename}_trajectory.csv"))
    assert str(outputs["summary_json"]).startswith(str(output_root / "audit"))
    assert str(outputs["summary_csv"]).startswith(str(output_root / "csv"))
    assert str(outputs["diagnostic_png"]).startswith(str(output_root / "results"))
    assert str(outputs["alignment_diagnostics_json"]).startswith(str(output_root / "audit"))
    assert str(outputs["windows_csv"]).startswith(str(output_root / "csv"))
    assert str(outputs["trace_annotated_csv"]).startswith(str(output_root / "csv"))
    assert not (in_run / f"{basename}_drag_summary.json").exists()
    assert not (in_run / f"{basename}_drag_summary.csv").exists()
    assert not (in_run / f"{basename}_drag_diagnostic.png").exists()
    assert not (in_run / f"{basename}_alignment_diagnostics.json").exists()
    assert result.current_drag_summary_json_path == str(outputs["summary_json"])


def test_report_assembly_reads_standalone_drag_summary(tmp_path: Path, monkeypatch) -> None:
    in_run = tmp_path / "DragReport"
    basename = "DragReport"
    _prepare_input_run(in_run, basename)
    _patch_pipeline(monkeypatch, basename)
    output_root = in_run / "analysis"

    cfg = DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, kappa_n_per_m=1e-6)
    run_drag_from_raw(in_run, cfg, output_root=output_root)

    summary = build_ot_item_summary(
        run_dir=output_root,
        base_name=basename,
        item_id="it",
        source_input_path=str(in_run / f"{basename}.raw"),
        status="success",
    )
    diagnostics = summary["diagnostics"]
    assert diagnostics.get("report_source_kind") == "drag_summary"
    assert diagnostics.get("drag_force_n") is not None
    assert diagnostics.get("report_source_path") is not None


def test_provenance_paths_are_written_to_run_protocol(tmp_path: Path, monkeypatch) -> None:
    in_run = tmp_path / "DragProv"
    basename = "DragProv"
    _prepare_input_run(in_run, basename)
    _patch_pipeline(monkeypatch, basename)
    output_root = in_run / "analysis"

    cfg = DragAnalysisConfig(
        analysis_axis="x",
        um_per_px=0.06,
        kappa_n_per_m=1e-6,
        current_drag_input_path=str((in_run / f"{basename}.raw").resolve()),
        current_drag_item_root=None,
        brownian_baseline_folder=str((tmp_path / "baseline").resolve()),
        baseline_selection_mode="explicit_ui_folder",
        drag_preflight_status="ready_tracking_required_standalone",
        drag_preflight_message="tracking required",
    )
    run_drag_from_raw(in_run, cfg, output_root=output_root)
    protocol = json.loads((output_root / "run_protocol.json").read_text(encoding="utf-8"))
    prov = protocol.get("provenance") or {}
    assert prov.get("current_drag_output_root") == str(output_root.resolve())
    assert prov.get("current_drag_summary_json_path")
    assert prov.get("current_drag_summary_csv_path")
    assert prov.get("current_drag_alignment_json_path")
    assert prov.get("current_drag_diagnostic_png_path")
    assert prov.get("report_source_kind") == "drag_summary"
    assert prov.get("report_source_path")
    assert (output_root / "audit" / "run_protocol.json").is_file()


def test_baseline_folder_not_used_as_trajectory_source(tmp_path: Path, monkeypatch) -> None:
    in_run = tmp_path / "DragBaseline"
    baseline = tmp_path / "BrownianBaseline"
    baseline.mkdir(parents=True, exist_ok=True)
    basename = "DragBaseline"
    _prepare_input_run(in_run, basename)
    _touch(baseline / f"{basename}_trajectory.csv", "frame,t_s,x_px,y_px,quality\n0,0.0,0,0,1\n")
    _patch_pipeline(monkeypatch, basename)
    output_root = in_run / "analysis"

    cfg = DragAnalysisConfig(
        analysis_axis="x",
        um_per_px=0.06,
        kappa_n_per_m=1e-6,
        brownian_baseline_folder=str(baseline.resolve()),
    )
    _, outputs = run_drag_from_raw(in_run, cfg, output_root=output_root)
    assert str(outputs["trajectory"]).startswith(str((in_run / "analysis" / "csv").resolve()))


def test_standalone_default_output_root_is_input_analysis(tmp_path: Path, monkeypatch) -> None:
    in_run = tmp_path / "DragDefaultOut"
    basename = "DragDefaultOut"
    _prepare_input_run(in_run, basename)
    _patch_pipeline(monkeypatch, basename)
    cfg = DragAnalysisConfig(analysis_axis="x", um_per_px=0.06, kappa_n_per_m=1e-6)
    _, outputs = run_drag_from_raw(in_run, cfg)
    expected_root = (in_run / "analysis").resolve()
    assert str(outputs["summary_json"]).startswith(str(expected_root / "audit"))
    assert str(outputs["summary_csv"]).startswith(str(expected_root / "csv"))
    assert str(outputs["diagnostic_png"]).startswith(str(expected_root / "results"))


def test_drag_summary_and_alignment_diagnostics_completeness(tmp_path: Path, monkeypatch) -> None:
    in_run = tmp_path / "DragComplete"
    basename = "DragComplete"
    _prepare_input_run(in_run, basename)
    _patch_pipeline(monkeypatch, basename)
    output_root = in_run / "analysis"
    cfg = DragAnalysisConfig(
        analysis_axis="x",
        um_per_px=0.06,
        kappa_n_per_m=1e-6,
        brownian_baseline_folder=str((tmp_path / "baseline").resolve()),
        current_drag_input_path=str((in_run / f"{basename}.raw").resolve()),
        drag_preflight_status="ready_tracking_required_standalone",
        drag_preflight_message="tracking required",
    )
    _, outputs = run_drag_from_raw(in_run, cfg, output_root=output_root)
    summary = json.loads(Path(outputs["summary_json"]).read_text(encoding="utf-8"))
    required_summary_keys = {
        "basename",
        "axis",
        "protocol_type",
        "analysis_axis",
        "stage_axis",
        "selected_calibration_path",
        "selected_stage_meta_path",
        "selected_stage_trace_path",
        "selected_timestamps_path",
        "selected_trajectory_path",
        "current_drag_input_path",
        "current_drag_item_root",
        "current_drag_output_root",
        "brownian_baseline_folder",
        "baseline_selection_mode",
        "drag_preflight_status",
        "drag_preflight_message",
        "report_source_kind",
        "report_source_path",
        "artifact_selection",
        "timing_source",
        "timestamp_validation_pass",
        "timestamp_validation_message",
        "kappa_source",
        "um_per_px_source",
        "motion_kinematics_source",
        "motion_start_stage_s",
        "motion_stop_stage_s",
        "motion_start_video_s_detected",
        "motion_stop_video_s_stage_aligned",
        "alignment_offset_s",
        "alignment_status",
        "alignment_message",
        "warnings",
        "baseline_start_s",
        "baseline_end_s",
        "steady_start_s",
        "steady_end_s",
        "baseline_position_px",
        "baseline_position_um",
        "steady_position_px",
        "steady_position_um",
        "offset_px_raw",
        "offset_um_raw",
        "offset_px_stage_signed",
        "offset_um_stage_signed",
        "abs_offset_um",
        "actual_travel_user",
        "actual_motion_duration_s",
        "actual_speed_user_s",
        "actual_travel_um",
        "actual_speed_um_s",
        "drag_force_n",
        "kappa_n_per_m",
        "kappa_pn_per_um",
        "eta_pa_s",
        "qc_baseline_window_ok",
        "qc_steady_window_ok",
        "qc_sufficient_steady_duration",
        "qc_alignment_confident",
        "qc_stage_speed_available",
        "qc_physics_ready",
        "qc_offset_detected",
        "drag_physics_confidence",
        "drag_physics_warning",
        "baseline_robustness_flag",
        "baseline_robustness_message",
        "onset_robustness_flag",
        "onset_robustness_message",
        "kinematics_robustness_flag",
        "kinematics_robustness_message",
        "drag_validation_gate",
        "drag_validation_reason",
        "drag_anchor_mode",
        "primary_timing_source_for_windows",
        "detected_onset_consistency_flag",
        "detected_onset_consistency_message",
        "stage_anchor_confidence",
        "stage_anchor_reason",
        "physics_primary_gate",
        "detection_qc_gate",
        "final_drag_verdict",
        "final_drag_reason",
        "stage_validated_physics_acceptable",
        "detected_onset_qc_only",
        "detected_onset_veto_applied",
        "alignment_sanity_flag",
        "alignment_sanity_message",
        "expected_stage_start_video_s",
        "expected_stage_stop_video_s",
        "detected_stage_start_video_s",
        "detected_stage_stop_video_s",
        "stage_video_start_delta_s",
        "stage_video_stop_delta_s",
        "window_clipping_applied",
        "window_clipping_message",
        "baseline_window_original_start_s",
        "baseline_window_original_end_s",
        "steady_window_original_start_s",
        "steady_window_original_end_s",
        "baseline_window_clipped_start_s",
        "baseline_window_clipped_end_s",
        "steady_window_clipped_start_s",
        "steady_window_clipped_end_s",
        "baseline_strategy_primary",
        "baseline_strategy_alt",
        "baseline_position_primary_px",
        "baseline_position_primary_um",
        "baseline_position_alt_px",
        "baseline_position_alt_um",
        "offset_primary_um",
        "offset_alt_um",
        "eta_primary_pa_s",
        "eta_alt_pa_s",
        "baseline_strategy_difference_ratio",
        "relaxed_onset_used",
        "competing_durable_candidates_count",
        "onset_candidate_density",
        "speed_stage_json",
        "speed_trace_derived",
        "speed_used_for_physics",
        "speed_consistency_error_pct",
        "expected_offset_if_eta_1mPas_um",
        "expected_offset_if_eta_from_baseline_um",
        "measured_offset_um",
        "offset_underestimation_ratio_vs_water",
        "offset_underestimation_ratio_vs_baseline",
        "offset_current_windows_um",
        "offset_alt_baseline_um",
        "eta_current_windows",
        "eta_alt_baseline",
        "baseline_reference_median_px",
        "baseline_reference_window_start_s",
        "baseline_reference_window_end_s",
        "baseline_median_delta_px",
        "baseline_median_delta_um",
        "stage_speed_from_trace_um_s",
        "stage_speed_relative_diff",
        "stage_speed_consistent",
        "onset_relaxed_used",
        "onset_competing_durable_candidates",
        "onset_ambiguity_score",
        "onset_confidence_class",
        "onset_candidate_density",
        "analysis_status",
        "physics_status",
    }
    assert required_summary_keys.issubset(set(summary.keys()))

    alignment = json.loads(Path(outputs["alignment_diagnostics_json"]).read_text(encoding="utf-8"))
    required_alignment_keys = {
        "baseline_end_s",
        "baseline_median",
        "baseline_mad",
        "baseline_sigma",
        "onset_threshold_sigma",
        "onset_threshold_abs",
        "onset_min_hold_s",
        "n_baseline_samples",
        "n_total_samples",
        "n_frames_outside_baseline",
        "candidate_onset_times_s",
        "candidate_durations_s",
        "failure_reason",
        "message",
        "onset_relaxed_used",
        "onset_competing_durable_candidates",
        "onset_ambiguity_score",
        "onset_confidence_class",
        "onset_candidate_density",
    }
    assert required_alignment_keys.issubset(set(alignment.keys()))
