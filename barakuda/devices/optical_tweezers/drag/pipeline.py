from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

from barakuda.core.video_reader import VideoReader
from barakuda.devices.optical_tweezers.pipeline.tracking import (
    Roi,
    TrackingMethod,
    choose_tracking_polarity,
    roi_follow_center,
    track_particle,
)

from .analysis import analyze_drag_run
from .io import discover_drag_run_paths, DragIoError
from .schema import DragAnalysisConfig
from barakuda.core.run_protocol import (
    create_protocol_from_context,
    load_protocol,
    merge_protocol,
    save_protocol,
)


def _run_tracking_to_trajectory(
    raw_path: Path,
    output_dir: Path,
    tracking_config: dict[str, Any] | None = None,
) -> Path:
    """Run shared OT tracking on RAW video and write a minimal trajectory CSV.

    This is a tracking-only helper (no Brownian/drag physics). It writes:
      <basename>_trajectory.csv
    with columns:
      frame, t_s, x_px, y_px, quality
    """
    tracking_config = dict(tracking_config or {})
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reader = VideoReader(str(raw_path))
    try:
        fps = float(reader.meta.fps)
        if not np.isfinite(fps) or fps <= 0:
            raise DragIoError(f"Invalid FPS detected for {raw_path.name}: {fps}")

        n_frames = int(getattr(reader.meta, "frame_count", 0))
        if n_frames <= 0:
            raise DragIoError(f"No frames detected in video: {raw_path}")

        # Tracking defaults (RADIAL_SYMMETRY, auto polarity, full-frame ROI).
        method = TrackingMethod(tracking_config.get("method", "RADIAL_SYMMETRY"))
        blur_sigma = float(tracking_config.get("blur_sigma", 1.2))
        radial_grad_threshold = float(tracking_config.get("radial_grad_threshold", 2.0))
        invert_default = bool(tracking_config.get("invert", True))
        auto_polarity = bool(tracking_config.get("auto_polarity", True))

        init_roi = tracking_config.get(
            "roi",
            [0, 0, int(getattr(reader.meta, "width", 0)), int(getattr(reader.meta, "height", 0))],
        )
        roi_obj = Roi(*init_roi)

        t_s: list[float] = []
        x_px: list[float] = []
        y_px: list[float] = []
        quality: list[float] = []

        locked_invert = invert_default
        locked_det = None

        for fi in range(n_frames):
            frame = reader.get_frame(fi)
            if locked_det is None and auto_polarity:
                locked_invert, locked_det = choose_tracking_polarity(
                    frame,
                    roi_obj,
                    method=method,
                    blur_sigma=blur_sigma,
                    radial_grad_threshold=radial_grad_threshold,
                    annulus_enabled=False,
                    annulus_auto=False,
                    annulus_r_inner_px=None,
                    annulus_r_outer_px=None,
                    annulus_profile_smooth=3,
                    compute_device="cpu",
                )
            if fi == 0 and locked_det is not None:
                det = locked_det
                locked_det = None
            else:
                det = track_particle(
                    frame,
                    roi_obj,
                    method=method,
                    compute_device="cpu",
                    invert=locked_invert,
                    blur_sigma=blur_sigma,
                    radial_grad_threshold=radial_grad_threshold,
                    auto_polarity=False,
                    annulus_enabled=False,
                    annulus_auto=False,
                    annulus_r_inner_px=None,
                    annulus_r_outer_px=None,
                    annulus_profile_smooth=3,
                )

            t_s.append(fi / fps if fps > 0 else 0.0)
            x_px.append(float(det.x_px))
            y_px.append(float(det.y_px))
            quality.append(float(det.quality))

            roi_obj = roi_follow_center(frame.shape, roi_obj, det.x_px, det.y_px)

    finally:
        reader.close()

    basename = raw_path.stem
    traj_path = output_dir / f"{basename}_trajectory.csv"
    with traj_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "t_s", "x_px", "y_px", "quality"])
        for fi, (t, x, y, q) in enumerate(zip(t_s, x_px, y_px, quality)):
            w.writerow([fi, f"{t:.9f}", f"{x:.9f}", f"{y:.9f}", f"{q:.9f}"])

    return traj_path


def run_drag_from_raw(
    run_dir: Path,
    drag_config: DragAnalysisConfig | None = None,
    tracking_config: dict[str, Any] | None = None,
) -> tuple["DragAnalysisResult", dict[str, Path]]:
    """End-to-end DRAG pipeline over a single RAW run folder.

    Steps:
      1) Discover RAW + timestamps + stage metadata in run_dir.
      2) Run shared OT tracking-only helper to generate <basename>_trajectory.csv.
      3) Run DRAG analysis (alignment, windows, offsets, physics) over that trajectory.
      4) Export drag_summary.json/csv + drag_diagnostic.png in run_dir.

    Returns:
      (DragAnalysisResult, {"trajectory": ..., "summary_json": ..., "summary_csv": ..., "diagnostic_png": ...})
    """
    paths = discover_drag_run_paths(run_dir, trajectory_path=None)

    # A) tracking-only pass -> trajectory.csv
    traj_path = _run_tracking_to_trajectory(paths.raw_path, paths.run_dir, tracking_config=tracking_config)

    # B) DRAG analysis
    # analysis_axis here is only a default; stage metadata ultimately defines the physical axis.
    cfg = drag_config or DragAnalysisConfig(analysis_axis="x")

    from .export import (
        export_alignment_diagnostics_json,
        export_drag_summary_csv,
        export_drag_summary_json,
    )
    from .plotting import plot_drag_diagnostic
    from .analysis import _interp_time_for_frames  # reuse helper
    from barakuda.core.trajectory_csv_io import read_trajectory_csv
    import csv as _csv

    # analyze_drag_run will also reload paths via load_drag_run; we just pass explicit trajectory path
    result = analyze_drag_run(run_dir, cfg, trajectory_path=traj_path)

    protocol_path = _update_run_protocol_with_drag_analysis(
        run_dir=paths.run_dir,
        result=result,
    )

    # Exports
    summary_json = export_drag_summary_json(
        result,
        paths.run_dir,
        protocol_path=str(protocol_path) if protocol_path else None,
    )
    summary_csv = export_drag_summary_csv(
        result,
        paths.run_dir,
        protocol_path=str(protocol_path) if protocol_path else None,
    )
    alignment_diag_json = export_alignment_diagnostics_json(result, paths.run_dir)

    # Diagnostic plot needs full time axis and px signal
    traj_table = read_trajectory_csv(traj_path)
    frames = [int(float(r.get("frame", "0"))) for r in traj_table.rows]
    axis = result.axis
    sig_px = [float(r.get(f"{axis}_px", "nan")) for r in traj_table.rows]

    ts_frames: list[int] = []
    ts_times: list[float] = []
    with paths.timestamps_path.open("r", encoding="utf-8", newline="") as f:
        rdr = _csv.DictReader(f)
        for row in rdr:
            if not row:
                continue
            try:
                ts_frames.append(int(row.get("frame", "0")))
                ts_times.append(float(row.get("timestamp_s", "nan")))
            except Exception:  # noqa: BLE001
                continue

    t_video = _interp_time_for_frames(ts_frames, ts_times, frames)
    diagnostic_png = plot_drag_diagnostic(t_video, sig_px, result, paths.run_dir)

    outputs = {
        "trajectory": traj_path,
        "summary_json": summary_json,
        "summary_csv": summary_csv,
        "diagnostic_png": diagnostic_png,
        "alignment_diagnostics_json": alignment_diag_json,
    }
    return result, outputs


def _update_run_protocol_with_drag_analysis(
    *,
    run_dir: Path,
    result: "DragAnalysisResult",
) -> Path | None:
    analysis_updates: dict[str, Any] = {
        "analysis_type": "drag",
        "selected_calibration_path": result.selected_calibration_path,
        "analysis_axis": result.analysis_axis,
        "stage_axis": result.stage_axis,
        "warnings": list(result.warnings),
        "qc_flags": {
            name: value for name, value in result.qc_flags.__dict__.items()
        },
        "physics_status": result.physics_status,
        "analysis_status": result.analysis_status,
        "selected_results": {
            "drag_force_n": result.drag_force_n,
            "kappa_n_per_m": result.kappa_n_per_m,
            "kappa_pn_per_um": result.kappa_pn_per_um,
            "eta_pa_s": result.eta_pa_s,
            "actual_speed_um_s": result.actual_speed_um_s,
        },
    }
    provenance_updates: dict[str, Any] = {
        "um_per_px_source": result.um_per_px_source,
        "stage_um_per_unit_source": result.stage_um_per_unit_source,
        "kappa_source": result.kappa_source,
        "timing_source": result.timing_source,
        "motion_kinematics_source": result.motion_kinematics_source,
        "analysis_axis": result.analysis_axis,
        "stage_axis": result.stage_axis,
        "selected_stage_meta_path": result.selected_stage_meta_path,
        "selected_stage_trace_path": result.selected_stage_trace_path,
        "selected_timestamps_path": result.selected_timestamps_path,
        "selected_calibration_path": result.selected_calibration_path,
        "used_fallbacks": dict(result.used_fallbacks),
    }
    updates = {
        "identity": {
            "run_id": result.basename,
            "source_type": "analysis",
        },
        "analysis": analysis_updates,
        "provenance": provenance_updates,
    }
    try:
        existing = load_protocol(run_dir)
    except Exception:
        existing = create_protocol_from_context()
    try:
        merged = merge_protocol(existing, updates, allow_manual_overwrite=False)
        return save_protocol(merged, run_dir)
    except Exception:
        return None

