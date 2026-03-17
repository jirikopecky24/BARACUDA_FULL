from __future__ import annotations

import argparse
from pathlib import Path

from .analysis import analyze_drag_run
from .export import export_drag_summary_csv, export_drag_summary_json
from .plotting import plot_drag_diagnostic
from .schema import DragAnalysisConfig, DragWindowParams
from .io import DragIoError
from .alignment import DragAlignmentError
from .windows import DragWindowError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Debug CLI for OT DRAG v1 analysis.")
    parser.add_argument("--run-dir", required=True, help="Path to DRAG run folder.")
    parser.add_argument(
        "--trajectory",
        help="Optional explicit path to trajectory CSV; "
        "if omitted, <basename>_trajectory.csv in run-dir is used.",
    )
    parser.add_argument(
        "--axis",
        choices=["x", "y"],
        default="x",
        help="Analysis axis (must match stage metadata axis).",
    )
    parser.add_argument(
        "--um-per-px",
        type=float,
        default=None,
        help="Image scale in µm/px (optional, required for absolute µm outputs).",
    )
    parser.add_argument(
        "--bead-radius-um",
        type=float,
        default=None,
        help="Bead radius in µm (optional, for physics layer).",
    )
    parser.add_argument(
        "--bead-diameter-um",
        type=float,
        default=None,
        help="Bead diameter in µm (optional, for physics layer).",
    )
    parser.add_argument(
        "--eta-pa-s",
        type=float,
        default=None,
        help="Viscosity η in Pa·s (if provided, kappa is inferred from drag).",
    )
    parser.add_argument(
        "--kappa-n-per-m",
        type=float,
        default=None,
        help="Trap stiffness kappa in N/m (if provided, η is inferred from drag).",
    )
    parser.add_argument(
        "--stage-um-per-unit",
        type=float,
        default=None,
        help="Conversion factor from stage user units to µm (optional).",
    )
    parser.add_argument(
        "--manual-offset-s",
        type=float,
        default=None,
        help="Manual time offset (video - stage) in seconds; "
        "used if automatic onset detection fails.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for outputs (JSON/CSV/PNG). Defaults to run-dir.",
    )
    parser.add_argument(
        "--strict-steady",
        action="store_true",
        help="Fail if steady window is shorter than min_steady_duration_s.",
    )

    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    trajectory_path = Path(args.trajectory) if args.trajectory else None
    output_dir = Path(args.output_dir) if args.output_dir else run_dir

    cfg = DragAnalysisConfig(
        analysis_axis=args.axis,  # type: ignore[arg-type]
        um_per_px=args.um_per_px,
        bead_radius_um=args.bead_radius_um,
        bead_diameter_um=args.bead_diameter_um,
        eta_pa_s=args.eta_pa_s,
        kappa_n_per_m=args.kappa_n_per_m,
        stage_um_per_unit=args.stage_um_per_unit,
        manual_offset_s=args.manual_offset_s,
        window_params=DragWindowParams(),
        strict_steady=bool(args.strict_steady),
    )

    try:
        result = analyze_drag_run(run_dir, cfg, trajectory_path=trajectory_path)
    except (DragIoError, DragAlignmentError, DragWindowError) as e:
        print(f"[DRAG] Analysis failed: {e}")
        return 1

    json_path = export_drag_summary_json(result, output_dir)
    csv_path = export_drag_summary_csv(result, output_dir)

    # For the diagnostic plot we need the time axis and px signal again.
    from barakuda.core.trajectory_csv_io import read_trajectory_csv
    from .io import discover_drag_run_paths

    paths = discover_drag_run_paths(run_dir, trajectory_path=trajectory_path)
    traj_table = read_trajectory_csv(paths.trajectory_path)  # type: ignore[arg-type]
    frames = [int(float(r.get("frame", "0"))) for r in traj_table.rows]
    x_px = [float(r.get(f"{args.axis}_px", "nan")) for r in traj_table.rows]

    # Use timestamps for authoritative time axis
    import csv as _csv

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

    from .analysis import _interp_time_for_frames  # type: ignore[attr-defined]

    t_video = _interp_time_for_frames(ts_frames, ts_times, frames)
    png_path = plot_drag_diagnostic(t_video, x_px, result, output_dir)

    print(f"[DRAG] Summary JSON: {json_path}")
    print(f"[DRAG] Summary CSV:  {csv_path}")
    print(f"[DRAG] Diagnostic:   {png_path}")
    print(f"[DRAG] Status:       {result.analysis_status} / {result.alignment_status} / {result.physics_status}")
    if result.warnings:
        print("[DRAG] Warnings:")
        for w in result.warnings:
            print(f"  - {w}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

