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
    XLSX bundle (variant 1) – sheet order MUST be:
      Metadata, Trajectory, MSD, PSD_X, PSD_Y, CALIBRATION, HIST_X, HIST_Y, HIST_R
    """
    import csv
    import json

    try:
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter
    except Exception as e:
        raise RuntimeError("openpyxl is required for XLSX export.") from e

    output_dir = Path(output_dir)
    trajectory_csv_path = Path(trajectory_csv_path)
    out_path = output_dir / f"{base_name}_results.xlsx"

    wb = Workbook()

    def _auto_width(ws) -> None:
        for col_idx in range(1, ws.max_column + 1):
            max_len = 10
            for cell in ws.iter_rows(min_col=col_idx, max_col=col_idx, max_row=min(200, ws.max_row)):
                v = cell[0].value
                if v is not None:
                    max_len = max(max_len, len(str(v)))
            ws.column_dimensions[get_column_letter(col_idx)].width = float(min(36, max_len + 2))

    def _add_csv_sheet(title: str, csv_path: Path | None) -> None:
        if csv_path is None or not Path(csv_path).exists():
            return
        csv_path = Path(csv_path)

        ws = wb.create_sheet(title)

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows: list[list[str]] = []
            for row in reader:
                # trajectory.csv has leading '# ...' meta lines → skip to match XLSX behaviour
                if row and str(row[0]).startswith("#"):
                    continue
                rows.append(row)

        if not rows:
            return

        for rr in rows:
            ws.append(rr)

        ws.freeze_panes = "A2"
        if ws.dimensions:
            ws.auto_filter.ref = ws.dimensions
        _auto_width(ws)

    def _flatten(prefix: str, obj: Any, out: list[tuple[str, str]]) -> None:
        if isinstance(obj, dict):
            for k in sorted(obj.keys(), key=lambda x: str(x)):
                _flatten(f"{prefix}{k}.", obj[k], out)
        elif isinstance(obj, list):
            out.append((prefix[:-1] if prefix.endswith(".") else prefix, json.dumps(obj, ensure_ascii=False)))
        else:
            key = prefix[:-1] if prefix.endswith(".") else prefix
            out.append((key, "" if obj is None else str(obj)))

    # ---- 1) Metadata FIRST (active sheet) ----
    ws_meta = wb.active
    ws_meta.title = "Metadata"
    ws_meta.append(["Key", "Value"])

    meta_pairs: list[tuple[str, str]] = []

    run_json = output_dir / "run.json"
    if run_json.exists():
        try:
            payload = json.loads(run_json.read_text(encoding="utf-8"))
            _flatten("run.", payload, meta_pairs)
        except Exception:
            meta_pairs.append(("run_json_error", "failed to parse run.json"))

    post_json = output_dir / f"{base_name}_postprocess.json"
    if post_json.exists():
        try:
            payload = json.loads(post_json.read_text(encoding="utf-8"))
            _flatten("postprocess.", payload, meta_pairs)
        except Exception:
            meta_pairs.append(("postprocess_json_error", "failed to parse *_postprocess.json"))

    # trajectory header lines into Metadata (not into Trajectory sheet)
    try:
        table = read_trajectory_csv(trajectory_csv_path)
        for i, line in enumerate(table.meta_lines):
            meta_pairs.append((f"trajectory_meta[{i}]", line))
    except Exception:
        meta_pairs.append(("trajectory_meta_error", "failed to read trajectory.csv meta lines"))

    for k, v in meta_pairs:
        ws_meta.append([k, v])

    ws_meta.freeze_panes = "A2"
    ws_meta.column_dimensions["A"].width = 44
    ws_meta.column_dimensions["B"].width = 110

    # ---- 2) Data sheets in required order ----
    _add_csv_sheet("Trajectory", trajectory_csv_path)
    _add_csv_sheet("MSD", msd_csv_path)
    _add_csv_sheet("PSD_X", psd_x_csv_path)
    _add_csv_sheet("PSD_Y", psd_y_csv_path)

    # ---- 3) Calibration ALWAYS (after PSDs) ----
    cal_csv = output_dir / f"{base_name}_calibration.csv"
    cal_json = output_dir / f"{base_name}_calibration.json"
    ws_cal = wb.create_sheet("CALIBRATION")

    if cal_csv.exists():
        with cal_csv.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        for i, rr in enumerate(rows, start=1):
            for j, vv in enumerate(rr, start=1):
                ws_cal.cell(row=i, column=j, value=vv)
    elif cal_json.exists():
        ws_cal.append(["Key", "Value"])
        try:
            payload = json.loads(cal_json.read_text(encoding="utf-8"))
            pairs: list[tuple[str, str]] = []
            _flatten("calibration.", payload, pairs)
            for k, v in pairs:
                ws_cal.append([k, v])
        except Exception:
            ws_cal.append(["calibration_json_error", "failed to parse *_calibration.json"])
    else:
        ws_cal.append(["status", "MISSING"])
        ws_cal.append(["reason", "No calibration artifacts found"])

    ws_cal.freeze_panes = "A2"
    _auto_width(ws_cal)

    # ---- 4) Hist sheets at end (X,Y,R) ----
    for tag in ("x", "y", "r"):
        hp = output_dir / f"{base_name}_hist_{tag}.csv"
        if hp.exists():
            ws = wb.create_sheet(f"HIST_{tag.upper()}")
            with hp.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            for i, rr in enumerate(rows, start=1):
                for j, vv in enumerate(rr, start=1):
                    ws.cell(row=i, column=j, value=vv)
            ws.freeze_panes = "A2"
            _auto_width(ws)

    wb.save(out_path)
    return out_path
