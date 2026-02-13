from __future__ import annotations

"""XLSX export for run trajectories.

Goals:
- Human-friendly sheet with freeze header + filter.
- Metadata sheet with structured metadata + raw header lines from trajectory.csv.
- Never be the reason a run fails (caller should catch exceptions).

This exporter is tolerant to extra columns (e.g. OT-3.1 adds lost/drift columns).
"""

from pathlib import Path
from typing import Any

from barakuda.core.trajectory_csv_io import read_trajectory_csv


def export_trajectory_xlsx(
    run_dir: Path,
    trajectory_csv_path: Path,
    extra_metadata: dict[str, Any] | None = None,
    output_name: str = "trajectory.xlsx",
) -> Path:
    """Create run_dir/output_name with sheets Trajectory + Metadata.

    Requires openpyxl.
    """

    try:
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter
    except Exception as e:
        raise RuntimeError("openpyxl is required for XLSX export. Install it via pip/conda.") from e

    run_dir = Path(run_dir)
    trajectory_csv_path = Path(trajectory_csv_path)
    out_path = run_dir / output_name

    table = read_trajectory_csv(trajectory_csv_path)
    header = list(table.header)

    wb = Workbook()

    # --- Sheet: Trajectory ---
    ws = wb.active
    ws.title = "Trajectory"

    ws.append(header)
    for r in table.rows:
        ws.append([r.get(col, "") for col in header])

    # Usability
    ws.freeze_panes = "A2"
    if header:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}1"

    # Column widths (simple heuristic)
    for i, col in enumerate(header, start=1):
        # Use column name length and sample a few rows
        max_len = len(str(col))
        for rr in table.rows[:200]:
            v = rr.get(col, "")
            if v is None:
                continue
            max_len = max(max_len, len(str(v)))
        # Clamp to readable range
        ws.column_dimensions[get_column_letter(i)].width = float(max(10, min(28, max_len + 2)))

    # --- Sheet: Metadata ---
    ws2 = wb.create_sheet("Metadata")
    ws2.append(["Key", "Value"])

    if extra_metadata:
        for k in sorted(extra_metadata.keys()):
            v = extra_metadata[k]
            ws2.append([str(k), "" if v is None else str(v)])

    if table.meta_lines:
        ws2.append([])
        ws2.append(["trajectory.csv header lines", ""])
        for line in table.meta_lines:
            ws2.append([line, ""])

    ws2.freeze_panes = "A2"
    ws2.column_dimensions["A"].width = 34
    ws2.column_dimensions["B"].width = 90

    wb.save(out_path)
    return out_path


def export_ot_results_xlsx(
    output_dir: Path,
    base_name: str,
    trajectory_csv_path: Path,
    msd_csv_path: Path | None = None,
    psd_x_csv_path: Path | None = None,
    psd_y_csv_path: Path | None = None,
) -> Path:
    """
    Create <base_name>_results.xlsx with sheets:
      Trajectory, MSD, PSD_X, PSD_Y

    CSV files remain as canonical scientific output.
    XLSX is a human-friendly bundle (units encoded in column names, variant 1).
    """

    import csv

    try:
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter
    except Exception as e:
        raise RuntimeError("openpyxl is required for XLSX export.") from e

    output_dir = Path(output_dir)
    out_path = output_dir / f"{base_name}_results.xlsx"

    wb = Workbook()

    def _add_csv_sheet(title: str, csv_path: Path | None, *, is_first: bool = False) -> None:
        if csv_path is None or not Path(csv_path).exists():
            return
        csv_path = Path(csv_path)

        if is_first:
            ws = wb.active
            ws.title = title
        else:
            ws = wb.create_sheet(title)

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            # skip comment lines (trajectory CSV has # meta lines)
            rows: list[list[str]] = []
            for row in reader:
                if row and row[0].startswith("#"):
                    continue
                rows.append(row)

        if not rows:
            return

        for rr in rows:
            ws.append(rr)

        # freeze header + filter
        ws.freeze_panes = "A2"
        if ws.dimensions:
            ws.auto_filter.ref = ws.dimensions

        # auto-width (simple heuristic)
        for col_idx in range(1, ws.max_column + 1):
            max_len = 10
            for cell in ws.iter_rows(min_col=col_idx, max_col=col_idx, max_row=min(200, ws.max_row)):
                v = cell[0].value
                if v is not None:
                    max_len = max(max_len, len(str(v)))
            ws.column_dimensions[get_column_letter(col_idx)].width = float(min(28, max_len + 2))

    _add_csv_sheet("Trajectory", trajectory_csv_path, is_first=True)
    _add_csv_sheet("MSD", msd_csv_path)
    _add_csv_sheet("PSD_X", psd_x_csv_path)
    _add_csv_sheet("PSD_Y", psd_y_csv_path)

    # Optional: DRAG + COMPARE sheets (two-video comparison outputs)
    drag_json = output_dir / f"{base_name}_drag.json"
    compare_csv = output_dir / f"{base_name}_compare.csv"

    if drag_json.exists():
        ws = wb.create_sheet("DRAG")
        import json as _json
        payload = _json.loads(drag_json.read_text(encoding="utf-8"))
        # simple key-value dump
        row = 1
        def _emit(prefix: str, obj: Any):
            nonlocal row
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _emit(f"{prefix}{k}.", v)
            else:
                ws.cell(row=row, column=1, value=prefix[:-1] if prefix.endswith(".") else prefix)
                ws.cell(row=row, column=2, value=str(obj))
                row += 1
        _emit("", payload)

    if compare_csv.exists():
        ws = wb.create_sheet("COMPARE")
        import csv as _csv
        with compare_csv.open("r", encoding="utf-8", newline="") as f:
            r = _csv.reader(f)
            rows = list(r)
        for i, rr in enumerate(rows, start=1):
            for j, vv in enumerate(rr, start=1):
                ws.cell(row=i, column=j, value=vv)

    # Optional: CALIBRATION + HIST sheets
    cal_csv = output_dir / f"{base_name}_calibration.csv"
    if cal_csv.exists():
        ws = wb.create_sheet("CALIBRATION")
        import csv as _csv
        with cal_csv.open("r", encoding="utf-8", newline="") as f:
            rows = list(_csv.reader(f))
        for i, rr in enumerate(rows, start=1):
            for j, vv in enumerate(rr, start=1):
                ws.cell(row=i, column=j, value=vv)

    for tag in ("x", "y", "r"):
        hp = output_dir / f"{base_name}_hist_{tag}.csv"
        if hp.exists():
            ws = wb.create_sheet(f"HIST_{tag.upper()}")
            import csv as _csv
            with hp.open("r", encoding="utf-8", newline="") as f:
                rows = list(_csv.reader(f))
            for i, rr in enumerate(rows, start=1):
                for j, vv in enumerate(rr, start=1):
                    ws.cell(row=i, column=j, value=vv)

    wb.save(out_path)
    return out_path
