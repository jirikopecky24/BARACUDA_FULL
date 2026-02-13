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
    psd_fit_json_path: Path | None = None,
    postprocess_json_path: Path | None = None,
) -> Path:
    """
    Create/update <base_name>_trajectory.xlsx and add OT physics sheets.

    Keeps CSV as canonical scientific output. XLSX is a human-friendly bundle.
    Units must be encoded in column names in CSV (variant 1).
    """

    import csv
    import json as _json

    try:
        from openpyxl import load_workbook
    except Exception:
        # If openpyxl missing, do nothing (caller should catch if needed)
        return Path(output_dir) / f"{base_name}_trajectory.xlsx"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: ensure the trajectory workbook exists (Trajectory + Metadata)
    out_path = export_trajectory_xlsx(
        run_dir=output_dir,
        trajectory_csv_path=trajectory_csv_path,
        extra_metadata=None,
        output_name=f"{base_name}_trajectory.xlsx",
    )

    wb = load_workbook(out_path)

    def _drop_sheet(title: str) -> None:
        if title in wb.sheetnames:
            ws = wb[title]
            wb.remove(ws)

    def _write_csv_sheet(title: str, csv_path: Path) -> None:
        csv_path = Path(csv_path)
        if not csv_path.exists():
            return
        _drop_sheet(title)
        ws = wb.create_sheet(title)

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            r = csv.reader(f)
            rows = list(r)
        if not rows:
            return

        for rr in rows:
            ws.append(rr)

        # freeze header + filter
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    def _write_json_sheet(title: str, json_path: Path) -> None:
        json_path = Path(json_path)
        if not json_path.exists():
            return
        _drop_sheet(title)
        ws = wb.create_sheet(title)

        try:
            payload = _json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"error": "cannot parse json", "path": str(json_path)}

        # dump as key/value (1st level)
        ws.append(["key", "value"])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        if isinstance(payload, dict):
            for k, v in payload.items():
                ws.append([str(k), _json.dumps(v, ensure_ascii=False) if not isinstance(v, (str, int, float, bool)) else v])
        else:
            ws.append(["payload", _json.dumps(payload, ensure_ascii=False)])

    # Add sheets (only if files exist)
    if msd_csv_path is not None:
        _write_csv_sheet("msd", msd_csv_path)
    if psd_x_csv_path is not None:
        _write_csv_sheet("psd_x", psd_x_csv_path)
    if psd_y_csv_path is not None:
        _write_csv_sheet("psd_y", psd_y_csv_path)
    if psd_fit_json_path is not None:
        _write_json_sheet("psd_fit", psd_fit_json_path)
    if postprocess_json_path is not None:
        _write_json_sheet("postprocess_summary", postprocess_json_path)

    # Keep original "Trajectory" and "Metadata" sheets created by export_trajectory_xlsx
    wb.save(out_path)
    return out_path
