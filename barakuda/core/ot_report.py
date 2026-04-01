from __future__ import annotations

import csv
import json
import math
import textwrap
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


PAGE_SIZE = (8.27, 11.69)  # A4 in inches
PAGE_MARGIN_LEFT = 0.08
PAGE_MARGIN_RIGHT = 0.08
PAGE_MARGIN_TOP = 0.12
PAGE_MARGIN_BOTTOM = 0.06

BRAND_NAME = "BARAKUDA"
REPORT_NAME = "Optical Tweezers Analysis Report"
BRAND_COLOR = "#0F3D5E"
ACCENT_COLOR = "#1F6AA5"
LIGHT_BG = "#F4F7FA"
PANEL_BG = "#F8FBFD"
CARD_BG = "#FFFFFF"
TEXT_COLOR = "#162534"
MUTED_COLOR = "#586574"
LINE_COLOR = "#CAD5E0"
PLOT_COLOR = "#1F6AA5"

FONT_FAMILY = "DejaVu Sans"
FONT_SIZE_NORMAL = 10
FONT_SIZE_SMALL = 9
FONT_SIZE_TITLE = 14
FONT_SIZE_HEADER = 12


def _branding_asset_path(file_name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "branding" / "barakuda" / file_name


@lru_cache(maxsize=1)
def _load_header_logo() -> Any | None:
    logo_path = _branding_asset_path("logo_dark.png")
    if not logo_path.is_file():
        return None
    try:
        import matplotlib.image as mpimg

        return mpimg.imread(logo_path)
    except Exception:
        return None


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
        # Use scientific notation with proper formatting for very small/large values
        if abs(value) < 0.01 or abs(value) >= 1000:
            return _fmt_scientific_text(value, sig_figs=3)
        return f"{value:.6g}"
    return str(value)


def _fmt_unit(unit: str) -> str:
    """Format unit string with proper Unicode symbols."""
    return (
        unit
        .replace("um", "µm")
        .replace("^2", "²")
        .replace("*", "·")
    )


def _fmt_measure(value: Any, unit: str = "") -> str:
    text = _fmt_value(value)
    if text == "n/a" or not unit:
        return text
    return f"{text} {_fmt_unit(unit)}"


def _fmt_scientific_text(value: float, sig_figs: int = 3) -> str:
    """Format number as 'X.XX x 10^n' with Unicode superscript for plain text contexts."""
    try:
        if value == 0 or not math.isfinite(value):
            return "0" if value == 0 else "n/a"
        abs_val = abs(value)
        if abs_val >= 0.01 and abs_val < 1000:
            return f"{value:.{sig_figs}g}"
        
        exp = int(math.floor(math.log10(abs_val)))
        mantissa = value / (10 ** exp)
        # Superscript digits for plain text
        sup = str(exp).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))
        return f"{mantissa:.{sig_figs-1}f} x 10{sup}"
    except Exception:
        return f"{value:.{sig_figs}g}"


def _fmt_scientific_mathtext(value: float, sig_figs: int = 3) -> str:
    """Format number as 'X.XX x 10^n' with proper superscript using mathtext for matplotlib."""
    try:
        if value == 0 or not math.isfinite(value):
            return "0" if value == 0 else "n/a"
        abs_val = abs(value)
        if abs_val >= 0.01 and abs_val < 1000:
            return f"{value:.{sig_figs}g}"
        
        exp = int(math.floor(math.log10(abs_val)))
        mantissa = value / (10 ** exp)
        # Mathtext format for rendering in matplotlib
        return f"${mantissa:.{sig_figs-1}f} \\times 10^{{{exp}}}$"
    except Exception:
        return f"{value:.{sig_figs}g}"


def _fmt_measure_with_uncertainty(value: Any, uncertainty: Any, unit: str = "") -> str:
    """Format a measurement value with uncertainty, rounded according to uncertainty magnitude."""
    if value is None:
        return "n/a"
    try:
        val = float(value)
        if not math.isfinite(val):
            return "n/a"
    except Exception:
        return "n/a"

    unc = None
    try:
        unc = float(uncertainty) if uncertainty is not None else None
        if unc is not None and (not math.isfinite(unc) or unc <= 0):
            unc = None
    except Exception:
        unc = None

    if unc is None or unc == 0:
        # No uncertainty - use scientific notation for very small/large values
        abs_val = abs(val)
        if abs_val > 0 and (abs_val < 0.01 or abs_val >= 1000):
            formatted = _fmt_scientific_text(val, sig_figs=3)
            if unit:
                return f"{formatted} {_fmt_unit(unit)}"
            return formatted
        return _fmt_measure(val, unit)

    # Find decimal precision based on uncertainty
    # Round uncertainty to 1-2 significant figures
    try:
        unc_exp = int(math.floor(math.log10(abs(unc))))
        precision = max(0, min(10, -unc_exp + 1))  # Cap precision at 10 decimals
    except (ValueError, OverflowError):
        precision = 2
    
    # Round both values to the same precision
    val_rounded = round(val, precision)
    unc_rounded = round(unc, precision)
    
    # Check if we need scientific notation (very small or large values)
    abs_val_rounded = abs(val_rounded)
    if abs_val_rounded > 0 and (abs_val_rounded < 0.01 or abs_val_rounded >= 1000):
        try:
            # Scientific notation with uncertainty
            val_exp = int(math.floor(math.log10(abs_val_rounded)))
            val_mantissa = val_rounded / (10 ** val_exp)
            unc_mantissa = unc_rounded / (10 ** val_exp)
            
            # Format mantissas with appropriate precision
            mant_precision = max(1, min(6, precision + val_exp))
            val_str = f"{val_mantissa:.{mant_precision}f}"
            unc_str = f"{unc_mantissa:.{mant_precision}f}"
            
            # Unicode superscript for exponent
            sup = str(val_exp).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))
            
            if unit:
                return f"({val_str} +/- {unc_str}) x 10{sup} {_fmt_unit(unit)}"
            return f"({val_str} +/- {unc_str}) x 10{sup}"
        except (ValueError, OverflowError):
            pass
    
    # Normal range - format with appropriate decimal places
    val_str = f"{val_rounded:.{precision}f}"
    unc_str = f"{unc_rounded:.{precision}f}"

    if unit:
        return f"{val_str} +/- {unc_str} {_fmt_unit(unit)}"
    return f"{val_str} +/- {unc_str}"


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


def _is_drag_report(summary: dict[str, Any]) -> bool:
    metrics = summary.get("metrics") or {}
    diagnostics = summary.get("diagnostics") or {}
    source_kind = str(diagnostics.get("report_source_kind") or "").strip().lower()
    analysis_type = str(diagnostics.get("analysis_type") or "").strip().lower()
    mode = str(metrics.get("mode") or "").strip().lower()
    return source_kind == "drag_summary" or analysis_type == "drag" or mode in {"drag", "dragging"}


def _display_path(path_value: Any, width: int = 72) -> str:
    if not path_value:
        return "n/a"
    return textwrap.fill(str(path_value), width=width, break_long_words=False, break_on_hyphens=False)


def _split_display_path(path_value: Any) -> tuple[str, list[str]]:
    text = str(path_value or "").strip().replace("\\", "/")
    if not text:
        return "", []

    prefix = ""
    body = text
    if text.startswith("//"):
        prefix = "//"
        body = text[2:]
    elif len(text) >= 3 and text[1] == ":" and text[2] == "/":
        prefix = text[:3]
        body = text[3:]
    elif len(text) >= 2 and text[1] == ":":
        prefix = text[:2] + "/"
        body = text[2:].lstrip("/")
    elif text.startswith("/"):
        prefix = "/"
        body = text[1:]

    parts = [part for part in body.split("/") if part]
    return prefix, parts


def _join_display_path(prefix: str, parts: list[str]) -> str:
    if prefix in ("//", "/"):
        return prefix + "/".join(parts)
    if prefix.endswith("/"):
        return prefix + "/".join(parts)
    if prefix:
        return prefix + ("/" + "/".join(parts) if parts else "")
    return "/".join(parts)


def _short_path(path_value: Any, *, anchor: Any | None = None, keep_parts: int = 4) -> str:
    text = str(path_value or "").strip()
    if not text:
        return "n/a"

    try:
        path = Path(text)
        if anchor:
            anchor_path = Path(str(anchor))
            try:
                return str(path.relative_to(anchor_path)).replace("\\", "/")
            except Exception:
                pass
    except Exception:
        pass

    prefix, parts = _split_display_path(text)
    if not parts:
        return prefix or "n/a"
    if len(parts) <= keep_parts:
        return _join_display_path(prefix, parts)
    return ".../" + "/".join(parts[-keep_parts:])


def _wrap_path_segments(path_value: Any, width: int = 88) -> list[str]:
    prefix, parts = _split_display_path(path_value)
    if not parts and not prefix:
        return ["n/a"]

    lines: list[str] = []
    current = prefix if prefix else ""

    def _flush() -> None:
        nonlocal current
        if current:
            lines.append(current)
            current = ""

    for idx, part in enumerate(parts):
        segment = part
        if idx < len(parts) - 1:
            segment += "/"
        candidate = current + segment
        if current and len(candidate) > width:
            _flush()
            candidate = segment
        if len(candidate) <= width:
            current = candidate
            continue
        wrapped_segment = textwrap.wrap(
            segment,
            width=width,
            break_long_words=True,
            break_on_hyphens=True,
        ) or [segment]
        if current:
            _flush()
        for wrapped_idx, chunk in enumerate(wrapped_segment):
            if wrapped_idx < len(wrapped_segment) - 1:
                lines.append(chunk)
            else:
                current = chunk

    _flush()
    return lines or ["n/a"]


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
        "camera_dropped_frames": "Camera dropped frames",
        "tracking_lost_frames": "Tracking lost frames",
        "warning_count": "Warnings",
        "drag_force_n": "Drag force",
        "offset_um": "Drag offset",
        "kappa_drag_pn_per_um": "Drag stiffness",
        "ratio_drag_over_brownian": "Drag/Brownian stiffness ratio",
        "report_source_kind": "Report source kind",
        "report_source_path": "Report source path",
        "error": "Failure reason",
        "warnings": "Warnings detail",
        "qc_png": "QC image",
        "hist_x_png": "Histogram X image",
        "hist_y_png": "Histogram Y image",
        "hist_r_png": "Histogram R image",
        "tracking_preview_png": "Tracking preview image",
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
                display = _short_path(path, keep_parts=5)
        else:
            display = _short_path(path, keep_parts=5)
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
    run_protocol_json = _load_json(
        _first_existing(
            dir_audit / "run_protocol.json" if dir_audit else None,
            run_dir / "run_protocol.json" if run_dir else None,
        )
    )
    post_json = _load_json(dir_audit / f"{base_name}_postprocess.json" if dir_audit else None)
    calibration_json = _load_json(dir_audit / f"{base_name}_calibration.json" if dir_audit else None)
    drag_summary_json = _load_json(dir_audit / f"{base_name}_drag_summary.json" if dir_audit else None)
    drag_alignment_json = _load_json(
        dir_audit / f"{base_name}_alignment_diagnostics.json" if dir_audit else None
    )
    compare_json = _load_json(dir_audit / f"{base_name}_compare.json" if dir_audit else None)
    drag_json = _load_json(dir_audit / f"{base_name}_drag.json" if dir_audit else None)
    cal_csv = _read_metric_csv(dir_csv / f"{base_name}_calibration.csv" if dir_csv else None)
    derived_mean = _read_first_row(dir_csv / f"{base_name}_derived.csv" if dir_csv else None)

    metrics: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    warnings: list[str] = []

    cfg = ((run_json or {}).get("config") or {})
    provenance_cfg = (run_protocol_json or {}).get("provenance") or (run_json or {}).get("provenance") or {}
    analysis_cfg = (run_protocol_json or {}).get("analysis") or (run_json or {}).get("analysis") or {}
    summary_refs_cfg = analysis_cfg.get("summary_references") or {}
    tracking_cfg = cfg.get("tracking") or {}
    timing_cfg = tracking_cfg.get("timing") or {}
    post_cfg = cfg.get("postprocess") or {}
    cal_cfg = cfg.get("calibration") or {}
    calibration_bead_diameter_um = _parse_float((calibration_json or {}).get("bead_diameter_um"))
    calibration_bead_radius_um = _parse_float((calibration_json or {}).get("bead_radius_um"))

    metrics["fps"] = _parse_float(tracking_cfg.get("fps"))
    metrics["um_per_px"] = _parse_float(cal_cfg.get("um_per_px"))
    metrics["scale_source"] = cal_cfg.get("source")
    metrics["temperature_c"] = _parse_float(post_cfg.get("temperature_c"))
    metrics["bead_diameter_um"] = _parse_float(post_cfg.get("bead_diameter_um"))
    metrics["bead_source"] = post_cfg.get("bead_source")
    diagnostics["bead_fallback_used"] = bool(post_cfg.get("bead_fallback_used", False))
    bead_source_warning = post_cfg.get("bead_source_warning")
    if bead_source_warning:
        warnings.append(str(bead_source_warning))
    if metrics["bead_diameter_um"] is None:
        metrics["bead_diameter_um"] = calibration_bead_diameter_um
    metrics["bead_radius_um"] = calibration_bead_radius_um
    if metrics["bead_radius_um"] is None:
        metrics["bead_radius_um"] = _parse_float(post_cfg.get("bead_radius_um"))
    if metrics["bead_radius_um"] is None and metrics["bead_diameter_um"] is not None:
        metrics["bead_radius_um"] = float(metrics["bead_diameter_um"]) * 0.5
    metrics["mode"] = str(post_cfg.get("physics_mode") or derived_mean.get("mode") or "")
    metrics["drag_axis"] = str(post_cfg.get("drag_axis") or "")
    metrics["stage_speed_um_s"] = _parse_float(post_cfg.get("stage_speed_um_s"))
    diagnostics["elapsed_time_s"] = _parse_float(timing_cfg.get("elapsed_time_s"))
    diagnostics["effective_fps"] = _parse_float(timing_cfg.get("effective_fps"))
    diagnostics["timing_source"] = timing_cfg.get("timing_source")
    diagnostics["timing_source_detail"] = timing_cfg.get("timing_source_detail")
    diagnostics["timestamp_validation_pass"] = timing_cfg.get("timestamp_validation_pass")
    diagnostics["timestamp_validation_message"] = timing_cfg.get("timestamp_validation_message")
    diagnostics["current_drag_input_path"] = provenance_cfg.get("current_drag_input_path")
    diagnostics["current_drag_item_root"] = provenance_cfg.get("current_drag_item_root")
    diagnostics["brownian_baseline_folder"] = provenance_cfg.get("brownian_baseline_folder")
    diagnostics["baseline_selection_mode"] = provenance_cfg.get("baseline_selection_mode")
    diagnostics["drag_preflight_status"] = provenance_cfg.get("drag_preflight_status")
    diagnostics["drag_preflight_message"] = provenance_cfg.get("drag_preflight_message")
    diagnostics["current_drag_output_root"] = provenance_cfg.get("current_drag_output_root")
    diagnostics["current_drag_report_path"] = provenance_cfg.get("current_drag_report_path")
    diagnostics["current_drag_summary_json_path"] = provenance_cfg.get("current_drag_summary_json_path")
    diagnostics["current_drag_summary_csv_path"] = provenance_cfg.get("current_drag_summary_csv_path")
    diagnostics["current_drag_diagnostic_png_path"] = provenance_cfg.get("current_drag_diagnostic_png_path")
    diagnostics["current_drag_alignment_json_path"] = provenance_cfg.get("current_drag_alignment_json_path")
    diagnostics["current_drag_protocol_summary_json"] = summary_refs_cfg.get("summary_json")
    diagnostics["analysis_type"] = (
        analysis_cfg.get("analysis_type")
        or ((run_json or {}).get("analysis") or {}).get("analysis_type")
    )
    diagnostics["camera_dropped_frames"] = _parse_float(
        ((cfg.get("acquisition") or {}).get("camera_dropped_frames"))
    )
    if diagnostics["camera_dropped_frames"] is None and run_dir is not None:
        raw_dir = run_dir / "raw"
        for candidate in (
            raw_dir / "video_meta.json",
            raw_dir / f"{base_name}_meta.json",
        ):
            payload = _load_json(candidate)
            if payload:
                diagnostics["camera_dropped_frames"] = _parse_float(
                    payload.get("dropped_frames")
                )
                if diagnostics["camera_dropped_frames"] is not None:
                    break

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
        metrics["kappa_x_pn_per_um_se"] = _parse_float(kappa.get("kappa_x_pn_per_um_se"))
        metrics["kappa_y_pn_per_um_se"] = _parse_float(kappa.get("kappa_y_pn_per_um_se"))
        metrics["kappa_iso_ratio"] = _parse_float(kappa.get("kappa_iso_ratio"))
        metrics["eta_x_pa_s"] = _parse_float(viscosity.get("eta_x_pa_s"))
        metrics["eta_y_pa_s"] = _parse_float(viscosity.get("eta_y_pa_s"))
        metrics["eta_mean_pa_s"] = _parse_float(viscosity.get("eta_mean_pa_s"))
        metrics["eta_mean_pa_s_se"] = _parse_float(viscosity.get("eta_mean_pa_s_se"))
        metrics["D_m2_s"] = _parse_float(diffusion.get("D_m2_s"))
        metrics["D_m2_s_se"] = _parse_float(diffusion.get("D_m2_s_se"))
        diagnostics["fc_x_hz"] = _parse_float(diag.get("fc_x_hz"))
        diagnostics["fc_y_hz"] = _parse_float(diag.get("fc_y_hz"))
        diagnostics["fc_x_hz_se"] = _parse_float(diag.get("fc_x_hz_se"))
        diagnostics["fc_y_hz_se"] = _parse_float(diag.get("fc_y_hz_se"))
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

    if drag_summary_json:
        diagnostics["report_source_kind"] = drag_summary_json.get("report_source_kind") or "drag_summary"
        diagnostics["report_source_path"] = drag_summary_json.get("report_source_path") or (
            str((dir_audit / f"{base_name}_drag_summary.json")) if dir_audit else None
        )
        diagnostics["drag_force_n"] = _parse_float(drag_summary_json.get("drag_force_n"))
        diagnostics["offset_um"] = _parse_float(
            drag_summary_json.get("abs_offset_um")
            if drag_summary_json.get("abs_offset_um") is not None
            else drag_summary_json.get("offset_um_stage_signed")
        )
        metrics["kappa_drag_pn_per_um"] = _parse_float(drag_summary_json.get("kappa_pn_per_um"))
        diagnostics["drag_axis"] = drag_summary_json.get("axis")
        diagnostics["drag_analysis_axis"] = drag_summary_json.get("analysis_axis")
        diagnostics["drag_stage_axis"] = drag_summary_json.get("stage_axis")
        diagnostics["drag_protocol_type"] = drag_summary_json.get("protocol_type")
        diagnostics["selected_calibration_path"] = drag_summary_json.get("selected_calibration_path")
        diagnostics["selected_trajectory_path"] = drag_summary_json.get("selected_trajectory_path")
        diagnostics["selected_timestamps_path"] = drag_summary_json.get("selected_timestamps_path")
        diagnostics["selected_stage_meta_path"] = drag_summary_json.get("selected_stage_meta_path")
        diagnostics["selected_stage_trace_path"] = drag_summary_json.get("selected_stage_trace_path")
        diagnostics["timing_source"] = drag_summary_json.get("timing_source") or diagnostics.get("timing_source")
        diagnostics["motion_kinematics_source"] = drag_summary_json.get("motion_kinematics_source")
        diagnostics["kappa_source"] = drag_summary_json.get("kappa_source")
        diagnostics["um_per_px_source"] = drag_summary_json.get("um_per_px_source")
        diagnostics["baseline_selection_mode"] = drag_summary_json.get("baseline_selection_mode") or diagnostics.get(
            "baseline_selection_mode"
        )
        diagnostics["drag_preflight_status"] = drag_summary_json.get("drag_preflight_status") or diagnostics.get(
            "drag_preflight_status"
        )
        diagnostics["drag_preflight_message"] = drag_summary_json.get("drag_preflight_message") or diagnostics.get(
            "drag_preflight_message"
        )
        diagnostics["alignment_status"] = drag_summary_json.get("alignment_status")
        diagnostics["alignment_message"] = drag_summary_json.get("alignment_message")
        diagnostics["alignment_offset_s"] = _parse_float(drag_summary_json.get("alignment_offset_s"))
        diagnostics["motion_start_stage_s"] = _parse_float(drag_summary_json.get("motion_start_stage_s"))
        diagnostics["motion_stop_stage_s"] = _parse_float(drag_summary_json.get("motion_stop_stage_s"))
        diagnostics["motion_start_video_s_detected"] = _parse_float(
            drag_summary_json.get("motion_start_video_s_detected")
        )
        diagnostics["motion_stop_video_s_stage_aligned"] = _parse_float(
            drag_summary_json.get("motion_stop_video_s_stage_aligned")
        )
        diagnostics["baseline_start_s"] = _parse_float(drag_summary_json.get("baseline_start_s"))
        diagnostics["baseline_end_s"] = _parse_float(drag_summary_json.get("baseline_end_s"))
        diagnostics["steady_start_s"] = _parse_float(drag_summary_json.get("steady_start_s"))
        diagnostics["steady_end_s"] = _parse_float(drag_summary_json.get("steady_end_s"))
        diagnostics["actual_motion_duration_s"] = _parse_float(drag_summary_json.get("actual_motion_duration_s"))
        diagnostics["actual_speed_um_s"] = _parse_float(drag_summary_json.get("actual_speed_um_s"))
        diagnostics["eta_pa_s"] = _parse_float(drag_summary_json.get("eta_pa_s"))
        diagnostics["analysis_status"] = drag_summary_json.get("analysis_status")
        diagnostics["physics_status"] = drag_summary_json.get("physics_status")
        diagnostics["drag_physics_confidence"] = drag_summary_json.get("drag_physics_confidence")
        diagnostics["drag_physics_warning"] = drag_summary_json.get("drag_physics_warning")
        diagnostics["baseline_robustness_flag"] = drag_summary_json.get("baseline_robustness_flag")
        diagnostics["onset_robustness_flag"] = drag_summary_json.get("onset_robustness_flag")
        diagnostics["kinematics_robustness_flag"] = drag_summary_json.get("kinematics_robustness_flag")
        diagnostics["offset_current_windows_um"] = _parse_float(drag_summary_json.get("offset_current_windows_um"))
        diagnostics["offset_alt_baseline_um"] = _parse_float(drag_summary_json.get("offset_alt_baseline_um"))
        diagnostics["eta_current_windows"] = _parse_float(drag_summary_json.get("eta_current_windows"))
        diagnostics["eta_alt_baseline"] = _parse_float(drag_summary_json.get("eta_alt_baseline"))
        diagnostics["baseline_reference_median_px"] = _parse_float(drag_summary_json.get("baseline_reference_median_px"))
        diagnostics["baseline_reference_window_start_s"] = _parse_float(
            drag_summary_json.get("baseline_reference_window_start_s")
        )
        diagnostics["baseline_reference_window_end_s"] = _parse_float(
            drag_summary_json.get("baseline_reference_window_end_s")
        )
        diagnostics["baseline_median_delta_px"] = _parse_float(drag_summary_json.get("baseline_median_delta_px"))
        diagnostics["baseline_median_delta_um"] = _parse_float(drag_summary_json.get("baseline_median_delta_um"))
        diagnostics["stage_speed_from_trace_um_s"] = _parse_float(drag_summary_json.get("stage_speed_from_trace_um_s"))
        diagnostics["stage_speed_relative_diff"] = _parse_float(drag_summary_json.get("stage_speed_relative_diff"))
        diagnostics["stage_speed_consistent"] = drag_summary_json.get("stage_speed_consistent")
        metrics["mode"] = "DRAG"
        diagnostics["timestamp_validation_pass"] = drag_summary_json.get(
            "timestamp_validation_pass",
            diagnostics.get("timestamp_validation_pass"),
        )
        diagnostics["timestamp_validation_message"] = drag_summary_json.get(
            "timestamp_validation_message",
            diagnostics.get("timestamp_validation_message"),
        )
        qc_map = {
            "baseline_window_ok": drag_summary_json.get("qc_baseline_window_ok"),
            "steady_window_ok": drag_summary_json.get("qc_steady_window_ok"),
            "sufficient_steady_duration": drag_summary_json.get("qc_sufficient_steady_duration"),
            "alignment_confident": drag_summary_json.get("qc_alignment_confident"),
            "stage_speed_available": drag_summary_json.get("qc_stage_speed_available"),
            "physics_ready": drag_summary_json.get("qc_physics_ready"),
            "offset_detected": drag_summary_json.get("qc_offset_detected"),
        }
        diagnostics["drag_qc_flags"] = qc_map
        for warn in drag_summary_json.get("warnings") or []:
            warnings.append(str(warn))
    if diagnostics.get("report_source_kind") is None and provenance_cfg.get("report_source_kind"):
        diagnostics["report_source_kind"] = provenance_cfg.get("report_source_kind")
    if diagnostics.get("report_source_path") is None and provenance_cfg.get("report_source_path"):
        diagnostics["report_source_path"] = provenance_cfg.get("report_source_path")
    for key in (
        "selected_calibration_path",
        "selected_trajectory_path",
        "selected_timestamps_path",
        "selected_stage_meta_path",
        "selected_stage_trace_path",
        "current_drag_input_path",
        "brownian_baseline_folder",
        "current_drag_output_root",
        "current_drag_report_path",
    ):
        if diagnostics.get(key) is None and provenance_cfg.get(key):
            diagnostics[key] = provenance_cfg.get(key)
    if diagnostics.get("timing_source") is None and provenance_cfg.get("timing_source"):
        diagnostics["timing_source"] = provenance_cfg.get("timing_source")
    if drag_alignment_json:
        diagnostics["alignment_baseline_end_s"] = _parse_float(drag_alignment_json.get("baseline_end_s"))
        diagnostics["alignment_baseline_median"] = _parse_float(drag_alignment_json.get("baseline_median"))
        diagnostics["alignment_baseline_mad"] = _parse_float(drag_alignment_json.get("baseline_mad"))
        diagnostics["alignment_baseline_sigma"] = _parse_float(drag_alignment_json.get("baseline_sigma"))
        diagnostics["alignment_onset_threshold_sigma"] = _parse_float(
            drag_alignment_json.get("onset_threshold_sigma")
        )
        diagnostics["alignment_onset_threshold_abs"] = _parse_float(
            drag_alignment_json.get("onset_threshold_abs")
        )
        diagnostics["alignment_onset_min_hold_s"] = _parse_float(drag_alignment_json.get("onset_min_hold_s"))
        diagnostics["alignment_n_baseline_samples"] = _parse_float(
            drag_alignment_json.get("n_baseline_samples")
        )
        diagnostics["alignment_n_total_samples"] = _parse_float(drag_alignment_json.get("n_total_samples"))
        diagnostics["alignment_n_frames_outside_baseline"] = _parse_float(
            drag_alignment_json.get("n_frames_outside_baseline")
        )
        diagnostics["alignment_failure_reason"] = drag_alignment_json.get("failure_reason")
        diagnostics["alignment_message"] = (
            diagnostics.get("alignment_message") or drag_alignment_json.get("message")
        )
        diagnostics["onset_relaxed_used"] = drag_alignment_json.get("onset_relaxed_used")
        diagnostics["onset_competing_durable_candidates"] = _parse_float(
            drag_alignment_json.get("onset_competing_durable_candidates")
        )
        diagnostics["onset_ambiguity_score"] = _parse_float(drag_alignment_json.get("onset_ambiguity_score"))
        diagnostics["onset_confidence_class"] = drag_alignment_json.get("onset_confidence_class")
    if compare_json and metrics.get("kappa_drag_pn_per_um") is None:
        delta = compare_json.get("delta") or {}
        dragging = compare_json.get("dragging") or {}
        metrics["kappa_drag_pn_per_um"] = _parse_float(dragging.get("kappa_pn_per_um"))
        diagnostics["ratio_drag_over_brownian"] = _parse_float(delta.get("ratio_drag_over_brownian"))
        diagnostics["delta_n_per_m"] = _parse_float(delta.get("delta_n_per_m"))
    if drag_json and diagnostics.get("drag_force_n") is None:
        dragging = drag_json.get("dragging") or {}
        means_um = drag_json.get("means_um") or {}
        diagnostics["drag_force_n"] = _parse_float(dragging.get("drag_force_n"))
        diagnostics["offset_um"] = _parse_float(means_um.get("offset_um"))
    if diagnostics.get("report_source_kind") is None and (
        compare_json is not None or drag_json is not None
    ):
        diagnostics["report_source_kind"] = "legacy_drag_json"
        diagnostics["report_source_path"] = str((dir_audit / f"{base_name}_drag.json")) if dir_audit else None
        warnings.append("legacy drag source used")

    if post_json:
        pp_summary = post_json.get("summary") or {}
        qc = pp_summary.get("qc") or {}
        diagnostics["tracking_lost_frames"] = _parse_float(qc.get("lost_frames"))
        diagnostics["lost_fraction"] = _parse_float(qc.get("lost_fraction"))

    for warning in (post_json or {}).get("summary", {}).get("warnings", []):
        warnings.append(str(warning))
    diagnostics["warning_count"] = len(warnings)

    preview_grid_pngs: list[str] = []
    if run_dir is not None:
        for raw_dir in (run_dir.parent / "raw", run_dir / "raw"):
            if not raw_dir.exists():
                continue
            for i in range(1, 11):
                p = raw_dir / f"video_preview_{i:02d}.png"
                if p.is_file():
                    preview_grid_pngs.append(str(p))
            if preview_grid_pngs:
                break

    artifacts = {
        "analysis_dir": str(run_dir) if run_dir is not None else None,
        "audit_dir": str(dir_audit) if dir_audit is not None and dir_audit.exists() else None,
        "csv_dir": str(dir_csv) if dir_csv is not None and dir_csv.exists() else None,
        "results_dir": str(dir_results) if dir_results is not None and dir_results.exists() else None,
        "xlsx": str(dir_results / f"{base_name}_results.xlsx") if dir_results is not None else None,
        "results_csv": str(dir_csv / f"{base_name}_results.csv") if dir_csv is not None else None,
        "drag_summary_json": str(dir_audit / f"{base_name}_drag_summary.json") if dir_audit is not None else None,
        "alignment_diagnostics_json": str(dir_audit / f"{base_name}_alignment_diagnostics.json") if dir_audit is not None else None,
        "run_protocol_json": str(dir_audit / "run_protocol.json") if dir_audit is not None else None,
        "trajectory_csv": str(dir_csv / f"{base_name}_trajectory.csv") if dir_csv is not None else None,
        "drag_windows_csv": str(dir_csv / f"{base_name}_drag_windows.csv") if dir_csv is not None else None,
        "drag_trace_annotated_csv": str(dir_csv / f"{base_name}_drag_trace_annotated.csv") if dir_csv is not None else None,
        "current_drag_output_root": provenance_cfg.get("current_drag_output_root"),
        "current_drag_report_path": provenance_cfg.get("current_drag_report_path"),
        "current_drag_summary_json_path": provenance_cfg.get("current_drag_summary_json_path"),
        "current_drag_summary_csv_path": provenance_cfg.get("current_drag_summary_csv_path"),
        "current_drag_diagnostic_png_path": provenance_cfg.get("current_drag_diagnostic_png_path"),
        "drag_diagnostic_png": provenance_cfg.get("current_drag_diagnostic_png_path")
        or (str(dir_results / f"{base_name}_drag_diagnostic.png") if dir_results is not None else None),
        "current_drag_alignment_json_path": provenance_cfg.get("current_drag_alignment_json_path"),
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
        "tracking_preview_png": str(dir_results / f"{base_name}_tracking_preview.png") if dir_results is not None else None,
        "preview_grid_pngs": preview_grid_pngs,
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
    if _is_drag_report(summary):
        rows: list[tuple[str, str, Any, str, str]] = [
            ("Identity", "Item ID", summary.get("item_id"), "", "item_id"),
            ("Identity", "Status", _fmt_status(summary.get("status")), "", "status"),
            ("Identity", "Run ID", summary.get("run_id"), "", "run_id"),
            ("Identity", "Source input", summary.get("source_input_path"), "", "source_input_path"),
            ("Drag", "Analysis mode", "DRAG", "", "mode"),
            ("Drag", "Drag force", diagnostics.get("drag_force_n"), "N", "drag_force_n"),
            ("Drag", "Viscosity", diagnostics.get("eta_pa_s"), "Pa*s", "eta_pa_s"),
            ("Drag", "Drag stiffness", metrics.get("kappa_drag_pn_per_um"), "pN/um", "kappa_drag_pn_per_um"),
            ("Drag", "Actual speed", diagnostics.get("actual_speed_um_s"), "um/s", "actual_speed_um_s"),
            ("Drag", "Absolute offset", diagnostics.get("offset_um"), "um", "offset_um"),
            ("Drag", "Alignment status", diagnostics.get("alignment_status"), "", "alignment_status"),
            ("Drag", "Physics status", diagnostics.get("physics_status"), "", "physics_status"),
            ("Provenance", "Current drag input", diagnostics.get("current_drag_input_path"), "", "current_drag_input_path"),
            ("Provenance", "Current drag output root", diagnostics.get("current_drag_output_root"), "", "current_drag_output_root"),
            ("Provenance", "Brownian baseline folder", diagnostics.get("brownian_baseline_folder"), "", "brownian_baseline_folder"),
            ("Provenance", "Selected calibration source", diagnostics.get("selected_calibration_path"), "", "selected_calibration_path"),
            ("Provenance", "Selected trajectory source", diagnostics.get("selected_trajectory_path"), "", "selected_trajectory_path"),
            ("Provenance", "Selected timestamps source", diagnostics.get("selected_timestamps_path"), "", "selected_timestamps_path"),
            ("Provenance", "Selected stage meta path", diagnostics.get("selected_stage_meta_path"), "", "selected_stage_meta_path"),
            ("Provenance", "Selected stage trace path", diagnostics.get("selected_stage_trace_path"), "", "selected_stage_trace_path"),
            ("Provenance", "Timing source", diagnostics.get("timing_source"), "", "timing_source"),
            ("Provenance", "Report source kind", diagnostics.get("report_source_kind"), "", "report_source_kind"),
            ("Provenance", "Report source path", diagnostics.get("report_source_path"), "", "report_source_path"),
        ]
        warnings = summary.get("warnings") or []
        if warnings:
            rows.append(("QC", "Warnings detail", " | ".join(str(w) for w in warnings), "", "warnings"))
        return rows
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
        ("Input", "Scale source", metrics.get("scale_source"), "", "scale_source"),
        ("Input", "Temperature", metrics.get("temperature_c"), "C", "temperature_c"),
        ("Input", "Bead diameter", metrics.get("bead_diameter_um"), "um", "bead_diameter_um"),
        ("Input", "Bead source", metrics.get("bead_source"), "", "bead_source"),
        ("Input", "Timing source", diagnostics.get("timing_source"), "", "timing_source"),
        ("Input", "Elapsed time", diagnostics.get("elapsed_time_s"), "s", "elapsed_time_s"),
        ("Input", "Effective fps", diagnostics.get("effective_fps"), "Hz", "effective_fps"),
        ("Key results", "Corner frequency X", diagnostics.get("fc_x_hz"), "Hz", "fc_x_hz"),
        ("Key results", "Corner frequency Y", diagnostics.get("fc_y_hz"), "Hz", "fc_y_hz"),
        ("Key results", "Trap stiffness X", metrics.get("kappa_x_pn_per_um"), "pN/um", "kappa_x_pn_per_um"),
        ("Key results", "Trap stiffness Y", metrics.get("kappa_y_pn_per_um"), "pN/um", "kappa_y_pn_per_um"),
        ("Key results", "Mean viscosity", metrics.get("eta_mean_pa_s"), "Pa*s", "eta_mean_pa_s"),
        ("Key results", "Diffusion coefficient", metrics.get("D_m2_s"), "m^2/s", "D_m2_s"),
        ("QC", "Lost tracking fraction", diagnostics.get("lost_fraction"), "", "lost_fraction"),
        ("QC", "Camera dropped frames", diagnostics.get("camera_dropped_frames"), "frames", "camera_dropped_frames"),
        ("QC", "Tracking lost frames", diagnostics.get("tracking_lost_frames"), "frames", "tracking_lost_frames"),
        ("QC", "Warnings", diagnostics.get("warning_count"), "", "warning_count"),
        ("QC", "Timestamp validation pass", diagnostics.get("timestamp_validation_pass"), "", "timestamp_validation_pass"),
        ("Drag", "Drag force", diagnostics.get("drag_force_n"), "N", "drag_force_n"),
        ("Drag", "Drag offset", diagnostics.get("offset_um"), "um", "offset_um"),
        ("Drag", "Drag stiffness", metrics.get("kappa_drag_pn_per_um"), "pN/um", "kappa_drag_pn_per_um"),
        ("Drag", "Drag/Brownian stiffness ratio", diagnostics.get("ratio_drag_over_brownian"), "", "ratio_drag_over_brownian"),
        ("Drag", "Current drag input", diagnostics.get("current_drag_input_path"), "", "current_drag_input_path"),
        ("Drag", "Brownian baseline folder", diagnostics.get("brownian_baseline_folder"), "", "brownian_baseline_folder"),
        ("Drag", "Selected calibration source", diagnostics.get("selected_calibration_path"), "", "selected_calibration_path"),
        ("Drag", "Selected trajectory source", diagnostics.get("selected_trajectory_path"), "", "selected_trajectory_path"),
        ("Drag", "Selected timestamps source", diagnostics.get("selected_timestamps_path"), "", "selected_timestamps_path"),
        ("Drag", "Alignment status", diagnostics.get("alignment_status"), "", "alignment_status"),
        ("Drag", "Alignment message", diagnostics.get("alignment_message"), "", "alignment_message"),
        ("Drag", "Baseline window", f"{diagnostics.get('baseline_start_s')} -> {diagnostics.get('baseline_end_s')}", "s", "baseline_window"),
        ("Drag", "Steady window", f"{diagnostics.get('steady_start_s')} -> {diagnostics.get('steady_end_s')}", "s", "steady_window"),
        ("Drag", "Actual speed", diagnostics.get("actual_speed_um_s"), "um/s", "actual_speed_um_s"),
        ("Drag", "Viscosity", diagnostics.get("eta_pa_s"), "Pa*s", "eta_pa_s"),
        ("Drag", "Analysis status", diagnostics.get("analysis_status"), "", "analysis_status"),
        ("Drag", "Physics status", diagnostics.get("physics_status"), "", "physics_status"),
        ("Drag", "Drag physics confidence", diagnostics.get("drag_physics_confidence"), "", "drag_physics_confidence"),
        ("Drag", "Drag physics warning", diagnostics.get("drag_physics_warning"), "", "drag_physics_warning"),
        ("Drag", "Offset current windows", diagnostics.get("offset_current_windows_um"), "um", "offset_current_windows_um"),
        ("Drag", "Offset alt baseline", diagnostics.get("offset_alt_baseline_um"), "um", "offset_alt_baseline_um"),
        ("Drag", "Eta current windows", diagnostics.get("eta_current_windows"), "Pa*s", "eta_current_windows"),
        ("Drag", "Eta alt baseline", diagnostics.get("eta_alt_baseline"), "Pa*s", "eta_alt_baseline"),
        ("Drag", "Onset robustness flag", diagnostics.get("onset_robustness_flag"), "", "onset_robustness_flag"),
        ("Drag", "Baseline robustness flag", diagnostics.get("baseline_robustness_flag"), "", "baseline_robustness_flag"),
        ("Drag", "Kinematics robustness flag", diagnostics.get("kinematics_robustness_flag"), "", "kinematics_robustness_flag"),
        ("Drag", "Report source kind", diagnostics.get("report_source_kind"), "", "report_source_kind"),
        ("Drag", "Report source path", diagnostics.get("report_source_path"), "", "report_source_path"),
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
        ["Source file", _wrap(Path(str(summary.get("source_input_path") or "")).name if summary.get("source_input_path") else "n/a", 56)],
    ]


def _drag_cover_rows(summary: dict[str, Any]) -> tuple[list[list[str]], list[list[str]]]:
    diagnostics = summary.get("diagnostics") or {}
    metrics = summary.get("metrics") or {}
    source_name = Path(str(summary.get("source_input_path") or "")).name if summary.get("source_input_path") else "n/a"
    rows = [
        ["Item", _wrap(summary.get("item_id"), 56)],
        ["Status", _fmt_status(summary.get("status"))],
        ["Run ID", _wrap(summary.get("run_id"), 56)],
        ["Source file", _wrap(source_name, 56)],
        ["Drag force [N]", _fmt_value(diagnostics.get("drag_force_n"))],
        ["Viscosity [Pa*s]", _fmt_value(diagnostics.get("eta_pa_s"))],
        ["Drag stiffness [pN/um]", _fmt_value(metrics.get("kappa_drag_pn_per_um"))],
        ["Actual speed [um/s]", _fmt_value(diagnostics.get("actual_speed_um_s"))],
        ["Absolute offset [um]", _fmt_value(diagnostics.get("offset_um"))],
        ["Alignment status", _wrap(diagnostics.get("alignment_status"), 56)],
        ["Physics status", _wrap(diagnostics.get("physics_status"), 56)],
    ]
    return rows[:6], rows[6:]


def _path_entries_for_item(summary: dict[str, Any]) -> list[tuple[str, list[str]]]:
    return [
        ("Source input", _wrap_path_segments(summary.get("source_input_path"), 88)),
        ("Output root", _wrap_path_segments(summary.get("output_root"), 88)),
        ("Analysis directory", _wrap_path_segments(summary.get("analysis_dir"), 88)),
    ]


def _key_result_rows(summary: dict[str, Any]) -> list[list[str]]:
    metrics = summary.get("metrics") or {}
    diagnostics = summary.get("diagnostics") or {}
    return [
        ["Mean viscosity", _fmt_key_result(metrics.get("eta_mean_pa_s"), "Pa*s")],
        ["Diffusion coefficient", _fmt_key_result(metrics.get("D_m2_s"), "m^2/s")],
        ["Trap stiffness X", _fmt_key_result(metrics.get("kappa_x_pn_per_um"), "pN/um")],
        ["Trap stiffness Y", _fmt_key_result(metrics.get("kappa_y_pn_per_um"), "pN/um")],
        ["Corner frequency X", _fmt_key_result(diagnostics.get("fc_x_hz"), "Hz")],
        ["Corner frequency Y", _fmt_key_result(diagnostics.get("fc_y_hz"), "Hz")],
    ]


def _fmt_key_result(value: Any, unit: str, sig_figs: int = 3) -> str:
    """Format value in base SI units as X.XX x 10^n <unit> for Key results table."""
    if value is None:
        return "n/a"
    try:
        val = float(value)
    except Exception:
        return "n/a"
    if not math.isfinite(val):
        return "n/a"
    text = _fmt_scientific_text(val, sig_figs=sig_figs)
    if unit:
        return f"{text} {_fmt_unit(unit)}"
    return text


def _conditions_rows(summary: dict[str, Any]) -> list[list[str]]:
    metrics = summary.get("metrics") or {}
    diagnostics = summary.get("diagnostics") or {}
    return [
        ["Analysis mode", _wrap(metrics.get("mode"), 50)],
        ["Frame rate", _fmt_measure(metrics.get("fps"), "Hz")],
        ["Effective fps", _fmt_measure(diagnostics.get("effective_fps"), "Hz")],
        ["Elapsed time", _fmt_measure(diagnostics.get("elapsed_time_s"), "s")],
        ["Timing source", _wrap(diagnostics.get("timing_source"), 50)],
        ["Scale", _fmt_measure(metrics.get("um_per_px"), "um/px")],
        ["Scale source", _wrap(metrics.get("scale_source"), 50)],
        ["Temperature", _fmt_measure(metrics.get("temperature_c"), "C")],
        ["Bead diameter", _fmt_measure(metrics.get("bead_diameter_um"), "um")],
        ["Bead radius", _fmt_measure(metrics.get("bead_radius_um"), "um")],
        ["Bead source", _wrap(metrics.get("bead_source"), 50)],
        ["Current drag input", _wrap(diagnostics.get("current_drag_input_path"), 50)],
        ["Brownian baseline folder", _wrap(diagnostics.get("brownian_baseline_folder"), 50)],
        ["Selected calibration source", _wrap(diagnostics.get("selected_calibration_path"), 50)],
        ["Selected trajectory source", _wrap(diagnostics.get("selected_trajectory_path"), 50)],
        ["Selected timestamps source", _wrap(diagnostics.get("selected_timestamps_path"), 50)],
        ["Report source kind", _wrap(diagnostics.get("report_source_kind"), 50)],
        ["Report source path", _wrap(diagnostics.get("report_source_path"), 50)],
    ]


def _drag_conditions_rows(summary: dict[str, Any]) -> list[list[str]]:
    diagnostics = summary.get("diagnostics") or {}
    warnings = summary.get("warnings") or []
    qc_flags = diagnostics.get("drag_qc_flags") or {}
    qc_text = ", ".join(f"{k}={v}" for k, v in qc_flags.items()) if qc_flags else "n/a"
    return [
        ["Analysis mode", "DRAG"],
        ["Current drag input", _wrap(diagnostics.get("current_drag_input_path"), 52)],
        ["Current drag output root", _wrap(diagnostics.get("current_drag_output_root"), 52)],
        ["Current drag report path", _wrap(diagnostics.get("current_drag_report_path"), 52)],
        ["Brownian baseline folder", _wrap(diagnostics.get("brownian_baseline_folder"), 52)],
        ["Selected calibration source", _wrap(diagnostics.get("selected_calibration_path"), 52)],
        ["Selected trajectory source", _wrap(diagnostics.get("selected_trajectory_path"), 52)],
        ["Selected timestamps source", _wrap(diagnostics.get("selected_timestamps_path"), 52)],
        ["Selected stage meta path", _wrap(diagnostics.get("selected_stage_meta_path"), 52)],
        ["Selected stage trace path", _wrap(diagnostics.get("selected_stage_trace_path"), 52)],
        ["Report source kind", _wrap(diagnostics.get("report_source_kind"), 52)],
        ["Report source path", _wrap(diagnostics.get("report_source_path"), 52)],
        ["Timing source", _wrap(diagnostics.get("timing_source"), 52)],
        ["Drag physics confidence", _wrap(diagnostics.get("drag_physics_confidence"), 52)],
        ["Drag physics warning", _wrap(diagnostics.get("drag_physics_warning"), 52)],
        ["Alignment message", _wrap(diagnostics.get("alignment_message"), 52)],
        ["Baseline window [s]", _wrap(f"{diagnostics.get('baseline_start_s')} -> {diagnostics.get('baseline_end_s')}", 52)],
        ["Steady window [s]", _wrap(f"{diagnostics.get('steady_start_s')} -> {diagnostics.get('steady_end_s')}", 52)],
        ["Motion start stage [s]", _fmt_value(diagnostics.get("motion_start_stage_s"))],
        ["Motion start video [s]", _fmt_value(diagnostics.get("motion_start_video_s_detected"))],
        ["Motion stop stage-aligned video [s]", _fmt_value(diagnostics.get("motion_stop_video_s_stage_aligned"))],
        ["Alignment offset [s]", _fmt_value(diagnostics.get("alignment_offset_s"))],
        ["Warnings", _wrap(" | ".join(str(w) for w in warnings) if warnings else "none", 52)],
        ["QC flags", _wrap(qc_text, 52)],
    ]


def _drag_alignment_rows(summary: dict[str, Any]) -> list[list[str]]:
    diagnostics = summary.get("diagnostics") or {}
    return [
        ["Alignment status", _wrap(diagnostics.get("alignment_status"), 52)],
        ["Alignment message", _wrap(diagnostics.get("alignment_message"), 52)],
        ["Baseline median", _fmt_value(diagnostics.get("alignment_baseline_median"))],
        ["Baseline MAD", _fmt_value(diagnostics.get("alignment_baseline_mad"))],
        ["Baseline sigma", _fmt_value(diagnostics.get("alignment_baseline_sigma"))],
        ["Onset threshold sigma", _fmt_value(diagnostics.get("alignment_onset_threshold_sigma"))],
        ["Onset threshold abs", _fmt_value(diagnostics.get("alignment_onset_threshold_abs"))],
        ["Onset min hold [s]", _fmt_value(diagnostics.get("alignment_onset_min_hold_s"))],
        ["Baseline samples", _fmt_value(diagnostics.get("alignment_n_baseline_samples"))],
        ["Total samples", _fmt_value(diagnostics.get("alignment_n_total_samples"))],
        ["Frames outside baseline", _fmt_value(diagnostics.get("alignment_n_frames_outside_baseline"))],
        ["Failure reason", _wrap(diagnostics.get("alignment_failure_reason"), 52)],
    ]


def _qc_rows(summary: dict[str, Any]) -> list[list[str]]:
    diagnostics = summary.get("diagnostics") or {}
    warnings = summary.get("warnings") or []
    rows = [
        ["Lost tracking fraction", _fmt_value(diagnostics.get("lost_fraction"))],
        ["Camera dropped frames", _fmt_value(diagnostics.get("camera_dropped_frames"))],
        ["Tracking lost frames", _fmt_value(diagnostics.get("tracking_lost_frames"))],
        ["Timestamp validation pass", _fmt_value(diagnostics.get("timestamp_validation_pass"))],
        ["Timestamp validation message", _wrap(diagnostics.get("timestamp_validation_message"), 52)],
        ["Warnings", _fmt_value(diagnostics.get("warning_count"))],
        ["Alignment status", _wrap(diagnostics.get("alignment_status"), 52)],
        ["Alignment message", _wrap(diagnostics.get("alignment_message"), 52)],
        ["Baseline window [s]", _wrap(f"{diagnostics.get('baseline_start_s')} -> {diagnostics.get('baseline_end_s')}", 52)],
        ["Steady window [s]", _wrap(f"{diagnostics.get('steady_start_s')} -> {diagnostics.get('steady_end_s')}", 52)],
        ["Motion start stage [s]", _fmt_value(diagnostics.get("motion_start_stage_s"))],
        ["Motion start video [s]", _fmt_value(diagnostics.get("motion_start_video_s_detected"))],
        ["Motion stop stage-aligned video [s]", _fmt_value(diagnostics.get("motion_stop_video_s_stage_aligned"))],
        ["Alignment offset [s]", _fmt_value(diagnostics.get("alignment_offset_s"))],
        ["Drag force [N]", _fmt_value(diagnostics.get("drag_force_n"))],
        ["Offset [um]", _fmt_value(diagnostics.get("offset_um"))],
        ["Drag stiffness [pN/um]", _fmt_value((summary.get("metrics") or {}).get("kappa_drag_pn_per_um"))],
        ["Viscosity [Pa*s]", _fmt_value(diagnostics.get("eta_pa_s"))],
        ["Actual speed [um/s]", _fmt_value(diagnostics.get("actual_speed_um_s"))],
        ["Stage speed from trace [um/s]", _fmt_value(diagnostics.get("stage_speed_from_trace_um_s"))],
        ["Stage speed relative diff", _fmt_value(diagnostics.get("stage_speed_relative_diff"))],
        ["Stage speed consistent", _fmt_value(diagnostics.get("stage_speed_consistent"))],
        ["Offset current windows [um]", _fmt_value(diagnostics.get("offset_current_windows_um"))],
        ["Offset alt baseline [um]", _fmt_value(diagnostics.get("offset_alt_baseline_um"))],
        ["Eta current windows [Pa*s]", _fmt_value(diagnostics.get("eta_current_windows"))],
        ["Eta alt baseline [Pa*s]", _fmt_value(diagnostics.get("eta_alt_baseline"))],
        ["Baseline robustness flag", _fmt_value(diagnostics.get("baseline_robustness_flag"))],
        ["Onset robustness flag", _fmt_value(diagnostics.get("onset_robustness_flag"))],
        ["Kinematics robustness flag", _fmt_value(diagnostics.get("kinematics_robustness_flag"))],
        ["Analysis status", _fmt_value(diagnostics.get("analysis_status"))],
        ["Physics status", _fmt_value(diagnostics.get("physics_status"))],
    ]
    if summary.get("error"):
        rows.append(["Failure reason", _wrap(summary.get("error"), 52)])
    if warnings:
        rows.append(["Warnings detail", _wrap(" | ".join(str(w) for w in warnings), 52)])
    return rows


def _batch_overview_rows(batch_summary: dict[str, Any], items: list[dict[str, Any]], successes: list[dict[str, Any]], failures: list[dict[str, Any]]) -> list[list[str]]:
    return [
        ["Batch ID", _wrap(batch_summary.get("batch_id"), 58)],
        ["Items total", str(len(items))],
        ["Successful", str(len(successes))],
        ["Failed / stopped", str(len(failures))],
    ]


def _path_entries_for_batch(batch_summary: dict[str, Any]) -> list[tuple[str, list[str]]]:
    return [
        ("Output root", _wrap_path_segments(batch_summary.get("output_root"), 88)),
        ("Batch root", _wrap_path_segments(batch_summary.get("batch_root"), 88)),
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
    # Prefer raster (e.g. PNG) so matplotlib's imread/imshow can display in PDF; SVG is not supported by imread
    if path.is_file():
        return (label, path)
    svg_path = path.with_suffix(".svg")
    if svg_path.is_file():
        return (label, svg_path)
    return None


def _style_table(table, body_font_size: int = 9, header_font_size: int = 10) -> None:
    table.auto_set_font_size(False)
    row_line_counts: dict[int, int] = {}
    for (row_idx, _col_idx), cell in table.get_celld().items():
        text_obj = cell.get_text()
        cell.PAD = 0.14
        text_obj.set_wrap(True)
        text_obj.set_ha("left")
        text_obj.set_va("center")
        line_count = max(1, str(text_obj.get_text() or "").count("\n") + 1)
        row_line_counts[row_idx] = max(row_line_counts.get(row_idx, 1), line_count)
        cell.set_linewidth(0.45)
        cell.set_edgecolor(LINE_COLOR)
        if row_idx == 0:
            cell.set_facecolor(BRAND_COLOR)
            text_obj.set_color("white")
            text_obj.set_fontsize(header_font_size)
            text_obj.set_fontweight("bold")
        else:
            cell.set_facecolor(PANEL_BG if row_idx % 2 == 0 else CARD_BG)
            text_obj.set_fontsize(body_font_size)
            text_obj.set_color(TEXT_COLOR)
            if _col_idx == 0:
                text_obj.set_fontweight("bold")
    for (row_idx, _col_idx), cell in table.get_celld().items():
        base_height = 0.062 if row_idx == 0 else 0.052
        cell.set_height(base_height * row_line_counts.get(row_idx, 1))


def _wrap_lines(value: Any, width: int) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return ["n/a"]
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [text]


def _add_panel(fig, bounds: tuple[float, float, float, float], *, facecolor: str = CARD_BG) -> None:
    from matplotlib.patches import FancyBboxPatch

    x, y, width, height = bounds
    panel = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.010,rounding_size=0.018",
        transform=fig.transFigure,
        facecolor=facecolor,
        edgecolor=LINE_COLOR,
        linewidth=0.9,
        zorder=-5,
    )
    fig.add_artist(panel)


def _cover_table_col_width(rows: list[list[str]], *, min_fraction: float = 0.30, max_fraction: float = 0.46) -> float:
    label_len = max((len(str(row[0])) for row in rows if row), default=12)
    value_len = max((len(str(row[1])) for row in rows if len(row) > 1), default=24)
    total = max(1, label_len + value_len)
    estimate = (label_len + 4) / (total + 6)
    return max(min_fraction, min(max_fraction, estimate))


def _render_cover_card(
    fig,
    bounds: tuple[float, float, float, float],
    title: str,
    rows: list[list[str]],
    *,
    facecolor: str,
    header_label: str,
    label_wrap: int,
    value_wrap: int,
    min_label_fraction: float = 0.30,
    max_label_fraction: float = 0.46,
) -> None:
    x, y, width, height = bounds
    _add_panel(fig, bounds, facecolor=facecolor)
    fig.text(x + (width * 0.5), y + height - 0.035, title, fontsize=12.5, fontweight="bold", color=TEXT_COLOR, ha="center")

    wrapped_rows = [
        [
            _wrap(str(row[0] if len(row) > 0 else ""), width=label_wrap),
            _wrap(str(row[1] if len(row) > 1 else ""), width=value_wrap),
        ]
        for row in rows
    ]
    label_width = _cover_table_col_width(wrapped_rows, min_fraction=min_label_fraction, max_fraction=max_label_fraction)

    ax = fig.add_axes([x + 0.018, y + 0.028, width - 0.036, height - 0.095])
    ax.axis("off")
    table = ax.table(
        cellText=wrapped_rows,
        colLabels=[header_label, "Value"],
        cellLoc="left",
        colLoc="left",
        colWidths=[label_width, 1.0 - label_width],
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    table.auto_set_font_size(False)
    row_line_counts: dict[int, int] = {}
    for (row_idx, col_idx), cell in table.get_celld().items():
        text_obj = cell.get_text()
        cell.PAD = 0.12
        text_obj.set_wrap(True)
        text_obj.set_ha("left")
        text_obj.set_va("center")
        line_count = max(1, str(text_obj.get_text() or "").count("\n") + 1)
        row_line_counts[row_idx] = max(row_line_counts.get(row_idx, 1), line_count)
        cell.set_linewidth(0.45)
        cell.set_edgecolor(LINE_COLOR)
        if row_idx == 0:
            cell.set_facecolor(BRAND_COLOR)
            text_obj.set_color("white")
            text_obj.set_fontsize(10)
            text_obj.set_fontweight("bold")
        else:
            cell.set_facecolor(PANEL_BG if row_idx % 2 == 0 else CARD_BG)
            text_obj.set_color(TEXT_COLOR)
            text_obj.set_fontsize(9.2)
            if col_idx == 0:
                text_obj.set_fontweight("bold")
    for (row_idx, _col_idx), cell in table.get_celld().items():
        base_height = 0.088 if row_idx == 0 else 0.078
        cell.set_height(base_height * row_line_counts.get(row_idx, 1))


def _cover_key_result_rows(summary_rows: list[list[str]]) -> list[list[str]]:
    out: list[list[str]] = []
    for label, value in summary_rows:
        out.append([str(label), str(value)])
    return out


def _batch_cover_key_rows(batch_summary: dict[str, Any]) -> list[list[str]]:
    return [
        ["Report generated", _wrap(datetime.now().isoformat(timespec="seconds"), 22)],
        ["Comparison focus", _wrap("Viscosity, diffusion, stiffness, corner frequency", 24)],
        ["Primary outputs", _wrap("Summary tables, grouped QC, PSD, histogram curves", 24)],
    ]


class PageCounter:
    """Helper to track global page numbers across PDF generation."""
    def __init__(self):
        self.current = 0
        self.total = 0

    def next(self) -> int:
        self.current += 1
        return self.current

    def page_str(self) -> str:
        return f"-- {self.current} of {self.total} --" if self.total > 0 else f"-- {self.current} --"


def _add_page_footer(fig, page_counter: PageCounter | None) -> None:
    """Add page number footer to figure (bottom-right corner)."""
    if page_counter is not None:
        page_counter.next()
        fig.text(
            1 - PAGE_MARGIN_RIGHT, 0.02, page_counter.page_str(),
            fontsize=9, color=MUTED_COLOR, ha="right", va="bottom"
        )


def _add_brand_header(
    fig,
    title: str | None = None,
    subtitle: str | None = None,
    page_note: str | None = None,
    *,
    cover: bool = False,
    page_counter: PageCounter | None = None,
) -> None:
    from matplotlib.lines import Line2D

    center_x = 0.50
    logo_image = _load_header_logo()
    if logo_image is not None:
        logo_ax = fig.add_axes([0.07, 0.916, 0.23, 0.055], anchor="NW")
        logo_ax.imshow(logo_image)
        logo_ax.axis("off")
    else:
        fig.text(0.07, 0.955, BRAND_NAME, fontsize=18, fontweight="bold", color=BRAND_COLOR)

    fig.text(center_x, 0.952, REPORT_NAME, fontsize=10.5, color=MUTED_COLOR, ha="center")
    if not cover and title:
        fig.text(center_x, 0.916, title, fontsize=19, fontweight="bold", color=TEXT_COLOR, ha="center")
    if not cover and subtitle:
        fig.text(center_x, 0.890, subtitle, fontsize=10.2, color=MUTED_COLOR, ha="center")
    if page_note:
        fig.text(0.93, 0.955, page_note, fontsize=9, color=MUTED_COLOR, ha="right")
    fig.add_artist(Line2D([0.06, 0.94], [0.875, 0.875], transform=fig.transFigure, color=ACCENT_COLOR, linewidth=1.4))

    # Add page footer if counter provided
    _add_page_footer(fig, page_counter)


def _render_cover_page(
    pdf,
    title: str,
    subtitle: str,
    left_rows: list[list[str]],
    right_rows: list[list[str]],
    *,
    eyebrow: str = "Scientific Summary",
    page_counter: PageCounter | None = None,
) -> None:
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, page_note=None, cover=True, page_counter=page_counter)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.50, 0.812, eyebrow, fontsize=10.5, color=ACCENT_COLOR, fontweight="bold", ha="center")
    ax.text(0.50, 0.768, title, fontsize=24, fontweight="bold", color=TEXT_COLOR, ha="center")
    ax.text(0.50, 0.729, subtitle, fontsize=11.2, color=MUTED_COLOR, ha="center")
    ax.text(
        0.50,
        0.688,
        "Prepared for scientific review and external sharing.",
        fontsize=10.4,
        color=TEXT_COLOR,
        ha="center",
        wrap=True,
    )

    _render_cover_card(
        fig,
        (0.05, 0.225, 0.43, 0.37),
        "Report details",
        left_rows,
        facecolor=CARD_BG,
        header_label="Report detail",
        label_wrap=16,
        value_wrap=34,
        min_label_fraction=0.31,
        max_label_fraction=0.40,
    )
    _render_cover_card(
        fig,
        (0.52, 0.225, 0.43, 0.37),
        "Key results",
        _cover_key_result_rows(right_rows),
        facecolor=PANEL_BG,
        header_label="Key result",
        label_wrap=22,
        value_wrap=22,
        min_label_fraction=0.40,
        max_label_fraction=0.52,
    )

    fig.text(
        0.50,
        0.12,
        "The sections that follow retain the same measurements, QC outputs, plots, and exported artifacts as the analysis pipeline.",
        fontsize=9.2,
        color=MUTED_COLOR,
        ha="center",
    )
    pdf.savefig(fig)
    plt.close(fig)


def _render_theory_page(
    pdf,
    page_counter: PageCounter | None = None,
    physics_mode: str | None = None,
) -> None:
    """Render a page explaining the theoretical basis of OT calibration with proper equations."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Theory and Methods", page_counter=page_counter)

    ax = fig.add_axes([PAGE_MARGIN_LEFT, PAGE_MARGIN_BOTTOM + 0.02, 
                       1 - PAGE_MARGIN_LEFT - PAGE_MARGIN_RIGHT, 0.76])
    ax.axis("off")

    # Structured theory content with mathtext equations
    y = 0.98
    line_height = 0.032
    section_gap = 0.025
    equation_gap = 0.045

    # Title
    ax.text(
        0.0,
        y,
        "Optical Tweezers Calibration Theory",
        fontsize=FONT_SIZE_HEADER,
        fontweight="bold",
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height * 1.5

    # Intro
    _mode = str(physics_mode or "").upper().strip()
    if _mode == "DRAGGING":
        intro_line = (
            "This report includes drag/motion-calibrated results. Brownian formulas are shown for cross-checking"
        )
    else:
        intro_line = (
            "This report presents results from passive calibration of optical tweezers using Brownian motion"
        )
    ax.text(
        0.0,
        y,
        intro_line,
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    second_line = (
        "The DRAG sections use stage-aligned motion timing and steady-state displacement windows."
        if _mode == "DRAGGING"
        else "analysis of a trapped microsphere."
    )
    ax.text(
        0.0,
        y,
        second_line,
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height + section_gap

    # Equipartition Theorem
    ax.text(
        0.0,
        y,
        "Equipartition Theorem",
        fontsize=11,
        fontweight="bold",
        color=BRAND_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "The trap stiffness is calculated from the variance of particle position:",
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= equation_gap
    ax.text(
        0.5,
        y,
        r"$\kappa = \frac{k_{\mathrm{B}} T}{\langle x^2 \rangle}$",
        fontsize=14,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        ha="center",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "where $k_{\mathrm{B}}$ is the Boltzmann constant, $T$ is temperature, and $\\langle x^2 \\rangle$ is the",
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        fontstyle="italic",
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "position variance of the trapped particle.",
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        fontstyle="italic",
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height + section_gap

    # PSD Analysis
    ax.text(
        0.0,
        y,
        "Power Spectral Density (PSD) Analysis",
        fontsize=11,
        fontweight="bold",
        color=BRAND_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "The corner frequency is obtained by fitting a Lorentzian function to the one-sided PSD:",
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= equation_gap
    ax.text(
        0.5,
        y,
        r"$P(f) = \frac{A}{f_{\mathrm{c}}^{2} + f^{2}} + B$",
        fontsize=14,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        ha="center",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "The corner frequency relates to trap stiffness and viscous drag through",
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= equation_gap
    ax.text(
        0.5,
        y,
        r"$f_{\mathrm{c}} = \frac{\kappa}{2\pi\gamma}$,",
        fontsize=14,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        ha="center",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        r"where $\gamma = 6 \pi \eta R$ is the Stokes drag coefficient for a sphere of radius $R$ in a fluid",
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        fontstyle="italic",
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "with dynamic viscosity $\\eta$.",
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        fontstyle="italic",
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height + section_gap

    # Viscosity
    ax.text(
        0.0,
        y,
        "Viscosity Determination",
        fontsize=11,
        fontweight="bold",
        color=BRAND_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "The medium viscosity can be inferred from the measured trap stiffness and corner frequency:",
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= equation_gap
    ax.text(
        0.5,
        y,
        r"$\eta = \frac{\kappa}{12 \pi^{2} R f_{\mathrm{c}}}$",
        fontsize=14,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        ha="center",
    )
    y -= line_height + section_gap

    # Diffusion
    ax.text(
        0.0,
        y,
        "Diffusion Coefficient",
        fontsize=11,
        fontweight="bold",
        color=BRAND_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "The translational diffusion coefficient follows from the Stokes–Einstein relation:",
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= equation_gap
    ax.text(
        0.5,
        y,
        r"$D = \frac{k_{\mathrm{B}} T}{6 \pi \eta R}$",
        fontsize=14,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        ha="center",
    )
    y -= line_height + section_gap

    # Uncertainty
    ax.text(
        0.0,
        y,
        "Uncertainty Estimation",
        fontsize=11,
        fontweight="bold",
        color=BRAND_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "Measurement uncertainties are propagated from:",
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        r"- Position variance standard error, with $\mathrm{SE}(\sigma^{2}) = \sigma^{2} \sqrt{\frac{2}{n-1}}$",
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        fontstyle="italic",
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "- PSD fitting uncertainty for the corner frequency $f_{\mathrm{c}}$, obtained from the Lorentzian fit.",
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        fontstyle="italic",
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height + section_gap

    # References
    ax.text(
        0.0,
        y,
        "References",
        fontsize=11,
        fontweight="bold",
        color=BRAND_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height
    ax.text(
        0.0,
        y,
        "[1] K. Berg-Sorensen, H. Flyvbjerg, Rev. Sci. Instrum. 75, 594 (2004)",
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )

    pdf.savefig(fig)
    plt.close(fig)


def _render_drag_theory_page(
    pdf,
    *,
    page_counter: PageCounter | None = None,
) -> None:
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Drag Theory and Method", page_counter=page_counter)

    ax = fig.add_axes([PAGE_MARGIN_LEFT, PAGE_MARGIN_BOTTOM + 0.02, 1 - PAGE_MARGIN_LEFT - PAGE_MARGIN_RIGHT, 0.76])
    ax.axis("off")

    lines = [
        "Constant-velocity drag method",
        "",
        "1) Current drag trajectory is analyzed in the active run.",
        "2) Brownian baseline is used only for calibration (kappa, optional scale).",
        "3) Baseline and steady-state windows are resolved on the current drag trajectory.",
        "4) Offset is computed between baseline and steady-state positions.",
        "5) Drag force is inferred as: F_drag = kappa * offset.",
        "6) Viscosity is inferred from drag force and actual stage speed.",
        "",
        "Provenance note:",
        "Current trajectory source is intentionally independent from baseline source.",
        "The report always lists both sources explicitly for auditability.",
    ]
    ax.text(
        0.0,
        0.98,
        "\n".join(lines),
        fontsize=10.5,
        color=TEXT_COLOR,
        va="top",
        family=FONT_FAMILY,
        linespacing=1.5,
    )
    pdf.savefig(fig)
    plt.close(fig)


def _render_path_block_pages(
    pdf,
    title: str,
    entries: list[tuple[str, list[str]]],
    *,
    subtitle: str | None = None,
    page_counter: PageCounter | None = None,
) -> None:
    import matplotlib.pyplot as plt

    if not entries:
        return

    idx = 0
    while idx < len(entries):
        fig = plt.figure(figsize=PAGE_SIZE)
        fig.patch.set_facecolor("white")
        _add_brand_header(fig, title, subtitle=subtitle, page_counter=page_counter)
        ax = fig.add_axes([PAGE_MARGIN_LEFT, PAGE_MARGIN_BOTTOM, 
                          1 - PAGE_MARGIN_LEFT - PAGE_MARGIN_RIGHT, 0.78])
        ax.axis("off")

        y = 0.98
        while idx < len(entries):
            label, lines = entries[idx]
            block_height = 0.05 + (0.030 * max(1, len(lines)))
            if y - block_height < 0.06:
                break

            ax.text(0.0, y, label, fontsize=11, fontweight="bold", color=TEXT_COLOR, 
                    va="top", family=FONT_FAMILY)
            y -= 0.038
            ax.text(
                0.02,
                y,
                "\n".join(lines),
                fontsize=8.6,
                color=TEXT_COLOR,
                va="top",
                family="monospace",
                linespacing=1.25,
            )
            y -= (0.030 * max(1, len(lines))) + 0.03
            ax.hlines(y + 0.012, 0.0, 0.98, colors=LINE_COLOR, linewidth=0.8, transform=ax.transAxes)
            idx += 1

        pdf.savefig(fig)
        plt.close(fig)


def _render_paginated_table(
    pdf,
    title: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    subtitle: str | None = None,
    rows_per_page: int = 16,
    page_counter: PageCounter | None = None,
) -> None:
    import matplotlib.pyplot as plt

    if not rows:
        return
    chunks = _chunked(rows, rows_per_page)
    for idx, chunk in enumerate(chunks, start=1):
        fig = plt.figure(figsize=PAGE_SIZE)
        fig.patch.set_facecolor("white")
        _add_brand_header(fig, title, subtitle=subtitle, page_counter=page_counter)
        ax = fig.add_axes([PAGE_MARGIN_LEFT, PAGE_MARGIN_BOTTOM, 
                          1 - PAGE_MARGIN_LEFT - PAGE_MARGIN_RIGHT, 0.76])
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
        pdf.savefig(fig)
        plt.close(fig)


def _render_dual_table_page(
    pdf,
    title: str,
    top_title: str,
    top_rows: list[list[str]],
    bottom_title: str,
    bottom_rows: list[list[str]],
    *,
    page_counter: PageCounter | None = None,
) -> None:
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, title, page_counter=page_counter)

    _add_panel(fig, (0.06, 0.46, 0.88, 0.31), facecolor=CARD_BG)
    _add_panel(fig, (0.06, 0.09, 0.88, 0.29), facecolor=PANEL_BG)

    ax_top_title = fig.add_axes([PAGE_MARGIN_LEFT, 0.74, 0.84, 0.05])
    ax_top_title.axis("off")
    ax_top_title.text(0.0, 0.5, top_title, fontsize=FONT_SIZE_HEADER, fontweight="bold", 
                      color=TEXT_COLOR, va="center", family=FONT_FAMILY)

    ax_top = fig.add_axes([PAGE_MARGIN_LEFT, 0.495, 0.84, 0.23])
    ax_top.axis("off")
    top_table = ax_top.table(
        cellText=top_rows,
        colLabels=["Field", "Value"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    _style_table(top_table)

    ax_bottom_title = fig.add_axes([PAGE_MARGIN_LEFT, 0.34, 0.84, 0.05])
    ax_bottom_title.axis("off")
    ax_bottom_title.text(0.0, 0.5, bottom_title, fontsize=FONT_SIZE_HEADER, fontweight="bold", 
                         color=TEXT_COLOR, va="center", family=FONT_FAMILY)

    ax_bottom = fig.add_axes([PAGE_MARGIN_LEFT, 0.125, 0.84, 0.19])
    ax_bottom.axis("off")
    bottom_table = ax_bottom.table(
        cellText=bottom_rows,
        colLabels=["Field", "Value"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    _style_table(bottom_table)

    pdf.savefig(fig)
    plt.close(fig)


def _render_plot_pages(
    pdf,
    title: str,
    entries: list[tuple[str, Path, tuple[str, ...], tuple[str, ...], str, str, bool, bool]],
    *,
    layout: str = "vertical",
    items_per_page: int = 2,
    page_counter: PageCounter | None = None,
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
        fig.patch.set_facecolor("white")
        _add_brand_header(fig, title, page_counter=page_counter)
        fig.subplots_adjust(top=0.81, left=0.10, right=0.92, bottom=0.09, hspace=0.46, wspace=0.28)
        flat_axes = list(axes.flatten()) if hasattr(axes, "flatten") else [axes]
        for ax in flat_axes:
            ax.axis("off")
        for ax, (label, csv_path, x_opts, y_opts, x_title, y_title, log_x, log_y) in zip(flat_axes, chunk):
            parsed = _csv_numeric_columns(csv_path, x_opts, y_opts)
            if parsed is None:
                ax.axis("off")
                ax.text(0.5, 0.5, f"Not available\n{label}", ha="center", va="center", 
                        color=MUTED_COLOR, family=FONT_FAMILY)
                continue
            xs, ys, _, _ = parsed
            ax.axis("on")
            ax.set_facecolor(PANEL_BG)
            ax.plot(xs, ys, linewidth=1.6, color=PLOT_COLOR)
            if log_x:
                ax.set_xscale("log")
            if log_y:
                ax.set_yscale("log")
            ax.set_title(label, fontsize=11.5, fontweight="bold", color=TEXT_COLOR, 
                         pad=10, family=FONT_FAMILY)
            ax.set_xlabel(x_title, fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
            ax.set_ylabel(y_title, fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
            ax.tick_params(labelsize=8)
            ax.grid(True, which="both", linestyle="--", linewidth=0.5, color=LINE_COLOR)
            for spine in ax.spines.values():
                spine.set_color(LINE_COLOR)
        pdf.savefig(fig)
        plt.close(fig)


def _render_trajectory_heatmap_page(
    pdf,
    trajectory_csv: Path,
    title: str = "Trajectory",
    *,
    page_counter: PageCounter | None = None,
) -> None:
    """Render trajectory as 2D heatmap with marginal X/Y histograms (scatter_hist style)."""
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    import numpy as np

    parsed = _csv_numeric_columns(trajectory_csv, ("x_corr_um", "x_corr_px", "x_px"), ("y_corr_um", "y_corr_px", "y_px"))
    if parsed is None:
        return

    xs, ys, _, _ = parsed
    xs = np.array(xs, dtype=np.float64)
    ys = np.array(ys, dtype=np.float64)

    # Center the data
    xs = xs - np.nanmean(xs)
    ys = ys - np.nanmean(ys)

    xrange = [np.percentile(xs, 0.5), np.percentile(xs, 99.5)]
    yrange = [np.percentile(ys, 0.5), np.percentile(ys, 99.5)]
    bins = 80

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, title, page_counter=page_counter)

    # Scatter_hist layout: histx top, scatter bottom-left, histy right, colorbar far right
    gs = GridSpec(
        2,
        3,
        width_ratios=[4, 1, 0.35],
        height_ratios=[1, 4],
        left=PAGE_MARGIN_LEFT,
        right=1 - PAGE_MARGIN_RIGHT,
        bottom=PAGE_MARGIN_BOTTOM + 0.02,
        top=0.84,
        wspace=0.05,
        hspace=0.05,
    )

    ax_histx = fig.add_subplot(gs[0, 0])
    ax_main = fig.add_subplot(gs[1, 0])
    ax_histy = fig.add_subplot(gs[1, 1])
    ax_cbar = fig.add_subplot(gs[1, 2])

    # Central 2D histogram (heatmap)
    _, _, _, im = ax_main.hist2d(xs, ys, bins=bins, cmap="viridis", range=[xrange, yrange])
    ax_main.set_aspect("equal", adjustable="box")
    ax_main.set_xlabel("X position [µm]", fontsize=FONT_SIZE_NORMAL, family=FONT_FAMILY)
    ax_main.set_ylabel("Y position [µm]", fontsize=FONT_SIZE_NORMAL, family=FONT_FAMILY)
    ax_main.tick_params(labelsize=8)
    ax_main.grid(True, linestyle="--", linewidth=0.3, color=LINE_COLOR, alpha=0.5)

    # Marginal histogram X (top)
    ax_histx.hist(xs, bins=bins, range=xrange, color=PLOT_COLOR, alpha=0.7, edgecolor="white", linewidth=0.3)
    ax_histx.tick_params(axis="x", labelbottom=False)
    ax_histx.set_ylabel("Counts", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
    ax_histx.set_facecolor(PANEL_BG)
    ax_histx.tick_params(labelsize=8)

    # Marginal histogram Y (right)
    ax_histy.hist(ys, bins=bins, range=yrange, orientation="horizontal", color=PLOT_COLOR, alpha=0.7, edgecolor="white", linewidth=0.3)
    ax_histy.tick_params(axis="y", labelleft=False)
    ax_histy.set_xlabel("Counts", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
    ax_histy.set_facecolor(PANEL_BG)
    ax_histy.tick_params(labelsize=8)

    # Colorbar
    cbar = fig.colorbar(im, cax=ax_cbar)
    cbar.set_label("Counts", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
    cbar.ax.tick_params(labelsize=8)

    pdf.savefig(fig)
    plt.close(fig)


def _render_histogram_r_and_msd_page(
    pdf,
    hist_r_csv: Path | str | None,
    msd_csv: Path | str | None,
    *,
    page_counter: PageCounter | None = None,
) -> None:
    """Render one page with Histogram R curve and MSD plot stacked vertically."""
    import matplotlib.pyplot as plt

    # Two rows, one column: top = Histogram R, bottom = MSD
    fig, axes = plt.subplots(2, 1, figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Histogram R And MSD", page_counter=page_counter)
    fig.subplots_adjust(top=0.81, left=0.10, right=0.92, bottom=0.09, hspace=0.38)

    ax_hist, ax_msd = axes

    # Histogram R curve (top panel)
    hist_path = Path(hist_r_csv) if hist_r_csv else None
    if hist_path and hist_path.is_file():
        parsed = _csv_numeric_columns(hist_path, ("bin_center_um", "bin_center_px"), ("count", "density"))
        if parsed is not None:
            xs, ys, _, _ = parsed
            ax_hist.set_facecolor(PANEL_BG)
            ax_hist.plot(xs, ys, linewidth=1.6, color=PLOT_COLOR)
            ax_hist.set_title("Histogram R curve", fontsize=11.5, fontweight="bold", color=TEXT_COLOR, pad=10, family=FONT_FAMILY)
            ax_hist.set_xlabel("Bin center", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
            ax_hist.set_ylabel("Counts", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
            ax_hist.tick_params(labelsize=8)
            ax_hist.grid(True, which="both", linestyle="--", linewidth=0.5, color=LINE_COLOR)
            for spine in ax_hist.spines.values():
                spine.set_color(LINE_COLOR)
        else:
            ax_hist.axis("off")
            ax_hist.text(0.5, 0.5, "Not available\nHistogram R curve", ha="center", va="center", color=MUTED_COLOR, family=FONT_FAMILY)
    else:
        ax_hist.axis("off")
        ax_hist.text(0.5, 0.5, "Not available\nHistogram R curve", ha="center", va="center", color=MUTED_COLOR, family=FONT_FAMILY)

    # MSD (bottom panel)
    msd_path = Path(msd_csv) if msd_csv else None
    if msd_path and msd_path.is_file():
        msd_parsed = _csv_numeric_columns(msd_path, ("tau_s",), ("msd_r_um2", "msd_r_px2"))
        if msd_parsed is not None:
            msd_xs, msd_ys, _, _ = msd_parsed
            ax_msd.set_facecolor(PANEL_BG)
            ax_msd.loglog(msd_xs, msd_ys, color=PLOT_COLOR, linewidth=1.5)
            ax_msd.set_title("MSD", fontsize=11.5, fontweight="bold", color=TEXT_COLOR, pad=10, family=FONT_FAMILY)
            ax_msd.set_xlabel("τ [s]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
            ax_msd.set_ylabel("MSD [µm²]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
            ax_msd.tick_params(labelsize=8)
            ax_msd.grid(True, which="both", linestyle="--", linewidth=0.5, color=LINE_COLOR)
            for spine in ax_msd.spines.values():
                spine.set_color(LINE_COLOR)
        else:
            ax_msd.axis("off")
            ax_msd.text(0.5, 0.5, "Not available\nMSD", ha="center", va="center", color=MUTED_COLOR, family=FONT_FAMILY)
    else:
        ax_msd.axis("off")
        ax_msd.text(0.5, 0.5, "Not available\nMSD", ha="center", va="center", color=MUTED_COLOR, family=FONT_FAMILY)

    pdf.savefig(fig)
    plt.close(fig)


def _render_preview_grid_page(
    pdf,
    image_paths: list[Path],
    *,
    page_counter: PageCounter | None = None,
) -> None:
    """Render a grid of preview frames (thumbnails) with indices in the top-left corners."""
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    if not image_paths:
        return

    # Use at most 10 images, laid out in up to 3x4 grid (12 slots)
    max_images = 10
    paths = [Path(p) for p in image_paths][:max_images]

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Preview Frames", page_counter=page_counter)

    nrows, ncols = 3, 4
    gs = GridSpec(
        nrows,
        ncols,
        left=PAGE_MARGIN_LEFT,
        right=1 - PAGE_MARGIN_RIGHT,
        bottom=PAGE_MARGIN_BOTTOM + 0.02,
        top=0.84,
        wspace=0.12,
        hspace=0.18,
    )

    idx = 0
    for r in range(nrows):
        for c in range(ncols):
            ax = fig.add_subplot(gs[r, c])
            ax.axis("off")
            if idx >= len(paths):
                continue
            path = paths[idx]
            idx += 1
            try:
                img = mpimg.imread(path)
                ax.imshow(img, cmap=None)
                ax.axis("off")
                # Index in top-left corner (1-based)
                ax.text(
                    0.03,
                    0.95,
                    f"{idx}",
                    transform=ax.transAxes,
                    ha="left",
                    va="top",
                    fontsize=FONT_SIZE_SMALL,
                    color="white",
                    bbox=dict(boxstyle="round,pad=0.18", fc="black", ec="none", alpha=0.6),
                )
            except Exception:
                ax.text(
                    0.5,
                    0.5,
                    "Not available",
                    ha="center",
                    va="center",
                    color=MUTED_COLOR,
                    family=FONT_FAMILY,
                )

    pdf.savefig(fig)
    plt.close(fig)


def _render_drag_windows_table_page(
    pdf,
    windows_csv: Path,
    *,
    page_counter: PageCounter | None = None,
) -> None:
    rows: list[list[str]] = []
    try:
        with windows_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(
                    [
                        _fmt_value(row.get("window")),
                        _fmt_value(row.get("start_s")),
                        _fmt_value(row.get("end_s")),
                        _fmt_value(row.get("duration_s")),
                    ]
                )
    except Exception:
        rows = []
    if not rows:
        return
    _render_paginated_table(
        pdf,
        "Drag Windows",
        ["Window", "Start [s]", "End [s]", "Duration [s]"],
        rows,
        rows_per_page=18,
        page_counter=page_counter,
    )


def _render_image_pages(
    pdf,
    title: str,
    entries: list[tuple[str, Path]],
    *,
    layout: str = "vertical",
    items_per_page: int = 2,
    page_counter: PageCounter | None = None,
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
        fig.patch.set_facecolor("white")
        _add_brand_header(fig, title, page_counter=page_counter)
        fig.subplots_adjust(top=0.81, left=PAGE_MARGIN_LEFT, right=1-PAGE_MARGIN_RIGHT, 
                           bottom=PAGE_MARGIN_BOTTOM + 0.02, hspace=0.34, wspace=0.20)
        flat_axes = list(axes.flatten()) if hasattr(axes, "flatten") else [axes]
        for ax in flat_axes:
            ax.axis("off")
        for ax, (label, path) in zip(flat_axes, chunk):
            try:
                image = mpimg.imread(path)
                ax.set_facecolor(PANEL_BG)
                ax.imshow(image)
                ax.set_title(label, fontsize=11.5, fontweight="bold", color=TEXT_COLOR, 
                            pad=10, family=FONT_FAMILY)
                ax.axis("off")
            except Exception:
                ax.axis("off")
                ax.text(0.5, 0.5, f"Not available\n{label}", ha="center", va="center", 
                        color=MUTED_COLOR, family=FONT_FAMILY)
        pdf.savefig(fig)
        plt.close(fig)


def export_ot_item_pdf(report_path: Path | str, summary: dict[str, Any]) -> Path:
    try:
        from matplotlib.backends.backend_pdf import PdfPages
    except Exception as e:
        raise RuntimeError("matplotlib with PdfPages is required for OT PDF export.") from e

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts = summary.get("artifacts") or {}
    preview_paths = [Path(p) for p in (artifacts.get("preview_grid_pngs") or []) if p]
    drag_mode = _is_drag_report(summary)

    psd_entries = [
        entry
        for entry in (
            _build_plot_entry("PSD X", artifacts.get("psd_x_csv"), ("f_hz",), ("psd_um2_per_hz", "psd_px2_per_hz"), "Frequency [Hz]", "PSD", True, True),
            _build_plot_entry("PSD Y", artifacts.get("psd_y_csv"), ("f_hz",), ("psd_um2_per_hz", "psd_px2_per_hz"), "Frequency [Hz]", "PSD", True, True),
        )
        if entry is not None
    ]

    hist_curve_entries_xy = [
        entry
        for entry in (
            _build_plot_entry("Histogram X curve", artifacts.get("hist_x_csv"), ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
            _build_plot_entry("Histogram Y curve", artifacts.get("hist_y_csv"), ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
        )
        if entry is not None
    ]

    # Create page counter for global page numbering (cover page is unnumbered)
    page_counter = PageCounter()

    with PdfPages(report_path) as pdf:
        if drag_mode:
            left_rows, right_rows = _drag_cover_rows(summary)
            _render_cover_page(
                pdf,
                title=f"DRAG Item Report: {summary.get('item_id')}",
                subtitle="Constant-velocity drag summary",
                left_rows=left_rows,
                right_rows=right_rows,
                eyebrow="DRAG Summary",
                page_counter=page_counter,
            )
            _render_drag_theory_page(pdf, page_counter=page_counter)
            _render_dual_table_page(
                pdf,
                "Drag Conditions, Provenance And QC",
                "Drag provenance and timing conditions",
                _drag_conditions_rows(summary),
                "Alignment and quality-control notes",
                _qc_rows(summary),
                page_counter=page_counter,
            )
            drag_diag = _build_image_entry("Drag diagnostic figure", artifacts.get("drag_diagnostic_png"))
            if drag_diag is not None:
                _render_image_pages(
                    pdf,
                    "Drag Diagnostic Figure",
                    [drag_diag],
                    layout="vertical",
                    items_per_page=1,
                    page_counter=page_counter,
                )
            _render_paginated_table(
                pdf,
                "Alignment Diagnostics Summary",
                ["Field", "Value"],
                _drag_alignment_rows(summary),
                rows_per_page=18,
                page_counter=page_counter,
            )
            windows_csv = artifacts.get("drag_windows_csv")
            if windows_csv and Path(windows_csv).is_file():
                _render_drag_windows_table_page(pdf, Path(windows_csv), page_counter=page_counter)
            trace_entry = _build_plot_entry(
                "Annotated drag trace",
                artifacts.get("drag_trace_annotated_csv"),
                ("video_time_s", "stage_time_aligned_s"),
                ("axis_px",),
                "Time [s]",
                "Axis position [px]",
                False,
                False,
            )
            if trace_entry is not None:
                _render_plot_pages(
                    pdf,
                    "Drag Windows And Annotated Trace",
                    [trace_entry],
                    layout="vertical",
                    items_per_page=1,
                    page_counter=page_counter,
                )
            if preview_paths:
                _render_preview_grid_page(pdf, preview_paths, page_counter=page_counter)
        else:
            # Cover page - no page number
            _render_cover_page(
                pdf,
                title=f"Item Report: {summary.get('item_id')}",
                subtitle="Item-level summary",
                left_rows=_identity_rows(summary),
                right_rows=_key_result_rows(summary),
                eyebrow="Scientific Summary",
                page_counter=page_counter,
            )
            _render_theory_page(
                pdf,
                page_counter=page_counter,
                physics_mode=(summary.get("metrics") or {}).get("mode"),
            )
            _render_dual_table_page(
                pdf,
                "Item Conditions And Quality Control",
                "Acquisition and analysis conditions",
                _conditions_rows(summary),
                "Quality control and report notes",
                _qc_rows(summary),
                page_counter=page_counter,
            )
            if preview_paths:
                _render_preview_grid_page(pdf, preview_paths, page_counter=page_counter)
            trajectory_csv = artifacts.get("trajectory_csv")
            if trajectory_csv and Path(trajectory_csv).is_file():
                _render_trajectory_heatmap_page(
                    pdf,
                    Path(trajectory_csv),
                    title="Trajectory",
                    page_counter=page_counter,
                )
            if psd_entries:
                _render_plot_pages(pdf, "Power Spectral Density", psd_entries,
                                  layout="vertical", items_per_page=2, page_counter=page_counter)
            if hist_curve_entries_xy:
                _render_plot_pages(pdf, "Histogram Curves", hist_curve_entries_xy,
                                  layout="vertical", items_per_page=2, page_counter=page_counter)
            _render_histogram_r_and_msd_page(
                pdf,
                artifacts.get("hist_r_csv"),
                artifacts.get("msd_csv"),
                page_counter=page_counter,
            )
        # Artifact appendix removed - file structure is consistent across analyses
        # and documented in the user manual
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

    # Create page counter for global page numbering (cover page is unnumbered)
    page_counter = PageCounter()

    with PdfPages(report_path) as pdf:
        # Cover page - no page number
        _render_cover_page(
            pdf,
            title=f"Batch Report: {batch_summary.get('batch_id') or 'OT batch'}",
            subtitle="Batch comparison summary",
            left_rows=_batch_overview_rows(batch_summary, items, successes, failures),
            right_rows=_batch_cover_key_rows(batch_summary),
            eyebrow="Batch Summary",
            page_counter=page_counter,
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
                page_counter=page_counter,
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
                page_counter=page_counter,
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
                _render_image_pages(pdf, title, image_entries, layout="grid", 
                                   items_per_page=2, page_counter=page_counter)

        for title, key, x_opts, y_opts, x_title, y_title, log_x, log_y in (
            ("PSD X Comparison", "psd_x_csv", ("f_hz",), ("psd_um2_per_hz", "psd_px2_per_hz"), "Frequency [Hz]", "PSD", True, True),
            ("PSD Y Comparison", "psd_y_csv", ("f_hz",), ("psd_um2_per_hz", "psd_px2_per_hz"), "Frequency [Hz]", "PSD", True, True),
            ("Histogram X Curves", "hist_x_csv", ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
            ("Histogram Y Curves", "hist_y_csv", ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
            ("Histogram R Curves", "hist_r_csv", ("bin_center_um", "bin_center_px"), ("count", "density"), "Bin center", "Counts", False, False),
        ):
            plot_entries = _collect_plot_entries(key, title, x_opts, y_opts, x_title, y_title, log_x, log_y)
            if plot_entries:
                _render_plot_pages(pdf, title, plot_entries, layout="grid", 
                                  items_per_page=2, page_counter=page_counter)

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
                page_counter=page_counter,
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
                page_counter=page_counter,
            )

    return report_path
