from __future__ import annotations

import csv
import json
import math
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any


PAGE_SIZE = (8.27, 11.69)
BRAND_NAME = "BARAKUDA"
REPORT_NAME = "Optical Tweezers Analysis Report"
BRAND_COLOR = "#0F3D5E"
ACCENT_COLOR = "#1F6AA5"
LIGHT_BG = "#F4F7FA"
TEXT_COLOR = "#162534"
MUTED_COLOR = "#586574"
LINE_COLOR = "#CAD5E0"
PLOT_COLOR = "#1F6AA5"


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_metric_csv(path: Path | None) -> dict[str, str]:
    if path is None or not Path(path).exists():
        return {}
    out: dict[str, str] = {}
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                metric = str(row.get("metric", "")).strip()
                value = str(row.get("value", "")).strip()
                if metric:
                    out[metric] = value
    except Exception:
        return {}
    return out


def _read_first_row(path: Path | None) -> dict[str, str]:
    if path is None or not Path(path).exists():
        return {}
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return next(reader, {}) or {}
    except Exception:
        return {}


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        fv = float(value)
    except Exception:
        return None
    if not math.isfinite(fv):
        return None
    return fv


def _fmt_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "n/a"
        return f"{value:.6g}"
    return str(value)


def _fmt_measure(value: Any, unit: str = "") -> str:
    text = _fmt_value(value)
    if text == "n/a" or not unit:
        return text
    return f"{text} {unit}"


def _fmt_status(value: Any) -> str:
    text = str(value or "unknown").strip().replace("_", " ")
    return text.title()


def _first_existing(*paths: Path | None) -> Path | None:
    for path in paths:
        if path is not None and Path(path).exists():
            return Path(path)
    return None


def _chunked(items: list[Any], chunk_size: int) -> list[list[Any]]:
    if chunk_size <= 0:
        return [items]
    return [items[idx : idx + chunk_size] for idx in range(0, len(items), chunk_size)]


def _wrap(value: Any, width: int = 64) -> str:
    text = _fmt_value(value)
    if text == "n/a":
        return text
    return textwrap.fill(text, width=width, break_long_words=False, break_on_hyphens=False)


def _display_path(path_value: Any, width: int = 72) -> str:
    if not path_value:
        return "n/a"
    return textwrap.fill(str(path_value), width=width, break_long_words=False, break_on_hyphens=False)


def _presentation_key(key: str) -> str:
    mapping = {
        "item_id": "Item ID",
        "status": "Status",
        "run_id": "Run ID",
        "batch_id": "Batch ID",
        "source_input_path": "Source input",
        "analysis_dir": "Analysis directory",
        "output_root": "Output root",
        "mode": "Analysis mode",
        "fps": "Frame rate",
        "um_per_px": "Scale",
        "temperature_c": "Temperature",
        "bead_diameter_um": "Bead diameter",
        "fc_x_hz": "Corner frequency X",
        "fc_y_hz": "Corner frequency Y",
        "kappa_x_pn_per_um": "Trap stiffness X",
        "kappa_y_pn_per_um": "Trap stiffness Y",
        "eta_mean_pa_s": "Mean viscosity",
        "D_m2_s": "Diffusion coefficient",
        "lost_fraction": "Lost tracking fraction",
        "dropped_frames": "Dropped frames",
        "warning_count": "Warnings",
        "drag_force_n": "Drag force",
        "offset_um": "Drag offset",
        "kappa_drag_pn_per_um": "Drag stiffness",
        "ratio_drag_over_brownian": "Drag/Brownian stiffness ratio",
        "error": "Failure reason",
        "warnings": "Warnings detail",
        "qc_png": "QC image",
        "hist_x_png": "Histogram X image",
        "hist_y_png": "Histogram Y image",
        "hist_r_png": "Histogram R image",
        "trajectory_csv": "Trajectory CSV",
        "msd_csv": "MSD CSV",
        "psd_x_csv": "PSD X CSV",
        "psd_y_csv": "PSD Y CSV",
        "hist_x_csv": "Histogram X CSV",
        "hist_y_csv": "Histogram Y CSV",
        "hist_r_csv": "Histogram R CSV",
        "results_csv": "Results CSV",
        "xlsx": "Results workbook",
    }
    return mapping.get(key, key.replace("_", " ").title())


def _existing_artifact_rows(summary: dict[str, Any]) -> list[list[str]]:
    analysis_dir = Path(summary.get("analysis_dir")) if summary.get("analysis_dir") else None
    rows: list[list[str]] = []
    for key, path_value in sorted((summary.get("artifacts") or {}).items(), key=lambda item: str(item[0])):
        if not path_value:
            continue
        path = Path(path_value)
        if not path.exists():
            continue
        if analysis_dir is not None:
            try:
                display = str(path.relative_to(analysis_dir)).replace("\\", "/")
            except Exception:
                display = str(path)
        else:
            display = str(path)
        rows.append([_presentation_key(key), _wrap(display, width=62)])
    return rows


def build_ot_item_summary(
    *,
    run_dir: Path | None,
    base_name: str,
    item_id: str | None,
    source_input_path: str | None,
    original_input_path: str | None = None,
    resolved_video_path: str | None = None,
    status: str,
    run_id: str | None = None,
    batch_id: str | None = None,
    output_root: str | None = None,
    error: str | None = None,
    file_name: str | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir) if run_dir is not None else None
    dir_audit = run_dir / "audit" if run_dir is not None else None
    dir_csv = run_dir / "csv" if run_dir is not None else None
    dir_results = run_dir / "results" if run_dir is not None else None

    run_json = _load_json(_first_existing(dir_audit / "run.json" if dir_audit else None, run_dir / "run.json" if run_dir else None))
    post_json = _load_json(dir_audit / f"{base_name}_postprocess.json" if dir_audit else None)
    calibration_json = _load_json(dir_audit / f"{base_name}_calibration.json" if dir_audit else None)
    compare_json = _load_json(dir_audit / f"{base_name}_compare.json" if dir_audit else None)
    drag_json = _load_json(dir_audit / f"{base_name}_drag.json" if dir_audit else None)
    cal_csv = _read_metric_csv(dir_csv / f"{base_name}_calibration.csv" if dir_csv else None)
    derived_mean = _read_first_row(dir_csv / f"{base_name}_derived.csv" if dir_csv else None)

    metrics: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings: list[str] = []

    cfg = ((run_json or {}).get("config") or {})
    tracking_cfg = cfg.get("tracking") or {}
    post_cfg = cfg.get("postprocess") or {}
    cal_cfg = cfg.get("calibration") or {}

    metrics["fps"] = _parse_float(tracking_cfg.get("fps"))
    metrics["um_per_px"] = _parse_float(cal_cfg.get("um_per_px"))
    metrics["temperature_c"] = _parse_float(post_cfg.get("temperature_c"))
    metrics["bead_diameter_um"] = _parse_float(post_cfg.get("bead_diameter_um"))
    metrics["bead_radius_um"] = _parse_float(post_cfg.get("bead_radius_um"))
    metrics["mode"] = str(post_cfg.get("physics_mode") or derived_mean.get("mode") or "")
    metrics["drag_axis"] = str(post_cfg.get("drag_axis") or "")
    metrics["stage_speed_um_s"] = _parse_float(post_cfg.get("stage_speed_um_s"))

    if calibration_json:
        kappa = calibration_json.get("kappa") or {}
        viscosity = calibration_json.get("viscosity") or {}
        diffusion = calibration_json.get("diffusion") or {}
        diag = calibration_json.get("diagnostics") or {}
        anisotropy = calibration_json.get("anisotropy") or {}
        metrics["kappa_x_n_per_m"] = _parse_float(kappa.get("kappa_x_n_per_m"))
        metrics["kappa_y_n_per_m"] = _parse_float(kappa.get("kappa_y_n_per_m"))
        metrics["kappa_x_pn_per_um"] = _parse_float(kappa.get("kappa_x_pn_per_um"))
        metrics["kappa_y_pn_per_um"] = _parse_float(kappa.get("kappa_y_pn_per_um"))
        metrics["kappa_iso_ratio"] = _parse_float(kappa.get("kappa_iso_ratio"))
        metrics["eta_x_pa_s"] = _parse_float(viscosity.get("eta_x_pa_s"))
        metrics["eta_y_pa_s"] = _parse_float(viscosity.get("eta_y_pa_s"))
        metrics["eta_mean_pa_s"] = _parse_float(viscosity.get("eta_mean_pa_s"))
        metrics["D_m2_s"] = _parse_float(diffusion.get("D_m2_s"))
        diagnostics["fc_x_hz"] = _parse_float(diag.get("fc_x_hz"))
        diagnostics["fc_y_hz"] = _parse_float(diag.get("fc_y_hz"))
        diagnostics["n_used"] = _parse_float(diag.get("n_used"))
        diagnostics["eta_primary_pa_s"] = _parse_float(anisotropy.get("eta_primary_pa_s"))
        diagnostics["eta_primary_axis"] = anisotropy.get("eta_primary_axis")

    for key in (
        "kappa_x_n_per_m",
        "kappa_y_n_per_m",
        "kappa_x_pn_per_um",
        "kappa_y_pn_per_um",
        "kappa_iso_ratio",
        "eta_x_pa_s",
        "eta_y_pa_s",
        "eta_mean_pa_s",
        "D_m2_s",
        "fc_x_hz",
        "fc_y_hz",
    ):
        if key in metrics and metrics[key] is not None:
            continue
        if key in diagnostics and diagnostics[key] is not None:
            continue
        csv_key = key
        if csv_key in cal_csv:
            val = _parse_float(cal_csv[csv_key])
            if key.startswith("fc_"):
                diagnostics[key] = val
            else:
                metrics[key] = val

    if derived_mean:
        metrics["derived_axis"] = derived_mean.get("axis")
        diagnostics["derived_fc_hz"] = _parse_float(derived_mean.get("fc_hz"))
        diagnostics["derived_k_pn_um"] = _parse_float(derived_mean.get("k_pN_um"))
        diagnostics["derived_eta_pa_s"] = _parse_float(derived_mean.get("eta_Pa_s"))
        diagnostics["derived_gamma_ns_m"] = _parse_float(derived_mean.get("gamma_Ns_m"))
        diagnostics["derived_D_um2_s"] = _parse_float(derived_mean.get("D_um2_s"))

    if compare_json:
        delta = compare_json.get("delta") or {}
        dragging = compare_json.get("dragging") or {}
        metrics["kappa_drag_pn_per_um"] = _parse_float(dragging.get("kappa_pn_per_um"))
        diagnostics["ratio_drag_over_brownian"] = _parse_float(delta.get("ratio_drag_over_brownian"))
        diagnostics["delta_n_per_m"] = _parse_float(delta.get("delta_n_per_m"))
    if drag_json:
        dragging = drag_json.get("dragging") or {}
        means_um = drag_json.get("means_um") or {}
        diagnostics["drag_force_n"] = _parse_float(dragging.get("drag_force_n"))
        diagnostics["offset_um"] = _parse_float(means_um.get("offset_um"))

    if post_json:
        pp_summary = post_json.get("summary") or {}
        qc = pp_summary.get("qc") or {}
        diagnostics["lost_frames"] = _parse_float(qc.get("lost_frames"))
        diagnostics["dropped_frames"] = diagnostics["lost_frames"]
        diagnostics["lost_fraction"] = _parse_float(qc.get("lost_fraction"))

    for warning in (post_json or {}).get("summary", {}).get("warnings", []):
        warnings.append(str(warning))
    diagnostics["warning_count"] = len(warnings)

    artifacts = {
        "analysis_dir": str(run_dir) if run_dir is not None else None,
        "audit_dir": str(dir_audit) if dir_audit is not None and dir_audit.exists() else None,
        "csv_dir": str(dir_csv) if dir_csv is not None and dir_csv.exists() else None,
        "results_dir": str(dir_results) if dir_results is not None and dir_results.exists() else None,
        "xlsx": str(dir_results / f"{base_name}_results.xlsx") if dir_results is not None else None,
        "results_csv": str(dir_csv / f"{base_name}_results.csv") if dir_csv is not None else None,
        "trajectory_csv": str(dir_csv / f"{base_name}_trajectory.csv") if dir_csv is not None else None,
        "msd_csv": str(dir_csv / f"{base_name}_msd.csv") if dir_csv is not None else None,
        "psd_x_csv": str(dir_csv / f"{base_name}_psd_x.csv") if dir_csv is not None else None,
        "psd_y_csv": str(dir_csv / f"{base_name}_psd_y.csv") if dir_csv is not None else None,
        "hist_x_csv": str(dir_csv / f"{base_name}_hist_x.csv") if dir_csv is not None else None,
        "hist_y_csv": str(dir_csv / f"{base_name}_hist_y.csv") if dir_csv is not None else None,
        "hist_r_csv": str(dir_csv / f"{base_name}_hist_r.csv") if dir_csv is not None else None,
        "qc_png": str(dir_results / f"{base_name}_qc.png") if dir_results is not None else None,
        "hist_x_png": str(dir_results / f"{base_name}_hist_x.png") if dir_results is not None else None,
        "hist_y_png": str(dir_results / f"{base_name}_hist_y.png") if dir_results is not None else None,
        "hist_r_png": str(dir_results / f"{base_name}_hist_r.png") if dir_results is not None else None,
    }

    return {
        "item_id": item_id or base_name,
        "base_name": base_name,
        "file_name": file_name or base_name,
        "status": status,
        "error": error,
        "run_id": run_id or ((run_json or {}).get("run_id")),
        "batch_id": batch_id,
        "source_input_path": source_input_path or ((run_json or {}).get("input_path")),
        "original_input_path": original_input_path or source_input_path or ((run_json or {}).get("input_path")),
        "resolved_video_path": resolved_video_path,
        "output_root": output_root,
        "analysis_dir": str(run_dir) if run_dir is not None else None,
        "created_at": (run_json or {}).get("created_at"),
        "metrics": metrics,
        "diagnostics": diagnostics,
        "warnings": warnings,
        "artifacts": artifacts,
    }


def build_ot_summary_rows(summary: dict[str, Any]) -> list[tuple[str, str, Any, str, str]]:
    metrics = summary.get("metrics") or {}
    diagnostics = summary.get("diagnostics") or {}
    rows: list[tuple[str, str, Any, str, str]] = [
        ("Identity", "Item ID", summary.get("item_id"), "", "item_id"),
        ("Identity", "Status", _fmt_status(summary.get("status")), "", "status"),
        ("Identity", "Run ID", summary.get("run_id"), "", "run_id"),
        ("Identity", "Batch ID", summary.get("batch_id"), "", "batch_id"),
        ("Identity", "Source input", summary.get("source_input_path"), "", "source_input_path"),
        ("Identity", "Analysis directory", summary.get("analysis_dir"), "", "analysis_dir"),
        ("Identity", "Output root", summary.get("output_root"), "", "output_root"),
        ("Input", "Analysis mode", metrics.get("mode"), "", "mode"),
        ("Input", "Frame rate", metrics.get("fps"), "Hz", "fps"),
        ("Input", "Scale", metrics.get("um_per_px"), "um/px", "um_per_px"),
        ("Input", "Temperature", metrics.get("temperature_c"), "C", "temperature_c"),
        ("Input", "Bead diameter", metrics.get("bead_diameter_um"), "um", "bead_diameter_um"),
        ("Key results", "Corner frequency X", diagnostics.get("fc_x_hz"), "Hz", "fc_x_hz"),
        ("Key results", "Corner frequency Y", diagnostics.get("fc_y_hz"), "Hz", "fc_y_hz"),
        ("Key results", "Trap stiffness X", metrics.get("kappa_x_pn_per_um"), "pN/um", "kappa_x_pn_per_um"),
        ("Key results", "Trap stiffness Y", metrics.get("kappa_y_pn_per_um"), "pN/um", "kappa_y_pn_per_um"),
        ("Key results", "Mean viscosity", metrics.get("eta_mean_pa_s"), "Pa*s", "eta_mean_pa_s"),
        ("Key results", "Diffusion coefficient", metrics.get("D_m2_s"), "m^2/s", "D_m2_s"),
        ("QC", "Lost tracking fraction", diagnostics.get("lost_fraction"), "", "lost_fraction"),
        ("QC", "Dropped frames", diagnostics.get("dropped_frames"), "frames", "dropped_frames"),
        ("QC", "Warnings", diagnostics.get("warning_count"), "", "warning_count"),
        ("Drag", "Drag force", diagnostics.get("drag_force_n"), "N", "drag_force_n"),
        ("Drag", "Drag offset", diagnostics.get("offset_um"), "um", "offset_um"),
        ("Drag", "Drag stiffness", metrics.get("kappa_drag_pn_per_um"), "pN/um", "kappa_drag_pn_per_um"),
        ("Drag", "Drag/Brownian stiffness ratio", diagnostics.get("ratio_drag_over_brownian"), "", "ratio_drag_over_brownian"),
    ]
    if summary.get("error"):
        rows.append(("Status", "Failure reason", summary.get("error"), "", "error"))
    warnings = summary.get("warnings") or []
    if warnings:
        rows.append(("QC", "Warnings detail", " | ".join(str(w) for w in warnings), "", "warnings"))
    return rows


def _identity_rows(summary: dict[str, Any]) -> list[list[str]]:
    return [
        ["Item", _wrap(summary.get("item_id"), 56)],
        ["Status", _fmt_status(summary.get("status"))],
        ["Run ID", _wrap(summary.get("run_id"), 56)],
        ["Batch ID", _wrap(summary.get("batch_id"), 56)],
        ["Generated", _wrap(summary.get("created_at") or datetime.now().isoformat(timespec="seconds"), 56)],
        ["Source input", _display_path(summary.get("source_input_path"), 58)],
        ["Output root", _display_path(summary.get("output_root"), 58)],
        ["Analysis directory", _display_path(summary.get("analysis_dir"), 58)],
    ]


def _key_result_rows(summary: dict[str, Any]) -> list[list[str]]:
    metrics = summary.get("metrics") or {}
    diagnostics = summary.get("diagnostics") or {}
    return [
        ["Mean viscosity", _fmt_measure(metrics.get("eta_mean_pa_s"), "Pa*s")],
        ["Diffusion coefficient", _fmt_measure(metrics.get("D_m2_s"), "m^2/s")],
        ["Trap stiffness X", _fmt_measure(metrics.get("kappa_x_pn_per_um"), "pN/um")],
        ["Trap stiffness Y", _fmt_measure(metrics.get("kappa_y_pn_per_um"), "pN/um")],
        ["Corner frequency X", _fmt_measure(diagnostics.get("fc_x_hz"), "Hz")],
        ["Corner frequency Y", _fmt_measure(diagnostics.get("fc_y_hz"), "Hz")],
    ]


def _conditions_rows(summary: dict[str, Any]) -> list[list[str]]:
    metrics = summary.get("metrics") or {}
    return [
        ["Analysis mode", _wrap(metrics.get("mode"), 50)],
        ["Frame rate", _fmt_measure(metrics.get("fps"), "Hz")],
        ["Scale", _fmt_measure(metrics.get("um_per_px"), "um/px")],
        ["Temperature", _fmt_measure(metrics.get("temperature_c"), "C")],
        ["Bead diameter", _fmt_measure(metrics.get("bead_diameter_um"), "um")],
        ["Bead radius", _fmt_measure(metrics.get("bead_radius_um"), "um")],
    ]


def _qc_rows(summary: dict[str, Any]) -> list[list[str]]:
    diagnostics = summary.get("diagnostics") or {}
    warnings = summary.get("warnings") or []
    rows = [
        ["Lost tracking fraction", _fmt_value(diagnostics.get("lost_fraction"))],
        ["Dropped frames", _fmt_value(diagnostics.get("dropped_frames"))],
        ["Warnings", _fmt_value(diagnostics.get("warning_count"))],
    ]
    if summary.get("error"):
        rows.append(["Failure reason", _wrap(summary.get("error"), 52)])
    if warnings:
        rows.append(["Warnings detail", _wrap(" | ".join(str(w) for w in warnings), 52)])
    return rows


def _batch_overview_rows(batch_summary: dict[str, Any], items: list[dict[str, Any]], successes: list[dict[str, Any]], failures: list[dict[str, Any]]) -> list[list[str]]:
    return [
        ["Batch ID", _wrap(batch_summary.get("batch_id"), 58)],
        ["Output root", _display_path(batch_summary.get("output_root"), 58)],
        ["Batch root", _display_path(batch_summary.get("batch_root"), 58)],
        ["Items total", str(len(items))],
        ["Successful items", str(len(successes))],
        ["Failed or stopped items", str(len(failures))],
    ]


def _batch_summary_rows(items: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in items:
        metrics = item.get("metrics") or {}
        rows.append(
            [
                _wrap(item.get("item_id"), 18),
                _fmt_status(item.get("status")),
                _fmt_measure(metrics.get("eta_mean_pa_s"), "Pa*s"),
                _fmt_measure(metrics.get("D_m2_s"), "m^2/s"),
                _fmt_measure(metrics.get("kappa_x_pn_per_um"), "pN/um"),
                _fmt_measure(metrics.get("kappa_y_pn_per_um"), "pN/um"),
            ]
        )
    return rows


def _batch_metric_rows(items: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in items:
        metrics = item.get("metrics") or {}
        diagnostics = item.get("diagnostics") or {}
        rows.append(
            [
                _wrap(item.get("item_id"), 18),
                _fmt_measure(metrics.get("eta_mean_pa_s"), "Pa*s"),
                _fmt_measure(metrics.get("D_m2_s"), "m^2/s"),
                _fmt_measure(metrics.get("kappa_x_pn_per_um"), "pN/um"),
                _fmt_measure(metrics.get("kappa_y_pn_per_um"), "pN/um"),
                _fmt_measure(diagnostics.get("fc_x_hz"), "Hz"),
                _fmt_measure(diagnostics.get("fc_y_hz"), "Hz"),
            ]
        )
    return rows


def _csv_numeric_columns(path: Path, preferred_x: tuple[str, ...], preferred_y: tuple[str, ...]) -> tuple[list[float], list[float], str, str] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(row for row in f if not row.startswith("#"))
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    fieldnames = rows[0].keys()
    x_name = next((name for name in preferred_x if name in fieldnames), None)
    y_name = next((name for name in preferred_y if name in fieldnames), None)
    if x_name is None or y_name is None:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for row in rows:
        xv = _parse_float(row.get(x_name))
        yv = _parse_float(row.get(y_name))
        if xv is None or yv is None:
            continue
        xs.append(xv)
        ys.append(yv)
    if not xs or not ys:
        return None
    return xs, ys, x_name, y_name


def _build_plot_entry(label: str, csv_path: str | None, x_opts: tuple[str, ...], y_opts: tuple[str, ...], x_title: str, y_title: str, log_x: bool, log_y: bool) -> tuple[str, Path, tuple[str, ...], tuple[str, ...], str, str, bool, bool] | None:
    if not csv_path:
        return None
    path = Path(csv_path)
    if not path.is_file():
        return None
    return (label, path, x_opts, y_opts, x_title, y_title, log_x, log_y)


def _build_image_entry(label: str, path_value: str | None) -> tuple[str, Path] | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    return (label, path)


def _style_table(table, body_font_size: int = 9, header_font_size: int = 10) -> None:
    table.auto_set_font_size(False)
    for (row_idx, _col_idx), cell in table.get_celld().items():
        cell.set_linewidth(0.6)
        cell.set_edgecolor(LINE_COLOR)
        if row_idx == 0:
            cell.set_facecolor(BRAND_COLOR)
            cell.get_text().set_color("white")
            cell.get_text().set_fontsize(header_font_size)
            cell.get_text().set_fontweight("bold")
        else:
            cell.set_facecolor(LIGHT_BG if row_idx % 2 == 0 else "white")
            cell.get_text().set_fontsize(body_font_size)
            cell.get_text().set_color(TEXT_COLOR)


def _add_brand_header(fig, title: str, subtitle: str | None = None, page_note: str | None = None) -> None:
    from matplotlib.lines import Line2D

    fig.text(0.07, 0.972, BRAND_NAME, fontsize=20, fontweight="bold", color=BRAND_COLOR)
    fig.text(0.07, 0.948, REPORT_NAME, fontsize=10.5, color=MUTED_COLOR)
    fig.text(0.07, 0.914, title, fontsize=18, fontweight="bold", color=TEXT_COLOR)
    if subtitle:
        fig.text(0.07, 0.892, subtitle, fontsize=10, color=MUTED_COLOR)
    if page_note:
        fig.text(0.93, 0.972, page_note, fontsize=9, color=MUTED_COLOR, ha="right")
    fig.add_artist(Line2D([0.07, 0.93], [0.882, 0.882], transform=fig.transFigure, color=LINE_COLOR, linewidth=1.2))


def _render_cover_page(pdf, title: str, subtitle: str, left_rows: list[list[str]], right_rows: list[list[str]]) -> None:
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=PAGE_SIZE)
    _add_brand_header(fig, title, subtitle=subtitle)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.07, 0.82, title, fontsize=24, fontweight="bold", color=TEXT_COLOR)
    ax.text(0.07, 0.785, subtitle, fontsize=11, color=MUTED_COLOR)
    ax.text(0.07, 0.735, "Prepared for direct scientific review and client-facing delivery.", fontsize=10.5, color=TEXT_COLOR)

    ax_left = fig.add_axes([0.07, 0.19, 0.39, 0.47])
    ax_left.axis("off")
    left_table = ax_left.table(
        cellText=left_rows,
        colLabels=["Report details", "Value"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    _style_table(left_table, body_font_size=9, header_font_size=10)

    ax_right = fig.add_axes([0.52, 0.25, 0.38, 0.40])
    ax_right.axis("off")
    right_table = ax_right.table(
        cellText=right_rows,
        colLabels=["Key result", "Value"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    _style_table(right_table, body_font_size=9, header_font_size=10)

    fig.text(0.07, 0.12, "Branding note: text-only BARAKUDA header is used for now and can be replaced later with a final logo asset.", fontsize=9, color=MUTED_COLOR)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _render_paginated_table(
    pdf,
    title: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    subtitle: str | None = None,
    rows_per_page: int = 16,
) -> None:
    import matplotlib.pyplot as plt

    if not rows:
        return
    chunks = _chunked(rows, rows_per_page)
    for idx, chunk in enumerate(chunks, start=1):
        fig = plt.figure(figsize=PAGE_SIZE)
        note = f"Page {idx}/{len(chunks)}" if len(chunks) > 1 else None
        _add_brand_header(fig, title, subtitle=subtitle, page_note=note)
        ax = fig.add_axes([0.07, 0.08, 0.86, 0.76])
        ax.axis("off")
        table = ax.table(
            cellText=chunk,
            colLabels=headers,
            cellLoc="left",
            colLoc="left",
            bbox=[0.0, 0.0, 1.0, 1.0],
        )
        body_font_size = 8 if len(headers) > 4 else 9
        _style_table(table, body_font_size=body_font_size, header_font_size=10)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def _render_dual_table_page(
    pdf,
    title: str,
    top_title: str,
    top_rows: list[list[str]],
    bottom_title: str,
    bottom_rows: list[list[str]],
) -> None:
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=PAGE_SIZE)
    _add_brand_header(fig, title)

    ax_top_title = fig.add_axes([0.07, 0.79, 0.86, 0.05])
    ax_top_title.axis("off")
    ax_top_title.text(0.0, 0.5, top_title, fontsize=12, fontweight="bold", color=TEXT_COLOR, va="center")

    ax_top = fig.add_axes([0.07, 0.48, 0.86, 0.29])
    ax_top.axis("off")
    top_table = ax_top.table(
        cellText=top_rows,
        colLabels=["Field", "Value"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    _style_table(top_table)

    ax_bottom_title = fig.add_axes([0.07, 0.40, 0.86, 0.05])
    ax_bottom_title.axis("off")
    ax_bottom_title.text(0.0, 0.5, bottom_title, fontsize=12, fontweight="bold", color=TEXT_COLOR, va="center")

    ax_bottom = fig.add_axes([0.07, 0.10, 0.86, 0.28])
    ax_bottom.axis("off")
    bottom_table = ax_bottom.table(
        cellText=bottom_rows,
        colLabels=["Field", "Value"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    _style_table(bottom_table)

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _render_plot_pages(
    pdf,
    title: str,
    entries: list[tuple[str, Path, tuple[str, ...], tuple[str, ...], str, str, bool, bool]],
    *,
    layout: str = "vertical",
    items_per_page: int = 2,
) -> None:
    import matplotlib.pyplot as plt

    if not entries:
        return
    chunks = _chunked(entries, items_per_page)
    for idx, chunk in enumerate(chunks, start=1):
        if layout == "grid":
            ncols = 2 if len(chunk) > 1 else 1
            nrows = 1 if len(chunk) <= 2 else int(math.ceil(len(chunk) / ncols))
        else:
            ncols = 1
            nrows = len(chunk)
        fig, axes = plt.subplots(nrows, ncols, figsize=PAGE_SIZE)
        _add_brand_header(fig, title, page_note=(f"Page {idx}/{len(chunks)}" if len(chunks) > 1 else None))
        fig.subplots_adjust(top=0.84, left=0.10, right=0.95, bottom=0.08, hspace=0.38, wspace=0.25)
        flat_axes = list(axes.flatten()) if hasattr(axes, "flatten") else [axes]
        for ax in flat_axes:
            ax.axis("off")
        for ax, (label, csv_path, x_opts, y_opts, x_title, y_title, log_x, log_y) in zip(flat_axes, chunk):
            parsed = _csv_numeric_columns(csv_path, x_opts, y_opts)
            if parsed is None:
                ax.axis("off")
                ax.text(0.5, 0.5, f"Not available\n{label}", ha="center", va="center", color=MUTED_COLOR)
                continue
            xs, ys, _, _ = parsed
            ax.axis("on")
            ax.plot(xs, ys, linewidth=1.6, color=PLOT_COLOR)
            if log_x:
                ax.set_xscale("log")
            if log_y:
                ax.set_yscale("log")
            ax.set_title(label, fontsize=11, fontweight="bold", color=TEXT_COLOR)
            ax.set_xlabel(x_title, fontsize=9)
            ax.set_ylabel(y_title, fontsize=9)
            ax.tick_params(labelsize=8)
            ax.grid(True, which="both", linestyle="--", linewidth=0.5, color=LINE_COLOR)
            for spine in ax.spines.values():
                spine.set_color(LINE_COLOR)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def _render_image_pages(
    pdf,
    title: str,
    entries: list[tuple[str, Path]],
    *,
    layout: str = "vertical",
    items_per_page: int = 2,
) -> None:
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    if not entries:
        return
    chunks = _chunked(entries, items_per_page)
    for idx, chunk in enumerate(chunks, start=1):
        if layout == "grid":
            ncols = 2 if len(chunk) > 1 else 1
            nrows = 1 if len(chunk) <= 2 else int(math.ceil(len(chunk) / ncols))
        else:
            ncols = 1
            nrows = len(chunk)
        fig, axes = plt.subplots(nrows, ncols, figsize=PAGE_SIZE)
        _add_brand_header(fig, title, page_note=(f"Page {idx}/{len(chunks)}" if len(chunks) > 1 else None))
        fig.subplots_adjust(top=0.84, left=0.08, right=0.95, bottom=0.08, hspace=0.30, wspace=0.20)
        flat_axes = list(axes.flatten()) if hasattr(axes, "flatten") else [axes]
        for ax in flat_axes:
            ax.axis("off")
        for ax, (label, path) in zip(flat_axes, chunk):
            try:
                image = mpimg.imread(path)
                ax.imshow(image)
                ax.set_title(label, fontsize=11, fontweight="bold", color=TEXT_COLOR)
                ax.axis("off")
            except Exception:
                ax.axis("off")
                ax.text(0.5, 0.5, f"Not available\n{label}", ha="center", va="center", color=MUTED_COLOR)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def export_ot_item_pdf(report_path: Path | str, summary: dict[str, Any]) -> Path:
    try:
        from matplotlib.backends.backend_pdf import PdfPages
    except Exception as e:
        raise RuntimeError("matplotlib with PdfPages is required for OT PDF export.") from e

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts = summary.get("artifacts") or {}
    image_entries = [
        entry
        for entry in (
            _build_image_entry("Quality control image", artifacts.get("qc_png")),
            _build_image_entry("Histogram X", artifacts.get("hist_x_png")),
            _build_image_entry("Histogram Y", artifacts.get("hist_y_png")),
            _build_image_entry("Histogram R", artifacts.get("hist_r_png")),
        )
        if entry is not None
    ]

    trajectory_entries = [
        entry
        for entry in (
            _build_plot_entry("Trajectory", artifacts.get("trajectory_csv"), ("x_corr_um", "x_corr_px", "x_px"), ("y_corr_um", "y_corr_px", "y_px"), "X position", "Y position", False, False),
            _build_plot_entry("MSD", artifacts.get("msd_csv"), ("tau_s",), ("msd_r_um2", "msd_r_px2"), "Tau [s]", "MSD", True, True),
        )
        if entry is not None
    ]

    psd_entries = [
        entry
        for entry in (
            _build_plot_entry("PSD X", artifacts.get("psd_x_csv"), ("f_hz",), ("psd_um2_per_hz", "psd_px2_per_hz"), "Frequency [Hz]", "PSD", True, True),
            _build_plot_entry("PSD Y", artifacts.get("psd_y_csv"), ("f_hz",), ("psd_um2_per_hz", "psd_px2_per_hz"), "Frequency [Hz]", "PSD", True, True),
        )
        if entry is not None
    ]

    hist_curve_entries = [
        entry
        for entry in (
            _build_plot_entry("Histogram X curve", artifacts.get("hist_x_csv"), ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
            _build_plot_entry("Histogram Y curve", artifacts.get("hist_y_csv"), ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
            _build_plot_entry("Histogram R curve", artifacts.get("hist_r_csv"), ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
        )
        if entry is not None
    ]

    with PdfPages(report_path) as pdf:
        _render_cover_page(
            pdf,
            title=f"Item Report: {summary.get('item_id')}",
            subtitle=f"{REPORT_NAME} | Item-level summary",
            left_rows=_identity_rows(summary),
            right_rows=_key_result_rows(summary),
        )
        _render_dual_table_page(
            pdf,
            "Item Conditions And Quality Control",
            "Acquisition and analysis conditions",
            _conditions_rows(summary),
            "Quality control and report notes",
            _qc_rows(summary),
        )
        if image_entries:
            _render_image_pages(pdf, "Quality Control And Histogram Images", image_entries, layout="vertical", items_per_page=2)
        if trajectory_entries:
            _render_plot_pages(pdf, "Trajectory And MSD", trajectory_entries, layout="vertical", items_per_page=2)
        if psd_entries:
            _render_plot_pages(pdf, "Power Spectral Density", psd_entries, layout="vertical", items_per_page=2)
        if hist_curve_entries:
            _render_plot_pages(pdf, "Histogram Curves", hist_curve_entries, layout="vertical", items_per_page=2)
        artifact_rows = _existing_artifact_rows(summary)
        if artifact_rows:
            _render_paginated_table(pdf, "Artifact Appendix", ["Artifact", "Path"], artifact_rows, subtitle="Relevant output files stored for this item", rows_per_page=14)
    return report_path


def export_ot_batch_pdf(report_path: Path | str, batch_summary: dict[str, Any]) -> Path:
    try:
        from matplotlib.backends.backend_pdf import PdfPages
    except Exception as e:
        raise RuntimeError("matplotlib with PdfPages is required for OT PDF export.") from e

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    items = list(batch_summary.get("items") or [])
    successes = [item for item in items if str(item.get("status")).lower() == "success"]
    failures = [item for item in items if str(item.get("status")).lower() != "success"]

    with PdfPages(report_path) as pdf:
        _render_cover_page(
            pdf,
            title=f"Batch Report: {batch_summary.get('batch_id') or 'OT batch'}",
            subtitle=f"{REPORT_NAME} | Batch comparison summary",
            left_rows=_batch_overview_rows(batch_summary, items, successes, failures),
            right_rows=[
                ["Successful items", str(len(successes))],
                ["Failed or stopped", str(len(failures))],
                ["Report generated", datetime.now().isoformat(timespec="seconds")],
                ["Comparison focus", "Viscosity, diffusion, stiffness, corner frequency"],
                ["Branding", "BARAKUDA text header (logo-ready placeholder)"],
            ],
        )

        summary_rows = _batch_summary_rows(items)
        if summary_rows:
            _render_paginated_table(
                pdf,
                "Batch Summary Table",
                ["Item", "Status", "Mean viscosity", "Diffusion coefficient", "Trap stiffness X", "Trap stiffness Y"],
                summary_rows,
                subtitle="One row per item for rapid cross-batch inspection",
                rows_per_page=12,
            )

        metric_rows = _batch_metric_rows(successes)
        if metric_rows:
            _render_paginated_table(
                pdf,
                "Metric Comparison",
                ["Item", "Mean viscosity", "Diffusion coefficient", "Trap stiffness X", "Trap stiffness Y", "Corner frequency X", "Corner frequency Y"],
                metric_rows,
                subtitle="Successful items compared by the main physical outputs",
                rows_per_page=12,
            )

        def _collect_image_entries(key: str, label_prefix: str) -> list[tuple[str, Path]]:
            collected: list[tuple[str, Path]] = []
            for item in successes:
                entry = _build_image_entry(f"{label_prefix}: {item.get('item_id')}", (item.get("artifacts") or {}).get(key))
                if entry is not None:
                    collected.append(entry)
            return collected

        def _collect_plot_entries(key: str, label_prefix: str, x_opts: tuple[str, ...], y_opts: tuple[str, ...], x_title: str, y_title: str, log_x: bool, log_y: bool) -> list[tuple[str, Path, tuple[str, ...], tuple[str, ...], str, str, bool, bool]]:
            collected: list[tuple[str, Path, tuple[str, ...], tuple[str, ...], str, str, bool, bool]] = []
            for item in successes:
                entry = _build_plot_entry(
                    f"{label_prefix}: {item.get('item_id')}",
                    (item.get("artifacts") or {}).get(key),
                    x_opts,
                    y_opts,
                    x_title,
                    y_title,
                    log_x,
                    log_y,
                )
                if entry is not None:
                    collected.append(entry)
            return collected

        for title, key in (
            ("Grouped QC Images", "qc_png"),
            ("Grouped Histogram X Images", "hist_x_png"),
            ("Grouped Histogram Y Images", "hist_y_png"),
            ("Grouped Histogram R Images", "hist_r_png"),
        ):
            image_entries = _collect_image_entries(key, title.replace("Grouped ", "").replace(" Images", ""))
            if image_entries:
                _render_image_pages(pdf, title, image_entries, layout="grid", items_per_page=2)

        for title, key, x_opts, y_opts, x_title, y_title, log_x, log_y in (
            ("PSD X Comparison", "psd_x_csv", ("f_hz",), ("psd_um2_per_hz", "psd_px2_per_hz"), "Frequency [Hz]", "PSD", True, True),
            ("PSD Y Comparison", "psd_y_csv", ("f_hz",), ("psd_um2_per_hz", "psd_px2_per_hz"), "Frequency [Hz]", "PSD", True, True),
            ("Histogram X Curves", "hist_x_csv", ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
            ("Histogram Y Curves", "hist_y_csv", ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
            ("Histogram R Curves", "hist_r_csv", ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
        ):
            plot_entries = _collect_plot_entries(key, title, x_opts, y_opts, x_title, y_title, log_x, log_y)
            if plot_entries:
                _render_plot_pages(pdf, title, plot_entries, layout="grid", items_per_page=2)

        detail_rows = [
            [
                _wrap(item.get("item_id"), 18),
                _fmt_status(item.get("status")),
                _fmt_measure((item.get("metrics") or {}).get("eta_mean_pa_s"), "Pa*s"),
                _fmt_measure((item.get("metrics") or {}).get("D_m2_s"), "m^2/s"),
                _fmt_measure((item.get("diagnostics") or {}).get("fc_x_hz"), "Hz"),
                _wrap(item.get("error"), 24),
            ]
            for item in items
        ]
        if detail_rows:
            _render_paginated_table(
                pdf,
                "Item Detail Appendix",
                ["Item", "Status", "Mean viscosity", "Diffusion coefficient", "Corner frequency X", "Notes"],
                detail_rows,
                subtitle="Compact item-by-item appendix for quick reference",
                rows_per_page=12,
            )

        if failures:
            fail_rows = [[_wrap(item.get("item_id"), 20), _fmt_status(item.get("status")), _wrap(item.get("error"), 52)] for item in failures]
            _render_paginated_table(
                pdf,
                "Failures And Non-success Items",
                ["Item", "Status", "Reason"],
                fail_rows,
                subtitle="Items without complete outputs are listed here for traceability",
                rows_per_page=14,
            )

    return report_path
