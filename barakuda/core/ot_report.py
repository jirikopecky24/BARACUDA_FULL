from __future__ import annotations

import csv
import json
import math
import textwrap
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
import numpy as np


PAGE_SIZE = (8.27, 11.69)  # A4 in inches
PAGE_MARGIN_LEFT = 0.08
PAGE_MARGIN_RIGHT = 0.08
PAGE_MARGIN_TOP = 0.12
PAGE_MARGIN_BOTTOM = 0.06

# Drag PDF inner pages: unified print-safe content frame (figure coordinates, origin bottom-left).
DRAG_CONTENT_LEFT = 0.105
DRAG_CONTENT_RIGHT = 0.895
DRAG_STACK_TOP = 0.802
DRAG_STACK_BOTTOM = 0.258
# Legend: below captions, clearly above page bottom (print-safe).
DRAG_LEGEND_FIG_Y = 0.190

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
    """Format number as 'X.XX × 10ⁿ' with Unicode superscript."""
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
        return f"{mantissa:.{sig_figs-1}f} × 10{sup}"
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
        return f"${mantissa:.{sig_figs-1}f}\\times10^{{{exp}}}$"
    except Exception:
        return f"{value:.{sig_figs}g}"


def _unicode_exp_superscript(exp: int) -> str:
    return str(exp).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))


def _fmt_pm_scientific_uncertainty(val: float, unc: float, unit: str = "", *, mantissa_decimals: int = 3) -> str:
    """
    (m ± u) × 10ⁿ with a single shared exponent (from |val|), Unicode × and superscripts.
    """
    if not math.isfinite(val) or not math.isfinite(unc) or unc <= 0:
        return _fmt_measure(val, unit)
    av = abs(val)
    if av == 0:
        return _fmt_measure(val, unit)
    exp_v = int(math.floor(math.log10(av)))
    scale = 10.0**exp_v
    mv = val / scale
    mu = unc / scale
    v_str = f"{mv:.{mantissa_decimals}f}".rstrip("0").rstrip(".")
    u_str = f"{mu:.2g}"
    sup = _unicode_exp_superscript(exp_v)
    core = f"({v_str} ± {u_str}) × 10{sup}"
    if unit:
        return f"{core} {_fmt_unit(unit)}"
    return core


def _fmt_measure_with_uncertainty(value: Any, uncertainty: Any, unit: str = "") -> str:
    """Format value ± uncertainty; scientific form uses Unicode × and superscript exponents."""
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
        abs_val = abs(val)
        if abs_val > 0 and (abs_val < 0.01 or abs_val >= 1000):
            formatted = _fmt_scientific_text(val, sig_figs=3)
            if unit:
                return f"{formatted} {_fmt_unit(unit)}"
            return formatted
        return _fmt_measure(val, unit)

    try:
        unc_exp = int(math.floor(math.log10(abs(unc))))
        precision = max(0, min(10, -unc_exp + 1))
    except (ValueError, OverflowError):
        precision = 2

    # Decide scientific form from the true magnitude; rounding tiny values first can yield 0.0 (e.g. round(1e-13,10)==0).
    abs_val = abs(val)
    if abs_val > 0 and (abs_val < 0.01 or abs_val >= 1000):
        try:
            return _fmt_pm_scientific_uncertainty(val, unc, unit, mantissa_decimals=min(4, precision + 2))
        except (ValueError, OverflowError):
            pass

    val_rounded = round(val, precision)
    unc_rounded = round(unc, precision)
    if abs(val) > 0 and val_rounded == 0.0:
        try:
            return _fmt_pm_scientific_uncertainty(val, unc, unit, mantissa_decimals=4)
        except (ValueError, OverflowError):
            pass

    val_str = f"{val_rounded:.{precision}f}"
    unc_str = f"{unc_rounded:.{precision}f}"
    if unit:
        return f"{val_str} ± {unc_str} {_fmt_unit(unit)}"
    return f"{val_str} ± {unc_str}"


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


def _cover_cell_text(value: Any, *, max_chars: int = 44) -> str:
    """Single-line or gently wrapped text for cover tables; avoids over-wrapping short fields."""
    if value is None:
        return "n/a"
    text = str(value).strip()
    if not text:
        return "n/a"
    if len(text) <= max_chars:
        return text
    w = max(28, min(max_chars, 52))
    return textwrap.fill(text, width=w, break_long_words=False, break_on_hyphens=False)


def _is_drag_report(summary: dict[str, Any]) -> bool:
    metrics = summary.get("metrics") or {}
    diagnostics = summary.get("diagnostics") or {}
    source_kind = str(diagnostics.get("report_source_kind") or "").strip().lower()
    analysis_type = str(diagnostics.get("analysis_type") or "").strip().lower()
    mode = str(metrics.get("mode") or "").strip().lower()
    return source_kind == "drag_summary" or analysis_type == "drag" or mode in {"drag", "dragging"}


def _relaxation_time_from_fc_hz(
    fc_hz: Any,
    fc_hz_se: Any = None,
) -> tuple[float | None, float | None]:
    """Relaxation time τ = 1/(2π f_c); σ_τ = σ_fc / (2π f_c²) for small σ_fc."""
    fc = _parse_float(fc_hz)
    if fc is None or fc <= 0:
        return None, None
    tau = 1.0 / (2.0 * math.pi * fc)
    sfc = _parse_float(fc_hz_se)
    if sfc is None or sfc < 0:
        return tau, None
    sigma_tau = sfc / (2.0 * math.pi * fc * fc)
    return tau, sigma_tau


def _relative_lorentz_rmse(fit_block: dict[str, Any]) -> float | None:
    """Dimensionless Lorentz-fit quality: RMSE / |A| from PSD fit parameters."""
    rmse = _parse_float(fit_block.get("rmse"))
    A = _parse_float(fit_block.get("A"))
    if rmse is None or A is None or abs(A) < 1e-30:
        return None
    return abs(rmse / A)


def _ingest_brownian_psd_lorentz_metrics(
    post_json: dict[str, Any] | None,
    psd_fit_disk: dict[str, Any] | None,
    diagnostics: dict[str, Any],
) -> None:
    """Populate relative PSD Lorentz RMSE metrics from postprocess and/or *_psd_fit.json."""
    lx: dict[str, Any] = {}
    ly: dict[str, Any] = {}
    if post_json:
        phys = ((post_json.get("summary") or {}).get("physics") or {})
        lor = phys.get("lorentz_fit") or {}
        lx = lor.get("x") or {}
        ly = lor.get("y") or {}
    if psd_fit_disk:
        if not lx:
            lx = psd_fit_disk.get("fit_x") or {}
        if not ly:
            ly = psd_fit_disk.get("fit_y") or {}
    rx = _relative_lorentz_rmse(lx)
    ry = _relative_lorentz_rmse(ly)
    if rx is not None:
        diagnostics["psd_lorentz_rel_rmse_x"] = rx
    if ry is not None:
        diagnostics["psd_lorentz_rel_rmse_y"] = ry


def _compute_brownian_qc_verdicts(summary: dict[str, Any]) -> dict[str, Any]:
    """
    Conservative Brownian QC labels derived only from pipeline outputs.
    Thresholds are explicit and documented in the returned notes string.
    """
    diagnostics = summary.get("diagnostics") or {}
    status_l = str(summary.get("status") or "").strip().lower()
    hard_fail_status = status_l in ("error", "failed", "fail", "stopped", "cancelled")

    tvp = diagnostics.get("timestamp_validation_pass")
    if tvp is True:
        timing = "pass"
    elif tvp is False:
        timing = "fail"
    else:
        timing = "warning"

    lf = _parse_float(diagnostics.get("lost_fraction"))
    if lf is None:
        tracking = "warning"
    elif lf <= 0.01:
        tracking = "pass"
    elif lf <= 0.05:
        tracking = "warning"
    else:
        tracking = "fail"

    rmx = diagnostics.get("psd_lorentz_rel_rmse_x")
    rmy = diagnostics.get("psd_lorentz_rel_rmse_y")
    kappa_unit_ok = diagnostics.get("kappa_unit_check_pass")

    if kappa_unit_ok is False:
        psd_fit = "fail"
    elif rmx is not None and rmy is not None:
        m = max(float(rmx), float(rmy))
        if m <= 0.02:
            psd_fit = "pass"
        elif m <= 0.08:
            psd_fit = "warning"
        else:
            psd_fit = "fail"
    else:
        psd_fit = "warning"

    notes = (
        "Timing: timestamp_validation_pass. "
        "Tracking: lost_fraction (≤1% pass, ≤5% warn). "
        "PSD: Lorentz RMSE/|A| tiers 2%/8%; fail if κ unit check fails. "
        "Missing Lorentz metrics → PSD warning."
    )

    if summary.get("error") or hard_fail_status:
        overall = "reject"
    elif "fail" in (timing, tracking, psd_fit):
        overall = "reject"
    elif "warning" in (timing, tracking, psd_fit):
        overall = "caution"
    else:
        overall = "usable"

    if diagnostics.get("anisotropy_eta_pass") is False and overall == "usable":
        overall = "caution"
    if summary.get("warnings") and overall == "usable":
        overall = "caution"

    return {
        "timing": timing,
        "tracking": tracking,
        "psd_fit": psd_fit,
        "overall": overall,
        "notes": notes,
    }


def _finalize_brownian_report_augmentation(summary: dict[str, Any]) -> None:
    if _is_drag_report(summary):
        return
    diagnostics = summary.setdefault("diagnostics", {})
    metrics = summary.get("metrics") or {}

    tx, stx = _relaxation_time_from_fc_hz(diagnostics.get("fc_x_hz"), diagnostics.get("fc_x_hz_se"))
    ty, sty = _relaxation_time_from_fc_hz(diagnostics.get("fc_y_hz"), diagnostics.get("fc_y_hz_se"))
    diagnostics["tau_x_s"] = tx
    diagnostics["tau_y_s"] = ty
    diagnostics["tau_x_s_se"] = stx
    diagnostics["tau_y_s_se"] = sty

    kx = _parse_float(metrics.get("kappa_x_pn_per_um"))
    ky = _parse_float(metrics.get("kappa_y_pn_per_um"))
    if kx is not None and ky is not None and ky != 0:
        diagnostics["trap_kappa_ratio_xy"] = kx / ky

    fcx = _parse_float(diagnostics.get("fc_x_hz"))
    fcy = _parse_float(diagnostics.get("fc_y_hz"))
    if fcx is not None and fcy is not None and fcy != 0:
        diagnostics["trap_fc_ratio_xy"] = fcx / fcy

    diagnostics["brownian_qc"] = _compute_brownian_qc_verdicts(summary)


def _fmt_brownian_value_pm_se(value: Any, se: Any, unit: str, sig_figs: int = 3) -> str:
    """Format primary Brownian result with pipeline SE when present; never fabricates uncertainty."""
    v = _parse_float(value)
    if v is None:
        return "n/a"
    u = _parse_float(se)
    if u is None:
        # Diffusion (m²/s) and similar: always compact scientific on cover when tiny/large.
        if unit == "m^2/s" and abs(v) > 0 and (abs(v) < 1e-6 or abs(v) >= 1000):
            return f"{_fmt_scientific_text(v, sig_figs=sig_figs)} {_fmt_unit(unit)}"
        return _fmt_key_result(v, unit, sig_figs=sig_figs)
    return _fmt_measure_with_uncertainty(v, u, unit)


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
    psd_fit_json = _load_json(dir_audit / f"{base_name}_psd_fit.json" if dir_audit else None)
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
        kuc = calibration_json.get("kappa_unit_check") or {}
        diagnostics["kappa_unit_check_pass"] = kuc.get("pass")
        diagnostics["anisotropy_eta_pass"] = anisotropy.get("pass")

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
        diagnostics["actual_travel_um"] = _parse_float(drag_summary_json.get("actual_travel_um"))
        diagnostics["actual_speed_um_s"] = _parse_float(drag_summary_json.get("actual_speed_um_s"))
        diagnostics["eta_pa_s"] = _parse_float(drag_summary_json.get("eta_pa_s"))
        diagnostics["analysis_status"] = drag_summary_json.get("analysis_status")
        diagnostics["physics_status"] = drag_summary_json.get("physics_status")
        diagnostics["drag_physics_confidence"] = drag_summary_json.get("drag_physics_confidence")
        diagnostics["drag_physics_warning"] = drag_summary_json.get("drag_physics_warning")
        diagnostics["baseline_robustness_flag"] = drag_summary_json.get("baseline_robustness_flag")
        diagnostics["baseline_robustness_message"] = drag_summary_json.get("baseline_robustness_message")
        diagnostics["onset_robustness_flag"] = drag_summary_json.get("onset_robustness_flag")
        diagnostics["onset_robustness_message"] = drag_summary_json.get("onset_robustness_message")
        diagnostics["kinematics_robustness_flag"] = drag_summary_json.get("kinematics_robustness_flag")
        diagnostics["kinematics_robustness_message"] = drag_summary_json.get("kinematics_robustness_message")
        diagnostics["drag_validation_gate"] = drag_summary_json.get("drag_validation_gate")
        diagnostics["drag_validation_reason"] = drag_summary_json.get("drag_validation_reason")
        diagnostics["t_first_s"] = _parse_float(drag_summary_json.get("t_first_s"))
        diagnostics["t_last_s"] = _parse_float(drag_summary_json.get("t_last_s"))
        diagnostics["elapsed_time_s"] = _parse_float(drag_summary_json.get("elapsed_time_s"))
        diagnostics["expected_stage_start_video_s"] = _parse_float(drag_summary_json.get("expected_stage_start_video_s"))
        diagnostics["expected_stage_stop_video_s"] = _parse_float(drag_summary_json.get("expected_stage_stop_video_s"))
        diagnostics["detected_stage_start_video_s"] = _parse_float(drag_summary_json.get("detected_stage_start_video_s"))
        diagnostics["detected_stage_stop_video_s"] = _parse_float(drag_summary_json.get("detected_stage_stop_video_s"))
        diagnostics["stage_video_start_delta_s"] = _parse_float(drag_summary_json.get("stage_video_start_delta_s"))
        diagnostics["stage_video_stop_delta_s"] = _parse_float(drag_summary_json.get("stage_video_stop_delta_s"))
        diagnostics["alignment_sanity_flag"] = drag_summary_json.get("alignment_sanity_flag")
        diagnostics["alignment_sanity_message"] = drag_summary_json.get("alignment_sanity_message")
        diagnostics["drag_anchor_mode"] = drag_summary_json.get("drag_anchor_mode")
        diagnostics["drag_anchor_mode_requested"] = drag_summary_json.get("drag_anchor_mode_requested")
        diagnostics["drag_anchor_mode_effective"] = drag_summary_json.get(
            "drag_anchor_mode_effective"
        ) or drag_summary_json.get("drag_anchor_mode")
        diagnostics["primary_timing_source_for_windows"] = drag_summary_json.get(
            "primary_timing_source_for_windows"
        )
        diagnostics["motion_timing_primary_source"] = drag_summary_json.get("motion_timing_primary_source")
        diagnostics["detected_onset_video_s"] = _parse_float(drag_summary_json.get("detected_onset_video_s"))
        diagnostics["detected_onset_diagnostic_only"] = drag_summary_json.get("detected_onset_diagnostic_only")
        diagnostics["detected_onset_consistency_flag"] = drag_summary_json.get(
            "detected_onset_consistency_flag"
        )
        diagnostics["detected_onset_consistency_message"] = drag_summary_json.get(
            "detected_onset_consistency_message"
        )
        diagnostics["stage_anchor_confidence"] = drag_summary_json.get("stage_anchor_confidence")
        diagnostics["stage_anchor_reason"] = drag_summary_json.get("stage_anchor_reason")
        diagnostics["physics_primary_gate"] = drag_summary_json.get("physics_primary_gate")
        diagnostics["detection_qc_gate"] = drag_summary_json.get("detection_qc_gate")
        diagnostics["final_drag_verdict"] = drag_summary_json.get("final_drag_verdict")
        diagnostics["final_drag_reason"] = drag_summary_json.get("final_drag_reason")
        diagnostics["stage_validated_physics_acceptable"] = drag_summary_json.get(
            "stage_validated_physics_acceptable"
        )
        diagnostics["detected_onset_qc_only"] = drag_summary_json.get("detected_onset_qc_only")
        diagnostics["detected_onset_veto_applied"] = drag_summary_json.get("detected_onset_veto_applied")
        diagnostics["window_clipping_applied"] = drag_summary_json.get("window_clipping_applied")
        diagnostics["window_clipping_message"] = drag_summary_json.get("window_clipping_message")
        diagnostics["baseline_window_original_start_s"] = _parse_float(
            drag_summary_json.get("baseline_window_original_start_s")
        )
        diagnostics["baseline_window_original_end_s"] = _parse_float(
            drag_summary_json.get("baseline_window_original_end_s")
        )
        diagnostics["steady_window_original_start_s"] = _parse_float(
            drag_summary_json.get("steady_window_original_start_s")
        )
        diagnostics["steady_window_original_end_s"] = _parse_float(
            drag_summary_json.get("steady_window_original_end_s")
        )
        diagnostics["baseline_window_clipped_start_s"] = _parse_float(
            drag_summary_json.get("baseline_window_clipped_start_s")
        )
        diagnostics["baseline_window_clipped_end_s"] = _parse_float(
            drag_summary_json.get("baseline_window_clipped_end_s")
        )
        diagnostics["steady_window_clipped_start_s"] = _parse_float(
            drag_summary_json.get("steady_window_clipped_start_s")
        )
        diagnostics["steady_window_clipped_end_s"] = _parse_float(
            drag_summary_json.get("steady_window_clipped_end_s")
        )
        diagnostics["baseline_strategy_primary"] = drag_summary_json.get("baseline_strategy_primary")
        diagnostics["baseline_strategy_alt"] = drag_summary_json.get("baseline_strategy_alt")
        diagnostics["baseline_position_primary_px"] = _parse_float(drag_summary_json.get("baseline_position_primary_px"))
        diagnostics["baseline_position_primary_um"] = _parse_float(drag_summary_json.get("baseline_position_primary_um"))
        diagnostics["baseline_position_alt_px"] = _parse_float(drag_summary_json.get("baseline_position_alt_px"))
        diagnostics["baseline_position_alt_um"] = _parse_float(drag_summary_json.get("baseline_position_alt_um"))
        diagnostics["offset_primary_um"] = _parse_float(drag_summary_json.get("offset_primary_um"))
        diagnostics["offset_alt_um"] = _parse_float(drag_summary_json.get("offset_alt_um"))
        diagnostics["eta_primary_pa_s"] = _parse_float(drag_summary_json.get("eta_primary_pa_s"))
        diagnostics["eta_alt_pa_s"] = _parse_float(drag_summary_json.get("eta_alt_pa_s"))
        diagnostics["baseline_strategy_difference_ratio"] = _parse_float(
            drag_summary_json.get("baseline_strategy_difference_ratio")
        )
        diagnostics["relaxed_onset_used"] = drag_summary_json.get("relaxed_onset_used")
        diagnostics["competing_durable_candidates_count"] = _parse_float(
            drag_summary_json.get("competing_durable_candidates_count")
        )
        diagnostics["onset_candidate_density"] = _parse_float(drag_summary_json.get("onset_candidate_density"))
        diagnostics["speed_stage_json"] = _parse_float(drag_summary_json.get("speed_stage_json"))
        diagnostics["speed_trace_derived"] = _parse_float(drag_summary_json.get("speed_trace_derived"))
        diagnostics["speed_used_for_physics"] = _parse_float(drag_summary_json.get("speed_used_for_physics"))
        diagnostics["speed_consistency_error_pct"] = _parse_float(drag_summary_json.get("speed_consistency_error_pct"))
        diagnostics["expected_offset_if_eta_1mPas_um"] = _parse_float(
            drag_summary_json.get("expected_offset_if_eta_1mPas_um")
        )
        diagnostics["expected_offset_if_eta_from_baseline_um"] = _parse_float(
            drag_summary_json.get("expected_offset_if_eta_from_baseline_um")
        )
        diagnostics["measured_offset_um"] = _parse_float(drag_summary_json.get("measured_offset_um"))
        diagnostics["offset_underestimation_ratio_vs_water"] = _parse_float(
            drag_summary_json.get("offset_underestimation_ratio_vs_water")
        )
        diagnostics["offset_underestimation_ratio_vs_baseline"] = _parse_float(
            drag_summary_json.get("offset_underestimation_ratio_vs_baseline")
        )
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
    prov_report_val = str(provenance_cfg.get("current_drag_report_path") or "")
    if prov_report_val.lower().endswith(".pdf"):
        diagnostics["current_drag_report_path"] = prov_report_val
    if diagnostics.get("current_drag_report_path") is None and diagnostics.get("current_drag_summary_json_path"):
        diagnostics["current_drag_report_path"] = diagnostics.get("current_drag_summary_json_path")
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
        diagnostics["onset_candidate_density"] = _parse_float(drag_alignment_json.get("onset_candidate_density"))
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

    _ingest_brownian_psd_lorentz_metrics(post_json, psd_fit_json, diagnostics)

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

    summary_out: dict[str, Any] = {
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
        "run_json": run_json or {},
        "artifacts": artifacts,
    }
    _finalize_brownian_report_augmentation(summary_out)
    return summary_out


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
            ("Drag", "Drag physics confidence", diagnostics.get("drag_physics_confidence"), "", "drag_physics_confidence"),
            ("Drag", "Drag validation gate", diagnostics.get("drag_validation_gate"), "", "drag_validation_gate"),
            ("Drag", "Drag validation reason", diagnostics.get("drag_validation_reason"), "", "drag_validation_reason"),
            ("Drag", "Alignment sanity flag", diagnostics.get("alignment_sanity_flag"), "", "alignment_sanity_flag"),
            ("Drag", "Alignment sanity message", diagnostics.get("alignment_sanity_message"), "", "alignment_sanity_message"),
            ("Drag", "Drag anchor mode", diagnostics.get("drag_anchor_mode"), "", "drag_anchor_mode"),
            (
                "Drag",
                "Drag anchor (requested)",
                diagnostics.get("drag_anchor_mode_requested"),
                "",
                "drag_anchor_mode_requested",
            ),
            (
                "Drag",
                "Drag anchor (effective)",
                diagnostics.get("drag_anchor_mode_effective"),
                "",
                "drag_anchor_mode_effective",
            ),
            (
                "Drag",
                "Primary timing source for windows",
                diagnostics.get("primary_timing_source_for_windows"),
                "",
                "primary_timing_source_for_windows",
            ),
            (
                "Drag",
                "Motion timing primary source",
                diagnostics.get("motion_timing_primary_source"),
                "",
                "motion_timing_primary_source",
            ),
            (
                "Drag",
                "Detected onset (diagnostic, s)",
                diagnostics.get("detected_onset_video_s"),
                "s",
                "detected_onset_video_s",
            ),
            (
                "Drag",
                "Detected onset diagnostic-only flag",
                diagnostics.get("detected_onset_diagnostic_only"),
                "",
                "detected_onset_diagnostic_only",
            ),
            (
                "Drag",
                "Detected onset consistency flag",
                diagnostics.get("detected_onset_consistency_flag"),
                "",
                "detected_onset_consistency_flag",
            ),
            (
                "Drag",
                "Detected onset consistency message",
                diagnostics.get("detected_onset_consistency_message"),
                "",
                "detected_onset_consistency_message",
            ),
            ("Drag", "Stage anchor confidence", diagnostics.get("stage_anchor_confidence"), "", "stage_anchor_confidence"),
            ("Drag", "Stage anchor reason", diagnostics.get("stage_anchor_reason"), "", "stage_anchor_reason"),
            ("Drag", "Physics primary gate", diagnostics.get("physics_primary_gate"), "", "physics_primary_gate"),
            ("Drag", "Detection QC gate", diagnostics.get("detection_qc_gate"), "", "detection_qc_gate"),
            ("Drag", "Final drag verdict", diagnostics.get("final_drag_verdict"), "", "final_drag_verdict"),
            ("Drag", "Final drag reason", diagnostics.get("final_drag_reason"), "", "final_drag_reason"),
            (
                "Drag",
                "Stage validated physics acceptable",
                diagnostics.get("stage_validated_physics_acceptable"),
                "",
                "stage_validated_physics_acceptable",
            ),
            ("Drag", "Detected onset QC only", diagnostics.get("detected_onset_qc_only"), "", "detected_onset_qc_only"),
            (
                "Drag",
                "Detected onset veto applied",
                diagnostics.get("detected_onset_veto_applied"),
                "",
                "detected_onset_veto_applied",
            ),
            ("Drag", "Expected stage start in video", diagnostics.get("expected_stage_start_video_s"), "s", "expected_stage_start_video_s"),
            ("Drag", "Expected stage stop in video", diagnostics.get("expected_stage_stop_video_s"), "s", "expected_stage_stop_video_s"),
            ("Drag", "Detected stage start in video", diagnostics.get("detected_stage_start_video_s"), "s", "detected_stage_start_video_s"),
            ("Drag", "Detected stage stop in video", diagnostics.get("detected_stage_stop_video_s"), "s", "detected_stage_stop_video_s"),
            ("Drag", "Stage-video start delta", diagnostics.get("stage_video_start_delta_s"), "s", "stage_video_start_delta_s"),
            ("Drag", "Stage-video stop delta", diagnostics.get("stage_video_stop_delta_s"), "s", "stage_video_stop_delta_s"),
            ("Drag", "Baseline strategy primary", diagnostics.get("baseline_strategy_primary"), "", "baseline_strategy_primary"),
            ("Drag", "Baseline strategy alt", diagnostics.get("baseline_strategy_alt"), "", "baseline_strategy_alt"),
            ("Drag", "Offset primary", diagnostics.get("offset_primary_um"), "um", "offset_primary_um"),
            ("Drag", "Offset alt", diagnostics.get("offset_alt_um"), "um", "offset_alt_um"),
            ("Drag", "Eta primary", diagnostics.get("eta_primary_pa_s"), "Pa*s", "eta_primary_pa_s"),
            ("Drag", "Eta alt", diagnostics.get("eta_alt_pa_s"), "Pa*s", "eta_alt_pa_s"),
            ("Drag", "Baseline strategy difference ratio", diagnostics.get("baseline_strategy_difference_ratio"), "", "baseline_strategy_difference_ratio"),
            ("Drag", "Onset confidence class", diagnostics.get("onset_confidence_class"), "", "onset_confidence_class"),
            ("Drag", "Competing durable candidates", diagnostics.get("competing_durable_candidates_count"), "", "competing_durable_candidates_count"),
            ("Drag", "Onset candidate density", diagnostics.get("onset_candidate_density"), "", "onset_candidate_density"),
            ("Drag", "Speed stage json", diagnostics.get("speed_stage_json"), "um/s", "speed_stage_json"),
            ("Drag", "Speed trace derived", diagnostics.get("speed_trace_derived"), "um/s", "speed_trace_derived"),
            ("Drag", "Speed used for physics", diagnostics.get("speed_used_for_physics"), "um/s", "speed_used_for_physics"),
            ("Drag", "Speed consistency error", diagnostics.get("speed_consistency_error_pct"), "%", "speed_consistency_error_pct"),
            ("Provenance", "Current drag input", diagnostics.get("current_drag_input_path"), "", "current_drag_input_path"),
            ("Provenance", "Current drag output root", diagnostics.get("current_drag_output_root"), "", "current_drag_output_root"),
            ("Provenance", "Current drag report path", diagnostics.get("current_drag_report_path"), "", "current_drag_report_path"),
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
    def _parse_iso(value: Any) -> datetime | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    def _resolve_acquisition_dt() -> tuple[str, str]:
        analysis_dir = summary.get("analysis_dir")
        if analysis_dir:
            item_root = Path(str(analysis_dir)).parent
            meta_path = item_root / "raw" / "video_meta.json"
            if meta_path.is_file():
                try:
                    payload = json.loads(meta_path.read_text(encoding="utf-8"))
                    ts = _parse_iso(payload.get("timestamp"))
                    if ts is not None:
                        return ts.isoformat(timespec="seconds"), "video_meta.timestamp"
                except Exception:
                    pass
                try:
                    ts = datetime.fromtimestamp(meta_path.stat().st_mtime)
                    return ts.isoformat(timespec="seconds"), "video_meta.mtime_fallback"
                except Exception:
                    pass
            try:
                raw_name = Path(str(summary.get("source_input_path") or "")).name
                raw_local = (item_root / "raw" / raw_name) if raw_name else None
                if raw_local is not None and raw_local.is_file():
                    ts = datetime.fromtimestamp(raw_local.stat().st_mtime)
                    return ts.isoformat(timespec="seconds"), "raw_file.mtime_fallback"
            except Exception:
                pass
        return "n/a", "not_available"

    acq_dt, _acq_src = _resolve_acquisition_dt()
    processed_raw = summary.get("created_at") or datetime.now().isoformat(timespec="seconds")
    return [
        ["Item", _cover_cell_text(summary.get("item_id"), max_chars=40)],
        ["Status", _fmt_status(summary.get("status"))],
        ["Acquisition date/time", _cover_cell_text(acq_dt, max_chars=44)],
        ["Processed / report generated", _cover_cell_text(processed_raw, max_chars=44)],
    ]


def _drag_cover_source_file_display(summary: dict[str, Any]) -> str:
    """Prefer a real filename over placeholder `source_input_path` (e.g. CLI tests passing `x`)."""
    diagnostics = summary.get("diagnostics") or {}
    run_json = summary.get("run_json") or {}
    candidates = [
        summary.get("original_input_path"),
        summary.get("resolved_video_path"),
        diagnostics.get("current_drag_input_path"),
        run_json.get("input_path"),
        summary.get("source_input_path"),
    ]
    best_path = ""
    for c in candidates:
        if not c:
            continue
        s = str(c).strip()
        if not s or s.lower() in {"x", "n/a", "-", "none"}:
            continue
        if len(s) > len(best_path):
            best_path = s
    if not best_path:
        return "n/a"
    pn = Path(best_path)
    name = pn.name
    if len(name) <= 2 and len(str(pn)) > 4:
        return _wrap(str(pn), 56)
    return _wrap(name, 56)


def _drag_cover_rows(summary: dict[str, Any]) -> tuple[list[list[str]], list[list[str]]]:
    diagnostics = summary.get("diagnostics") or {}
    metrics = summary.get("metrics") or {}
    source_name = _drag_cover_source_file_display(summary)
    gate = str(diagnostics.get("drag_validation_gate") or "").strip().lower()
    final_verdict = str(diagnostics.get("final_drag_verdict") or "").strip().lower()
    physics_status = str(diagnostics.get("physics_status") or "").strip().lower()
    status_value = str(summary.get("status") or "")
    if final_verdict == "fail" or gate == "fail" or "fail" in physics_status:
        status_value = "fail"
    elif final_verdict in {"suspect", "pass_with_warnings"} or gate == "suspect" or "suspect" in physics_status:
        status_value = "suspect"

    def _f_pn(val: Any) -> str:
        v = _parse_float(val)
        if v is None:
            return "n/a"
        return f"{v * 1e12:.3f} pN"

    def _f_mpas(val: Any) -> str:
        v = _parse_float(val)
        if v is None:
            return "n/a"
        return f"{v * 1e3:.3f} mPa·s"

    def _f_um(val: Any) -> str:
        v = _parse_float(val)
        if v is None:
            return "n/a"
        return f"{v:.4f} µm"

    def _f_um_s(val: Any) -> str:
        v = _parse_float(val)
        if v is None:
            return "n/a"
        return f"{v:.2f} µm/s"

    def _f_kappa(val: Any) -> str:
        v = _parse_float(val)
        if v is None:
            return "n/a"
        return f"{v:.2f} pN/µm"

    rows = [
        ["Item", _wrap(summary.get("item_id"), 56)],
        ["Status", _fmt_status(status_value)],
        ["Run ID", _wrap(summary.get("run_id"), 56)],
        ["Source file", _wrap(source_name, 56)],
        ["Drag force", _f_pn(diagnostics.get("drag_force_n"))],
        ["Viscosity", _f_mpas(diagnostics.get("eta_pa_s"))],
        ["Drag stiffness", _f_kappa(metrics.get("kappa_drag_pn_per_um"))],
        ["Actual speed", _f_um_s(diagnostics.get("actual_speed_um_s"))],
        ["Absolute offset", _f_um(diagnostics.get("offset_um"))],
        ["Alignment status", _wrap(diagnostics.get("alignment_status"), 56)],
        ["Physics status", _wrap(diagnostics.get("physics_status"), 56)],
        ["Primary physics gate", _wrap(diagnostics.get("physics_primary_gate"), 56)],
        ["Detection QC gate", _wrap(diagnostics.get("detection_qc_gate"), 56)],
        ["Final drag verdict", _wrap(diagnostics.get("final_drag_verdict"), 56)],
    ]
    return rows[:6], rows[6:]


def _path_entries_for_item(summary: dict[str, Any]) -> list[tuple[str, list[str]]]:
    return [
        ("Source input", _wrap_path_segments(summary.get("source_input_path"), 88)),
        ("Output root", _wrap_path_segments(summary.get("output_root"), 88)),
        ("Analysis directory", _wrap_path_segments(summary.get("analysis_dir"), 88)),
    ]


def _key_result_rows(summary: dict[str, Any]) -> list[list[str]]:
    if _is_drag_report(summary):
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

    metrics = summary.get("metrics") or {}
    diagnostics = summary.get("diagnostics") or {}
    def _fmt_display_converted(
        value: Any,
        se: Any,
        *,
        scale: float,
        unit: str,
        max_decimals: int | None = None,
    ) -> str:
        v = _parse_float(value)
        if v is None:
            return "n/a"
        u = _parse_float(se)
        v_scaled = v * scale
        u_scaled = (u * scale) if u is not None else None
        if max_decimals is not None and math.isfinite(v_scaled):
            if u_scaled is not None and math.isfinite(u_scaled) and u_scaled > 0:
                try:
                    unc_exp = int(math.floor(math.log10(abs(u_scaled))))
                    precision = max(0, min(max_decimals, -unc_exp + 1))
                except Exception:
                    precision = max_decimals
                v_text = f"{v_scaled:.{precision}f}"
                u_text = f"{u_scaled:.{precision}f}"
                return f"{v_text} ± {u_text} {_fmt_unit(unit)}"
            v_text = f"{v_scaled:.{max_decimals}f}"
            return f"{v_text} {_fmt_unit(unit)}"
        return _fmt_measure_with_uncertainty(v_scaled, u_scaled, unit)

    rows: list[list[str]] = [
        [
            "Mean viscosity",
            _fmt_display_converted(
                metrics.get("eta_mean_pa_s"),
                metrics.get("eta_mean_pa_s_se"),
                scale=1e3,
                unit="mPa*s",
            ),
        ],
        [
            "Diffusion coefficient",
            _fmt_display_converted(
                metrics.get("D_m2_s"),
                metrics.get("D_m2_s_se"),
                scale=1e12,
                unit="um^2/s",
            ),
        ],
        [
            "Trap stiffness X",
            _fmt_brownian_value_pm_se(
                metrics.get("kappa_x_pn_per_um"),
                metrics.get("kappa_x_pn_per_um_se"),
                "pN/um",
            ),
        ],
        [
            "Trap stiffness Y",
            _fmt_brownian_value_pm_se(
                metrics.get("kappa_y_pn_per_um"),
                metrics.get("kappa_y_pn_per_um_se"),
                "pN/um",
            ),
        ],
        [
            "Corner frequency X",
            _fmt_brownian_value_pm_se(
                diagnostics.get("fc_x_hz"),
                diagnostics.get("fc_x_hz_se"),
                "Hz",
            ),
        ],
        [
            "Corner frequency Y",
            _fmt_brownian_value_pm_se(
                diagnostics.get("fc_y_hz"),
                diagnostics.get("fc_y_hz_se"),
                "Hz",
            ),
        ],
        [
            "Relaxation time X",
            _fmt_display_converted(
                diagnostics.get("tau_x_s"),
                diagnostics.get("tau_x_s_se"),
                scale=1e3,
                unit="ms",
                max_decimals=3,
            ),
        ],
        [
            "Relaxation time Y",
            _fmt_display_converted(
                diagnostics.get("tau_y_s"),
                diagnostics.get("tau_y_s_se"),
                scale=1e3,
                unit="ms",
                max_decimals=3,
            ),
        ],
    ]
    kr = diagnostics.get("trap_kappa_ratio_xy")
    if kr is not None and math.isfinite(float(kr)):
        rows.append(["Trap anisotropy (\u03bax/\u03bay)", _fmt_value(float(kr))])
    fr = diagnostics.get("trap_fc_ratio_xy")
    if fr is not None and math.isfinite(float(fr)):
        rows.append(["Corner-frequency ratio (fc,x/fc,y)", _fmt_value(float(fr))])

    bqc = diagnostics.get("brownian_qc") or {}
    if bqc:
        rows.extend(
            [
                ["QC: timing", str(bqc.get("timing") or "n/a")],
                ["QC: tracking", str(bqc.get("tracking") or "n/a")],
                ["QC: PSD fit", str(bqc.get("psd_fit") or "n/a")],
                ["Overall Brownian QC", str(bqc.get("overall") or "n/a")],
            ]
        )
    return rows


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
    cfg = ((summary.get("run_json") or {}).get("config") or {})
    tracking_cfg = cfg.get("tracking") or {}
    start_frame = tracking_cfg.get("start_frame")
    end_frame = tracking_cfg.get("end_frame")
    rows = [
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
        ["Tracking method", _wrap(tracking_cfg.get("method"), 50)],
    ]
    if start_frame is not None and end_frame is not None:
        rows.append(["Frame range used", _wrap(f"{start_frame} -> {end_frame}", 50)])
    for label, key in (
        ("Selected calibration source", "selected_calibration_path"),
        ("Selected trajectory source", "selected_trajectory_path"),
        ("Selected timestamps source", "selected_timestamps_path"),
    ):
        val = diagnostics.get(key)
        if val is not None and str(val).strip() and str(val).strip().lower() != "n/a":
            rows.append([label, _wrap(val, 50)])
    return rows


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
        ["Drag validation gate", _wrap(diagnostics.get("drag_validation_gate"), 52)],
        ["Drag validation reason", _wrap(diagnostics.get("drag_validation_reason"), 52)],
        ["Video first timestamp [s]", _fmt_value(diagnostics.get("t_first_s"))],
        ["Video last timestamp [s]", _fmt_value(diagnostics.get("t_last_s"))],
        ["Video elapsed [s]", _fmt_value(diagnostics.get("elapsed_time_s"))],
        ["Expected stage start in video [s]", _fmt_value(diagnostics.get("expected_stage_start_video_s"))],
        ["Expected stage stop in video [s]", _fmt_value(diagnostics.get("expected_stage_stop_video_s"))],
        ["Detected stage start in video [s]", _fmt_value(diagnostics.get("detected_stage_start_video_s"))],
        ["Detected stage stop in video [s]", _fmt_value(diagnostics.get("detected_stage_stop_video_s"))],
        ["Stage-video start delta [s]", _fmt_value(diagnostics.get("stage_video_start_delta_s"))],
        ["Stage-video stop delta [s]", _fmt_value(diagnostics.get("stage_video_stop_delta_s"))],
        ["Alignment sanity flag", _fmt_value(diagnostics.get("alignment_sanity_flag"))],
        ["Alignment sanity message", _wrap(diagnostics.get("alignment_sanity_message"), 52)],
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


def _drag_provenance_rows(summary: dict[str, Any]) -> list[list[str]]:
    diagnostics = summary.get("diagnostics") or {}
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
    ]


def _drag_timing_alignment_rows(summary: dict[str, Any]) -> list[list[str]]:
    diagnostics = summary.get("diagnostics") or {}
    t_first = diagnostics.get("t_first_s")

    def _rel(ts: Any) -> Any:
        try:
            if ts is None or t_first is None:
                return None
            return float(ts) - float(t_first)
        except Exception:
            return None

    return [
        ["Timing source", _wrap(diagnostics.get("timing_source"), 52)],
        ["Drag anchor mode", _wrap(diagnostics.get("drag_anchor_mode"), 52)],
        ["Primary timing source", _wrap(diagnostics.get("primary_timing_source_for_windows"), 52)],
        ["Video first timestamp [s]", _fmt_value(diagnostics.get("t_first_s"))],
        ["Video last timestamp [s]", _fmt_value(diagnostics.get("t_last_s"))],
        ["Video elapsed [s]", _fmt_value(diagnostics.get("elapsed_time_s"))],
        ["Expected stage start rel. [s]", _fmt_value(_rel(diagnostics.get("expected_stage_start_video_s")))],
        ["Expected stage stop rel. [s]", _fmt_value(_rel(diagnostics.get("expected_stage_stop_video_s")))],
        ["Detected stage start rel. [s]", _fmt_value(_rel(diagnostics.get("detected_stage_start_video_s")))],
        ["Detected stage stop rel. [s]", _fmt_value(_rel(diagnostics.get("detected_stage_stop_video_s")))],
        ["Expected stage start abs. [s]", _fmt_value(diagnostics.get("expected_stage_start_video_s"))],
        ["Expected stage stop abs. [s]", _fmt_value(diagnostics.get("expected_stage_stop_video_s"))],
        ["Stage-video start delta [s]", _fmt_value(diagnostics.get("stage_video_start_delta_s"))],
        ["Stage-video stop delta [s]", _fmt_value(diagnostics.get("stage_video_stop_delta_s"))],
        ["Detected onset consistency", _fmt_value(diagnostics.get("detected_onset_consistency_flag"))],
        ["Detected onset consistency message", _wrap(diagnostics.get("detected_onset_consistency_message"), 52)],
        ["Stage anchor confidence", _wrap(diagnostics.get("stage_anchor_confidence"), 52)],
        ["Stage anchor reason", _wrap(diagnostics.get("stage_anchor_reason"), 52)],
        ["Detected onset QC only", _fmt_value(diagnostics.get("detected_onset_qc_only"))],
        ["Alignment sanity flag", _fmt_value(diagnostics.get("alignment_sanity_flag"))],
        ["Alignment sanity message", _wrap(diagnostics.get("alignment_sanity_message"), 52)],
        ["Alignment status", _wrap(diagnostics.get("alignment_status"), 52)],
        ["Alignment message", _wrap(diagnostics.get("alignment_message"), 52)],
        ["Baseline window [s]", _wrap(f"{diagnostics.get('baseline_start_s')} -> {diagnostics.get('baseline_end_s')}", 52)],
        ["Steady window [s]", _wrap(f"{diagnostics.get('steady_start_s')} -> {diagnostics.get('steady_end_s')}", 52)],
        ["Window clipping applied", _fmt_value(diagnostics.get("window_clipping_applied"))],
        ["Window clipping message", _wrap(diagnostics.get("window_clipping_message"), 52)],
    ]


def _drag_qc_confidence_rows(summary: dict[str, Any]) -> list[list[str]]:
    diagnostics = summary.get("diagnostics") or {}
    qc_flags = diagnostics.get("drag_qc_flags") or {}
    qc_text = ", ".join(f"{k}={v}" for k, v in qc_flags.items()) if qc_flags else "n/a"
    return [
        ["Drag validation gate", _wrap(diagnostics.get("drag_validation_gate"), 52)],
        ["Drag validation reason", _wrap(diagnostics.get("drag_validation_reason"), 52)],
        ["Primary physics gate", _wrap(diagnostics.get("physics_primary_gate"), 52)],
        ["Detection QC gate", _wrap(diagnostics.get("detection_qc_gate"), 52)],
        ["Final drag verdict", _wrap(diagnostics.get("final_drag_verdict"), 52)],
        ["Final drag reason", _wrap(diagnostics.get("final_drag_reason"), 52)],
        ["Stage validated physics acceptable", _fmt_value(diagnostics.get("stage_validated_physics_acceptable"))],
        ["Detected onset veto applied", _fmt_value(diagnostics.get("detected_onset_veto_applied"))],
        ["Analysis status", _fmt_value(diagnostics.get("analysis_status"))],
        ["Physics status", _fmt_value(diagnostics.get("physics_status"))],
        ["Drag physics confidence", _wrap(diagnostics.get("drag_physics_confidence"), 52)],
        ["Drag physics warning", _wrap(diagnostics.get("drag_physics_warning"), 52)],
        ["Baseline robustness flag", _fmt_value(diagnostics.get("baseline_robustness_flag"))],
        ["Onset robustness flag", _fmt_value(diagnostics.get("onset_robustness_flag"))],
        ["Kinematics robustness flag", _fmt_value(diagnostics.get("kinematics_robustness_flag"))],
        ["Onset confidence class", _fmt_value(diagnostics.get("onset_confidence_class"))],
        ["Speed consistency error [%]", _fmt_value(diagnostics.get("speed_consistency_error_pct"))],
        ["Baseline strategy difference ratio", _fmt_value(diagnostics.get("baseline_strategy_difference_ratio"))],
        ["QC flags", _wrap(qc_text, 52)],
    ]


def _drag_warning_rows(summary: dict[str, Any]) -> list[list[str]]:
    warnings = summary.get("warnings") or []
    if not warnings:
        return [["Warnings", "none"]]
    return [["Warnings", _wrap(" | ".join(str(w) for w in warnings), 52)]]


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
    bqc = diagnostics.get("brownian_qc") or {}
    head: list[list[str]] = []
    if bqc and not _is_drag_report(summary):
        head = [["QC rules (summary)", _wrap(_compact_qc_rules_summary(bqc.get("notes")), 52)]]
    rows = [
        ["Lost tracking fraction", _fmt_value(diagnostics.get("lost_fraction"))],
        ["Camera dropped frames", _fmt_value(diagnostics.get("camera_dropped_frames"))],
        ["Tracking lost frames", _fmt_value(diagnostics.get("tracking_lost_frames"))],
        ["Timestamp validation pass", _fmt_value(diagnostics.get("timestamp_validation_pass"))],
        ["Timestamp validation message", _wrap(diagnostics.get("timestamp_validation_message"), 52)],
        ["Warnings", _fmt_value(diagnostics.get("warning_count"))],
    ]
    if summary.get("error"):
        rows.append(["Failure reason", _wrap(summary.get("error"), 52)])
    if warnings:
        rows.append(["Warnings detail", _wrap(" | ".join(str(w) for w in warnings), 52)])
    return head + rows


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


def _compact_qc_rules_summary(notes: Any) -> str:
    text = str(notes or "").strip()
    if not text:
        return "n/a"
    # Keep this short so the QC row does not dominate the table layout.
    return (
        "Timing: timestamp validation. "
        "Tracking: lost_fraction (<=1% pass, <=5% caution). "
        "PSD: Lorentz RMSE/|A| tiers 2%/8%; fail if kappa unit check fails."
    )


def _safe_psd_fit_overlay(
    *,
    label: str,
    csv_path: Path,
    x_values: list[float],
    y_values: list[float],
    y_column_name: str,
) -> tuple[list[float], list[float], float] | None:
    """
    Return PSD fit overlay curve only when conversion/model is demonstrably consistent.
    Guardrails intentionally fail closed: measured PSD remains, but no overlay is drawn.
    """
    low_label = label.lower().strip()
    axis_key = "x" if low_label.startswith("psd x") else ("y" if low_label.startswith("psd y") else None)
    if axis_key is None:
        return None
    # We only draw overlay when measured series is in explicit um^2/Hz representation.
    if y_column_name != "psd_um2_per_hz":
        return None
    suffix = "_psd_x.csv" if axis_key == "x" else "_psd_y.csv"
    if not csv_path.name.endswith(suffix):
        return None

    base = csv_path.name[: -len(suffix)]
    fit_path = csv_path.parent.parent / "audit" / f"{base}_psd_fit.json"
    fit_payload = _load_json(fit_path)
    fit_block = (fit_payload or {}).get(f"fit_{axis_key}") or {}
    A = _parse_float(fit_block.get("A"))
    B = _parse_float(fit_block.get("B"))
    fc = _parse_float(fit_block.get("fc_hz"))
    if A is None or B is None or fc is None or fc <= 0:
        return None

    fmin = _parse_float(fit_block.get("fmin_hz"))
    fmax = _parse_float(fit_block.get("fmax_hz"))
    if fmin is None or fmax is None or fmin <= 0 or fmax <= fmin:
        return None

    # Candidate unit scalings from fit-domain to measured-domain.
    scales: list[float] = [1.0]
    run_json = _load_json(csv_path.parent.parent / "audit" / "run.json")
    um_per_px = _parse_float((((run_json or {}).get("config") or {}).get("calibration") or {}).get("um_per_px"))
    if um_per_px is not None and um_per_px > 0:
        s2 = float(um_per_px * um_per_px)
        scales.extend([s2, 1.0 / s2])

    best_overlay: tuple[float, list[float], list[float], float] | None = None
    for scale in scales:
        pairs: list[tuple[float, float]] = []
        ys_fit: list[float] = []
        xs_fit: list[float] = []
        for f, p in zip(x_values, y_values):
            ff = _parse_float(f)
            pp = _parse_float(p)
            if ff is None or pp is None or ff <= 0 or pp <= 0:
                continue
            if ff < fmin or ff > fmax:
                continue
            pred_native = (A / ((fc * fc) + (ff * ff))) + B
            pred = pred_native * scale
            if not math.isfinite(pred) or pred <= 0:
                continue
            xs_fit.append(float(ff))
            ys_fit.append(float(pred))
            pairs.append((float(ff), float(pred / pp)))
        if len(pairs) < 20:
            continue
        log_ratios = [abs(math.log10(ratio)) for _ff, ratio in pairs if ratio > 0]
        if not log_ratios:
            continue
        median_log_ratio = float(np.median(np.asarray(log_ratios, dtype=np.float64)))
        if not math.isfinite(median_log_ratio):
            continue
        if best_overlay is None or median_log_ratio < best_overlay[0]:
            best_overlay = (median_log_ratio, xs_fit, ys_fit, fc)

    if best_overlay is None:
        return None
    if best_overlay[0] > 0.35:
        return None
    return best_overlay[1], best_overlay[2], best_overlay[3]


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
        if row_idx > 0 and _col_idx == 1:
            try:
                label_text = str(table[(row_idx, 0)].get_text().get_text() or "").strip().lower()
                if label_text == "qc rules (summary)":
                    cell.PAD = 0.08
            except Exception:
                pass
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


def _add_figure_caption(fig, text: str, *, y: float = 0.84) -> None:
    """Add a concise explanatory caption under the page header."""
    fig.text(
        PAGE_MARGIN_LEFT,
        y,
        text,
        fontsize=9.2,
        color=MUTED_COLOR,
        ha="left",
        va="top",
        family=FONT_FAMILY,
        wrap=True,
    )


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
    label_col_fraction: float | None = None,
) -> None:
    x, y, width, height = bounds
    _add_panel(fig, bounds, facecolor=facecolor)
    fig.text(x + (width * 0.5), y + height - 0.035, title, fontsize=12.5, fontweight="bold", color=TEXT_COLOR, ha="center")

    def _cell(text: str, wrap_w: int) -> str:
        s = str(text or "").strip()
        if not s:
            return "n/a"
        if len(s) <= wrap_w and "\n" not in s:
            return s
        return textwrap.fill(s, width=wrap_w, break_long_words=False, break_on_hyphens=False)

    wrapped_rows = [
        [
            _cell(str(row[0] if len(row) > 0 else ""), label_wrap),
            _cell(str(row[1] if len(row) > 1 else ""), value_wrap),
        ]
        for row in rows
    ]
    if label_col_fraction is not None:
        label_width = float(label_col_fraction)
    else:
        label_width = _cover_table_col_width(wrapped_rows, min_fraction=min_label_fraction, max_fraction=max_label_fraction)

    ax = fig.add_axes([x + 0.016, y + 0.024, width - 0.032, height - 0.090])
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
            text_obj.set_fontsize(10)
            text_obj.set_fontweight("bold")
        else:
            cell.set_facecolor(PANEL_BG if row_idx % 2 == 0 else CARD_BG)
            text_obj.set_color(TEXT_COLOR)
            fs = 8.9 if col_idx == 1 else 9.1
            text_obj.set_fontsize(fs)
            if col_idx == 0:
                text_obj.set_fontweight("bold")
    for (row_idx, _col_idx), cell in table.get_celld().items():
        base_height = 0.085 if row_idx == 0 else 0.072
        cell.set_height(base_height * row_line_counts.get(row_idx, 1))


def _cover_key_result_rows(summary_rows: list[list[str]]) -> list[list[str]]:
    out: list[list[str]] = []
    for label, value in summary_rows:
        out.append([str(label), str(value)])
    return out


def _build_single_cover_table_rows(
    title: str,
    left_rows: list[list[str]],
    right_rows: list[list[str]],
) -> list[list[str]]:
    """Compose one two-column cover table with section dividers."""
    item_in_title = title.lower().startswith("item report:")
    identity_rows: list[list[str]] = []
    for row in left_rows:
        if not row:
            continue
        label = str(row[0]).strip()
        value = str(row[1]).strip() if len(row) > 1 else ""
        if label == "Acquisition source":
            continue
        if item_in_title and label == "Item":
            continue
        identity_rows.append([label, value or "n/a"])

    key_rows = _cover_key_result_rows(right_rows)
    qc_rows = [row for row in key_rows if str(row[0]).startswith("QC:") or str(row[0]) == "Overall Brownian QC"]
    main_rows = [row for row in key_rows if row not in qc_rows]

    out: list[list[str]] = []
    if identity_rows:
        out.append(["Identity / timing", ""])
        out.extend(identity_rows)
    if main_rows:
        out.append(["Main results", ""])
        out.extend(main_rows)
    if qc_rows:
        out.append(["Brownian QC", ""])
        out.extend(qc_rows)
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
            1 - PAGE_MARGIN_RIGHT, 0.026, page_counter.page_str(),
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
        "Quick first-page verdict: identity, timing, primary results, and Brownian QC.",
        fontsize=10.4,
        color=TEXT_COLOR,
        ha="center",
        wrap=True,
    )

    table_rows = _build_single_cover_table_rows(title, left_rows, right_rows)
    bounds = (0.06, 0.15, 0.88, 0.50)
    _add_panel(fig, bounds, facecolor=CARD_BG)
    ax_tbl = fig.add_axes([bounds[0] + 0.015, bounds[1] + 0.020, bounds[2] - 0.030, bounds[3] - 0.040])
    ax_tbl.axis("off")

    def _wrap_cover_cell(text: str, width: int) -> str:
        s = str(text or "").strip()
        if not s:
            return "n/a"
        if len(s) <= width and "\n" not in s:
            return s
        return textwrap.fill(s, width=width, break_long_words=False, break_on_hyphens=False)

    wrapped_rows = [[_wrap_cover_cell(r[0], 34), _wrap_cover_cell(r[1], 62)] for r in table_rows]
    table = ax_tbl.table(
        cellText=wrapped_rows,
        colLabels=["Field", "Value"],
        cellLoc="left",
        colLoc="left",
        colWidths=[0.36, 0.64],
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    table.auto_set_font_size(False)
    section_labels = {"Identity / timing", "Main results", "Brownian QC"}
    nrows = len(wrapped_rows) + 1  # include header
    row_h = 0.98 / max(1, nrows)
    for (row_idx, col_idx), cell in table.get_celld().items():
        text_obj = cell.get_text()
        cell.PAD = 0.13
        cell.set_edgecolor(LINE_COLOR)
        cell.set_linewidth(0.45)
        text_obj.set_wrap(True)
        text_obj.set_ha("left")
        text_obj.set_va("center")
        if row_idx == 0:
            cell.set_facecolor(BRAND_COLOR)
            text_obj.set_color("white")
            text_obj.set_fontweight("bold")
            text_obj.set_fontsize(10.3)
        else:
            row_label = wrapped_rows[row_idx - 1][0]
            is_section = (row_label in section_labels) and (wrapped_rows[row_idx - 1][1] in {"", "n/a"})
            if is_section:
                cell.set_facecolor(PANEL_BG if col_idx == 0 else CARD_BG)
                if col_idx == 0:
                    text_obj.set_fontweight("bold")
                    text_obj.set_color(BRAND_COLOR)
                    text_obj.set_fontsize(9.8)
                else:
                    text_obj.set_text("")
            else:
                cell.set_facecolor("white" if row_idx % 2 else PANEL_BG)
                text_obj.set_color(TEXT_COLOR)
                text_obj.set_fontsize(9.2 if col_idx == 0 else 9.0)
                if col_idx == 0:
                    text_obj.set_fontweight("bold")
        cell.set_height(row_h)

    fig.text(
        0.50,
        0.105,
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
        r"where $k_{\mathrm{B}}$ is the Boltzmann constant, $T$ is temperature, and $\langle x^2 \rangle$ is the",
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
        r"$S_{xx}(f)=\frac{A}{1+(f/f_{\mathrm{c}})^2}+B$",
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
        r"with dynamic viscosity $\eta$.",
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
        r"• Stiffness from variance: $\mathrm{SE}(\sigma^{2}) \approx \sigma^{2}\sqrt{2/(n-1)}$ (Gaussian).",
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
        r"• Corner frequency $f_{\mathrm{c}}$: uncertainty from the Lorentzian PSD fit (reported SE).",
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
    """Single-page drag theory: Brown-family layout, airy spacing, display equations without boxes."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Theory and Methods", page_counter=page_counter)

    theory_bottom = 0.112
    ax_h = DRAG_STACK_TOP - theory_bottom
    ax = fig.add_axes([DRAG_CONTENT_LEFT, theory_bottom, DRAG_CONTENT_RIGHT - DRAG_CONTENT_LEFT, ax_h])
    ax.axis("off")

    line_height = 0.0295
    section_gap = 0.04
    equation_gap = 0.054
    theory_section_fs = 11
    y = 0.98

    ax.text(
        0.0,
        y,
        "Constant-velocity drag in a harmonic trap",
        fontsize=FONT_SIZE_HEADER,
        fontweight="bold",
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height * 1.5

    ax.text(
        0.0,
        y,
        textwrap.fill(
            (
                "The stage executes an approximately constant-velocity segment while a trapped bead is monitored along the drag axis. "
                "The harmonic trap (stiffness κ) pulls the particle toward its centre; fluid drag opposes that motion when the medium "
                "moves relative to the bead."
            ),
            width=90,
        ),
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
        va="top",
        linespacing=1.42,
    )
    y -= line_height * 2.55 + section_gap * 0.45

    ax.text(
        0.0,
        y,
        textwrap.fill(
            (
                "At steady motion the bead sits at a finite offset x_ss: Stokes drag balances trap restoring force (κ x_ss). "
                "That offset is the physical readout of viscosity, slip speed, and trap stiffness—not a tracking defect. "
                "Overdamped relaxation after perturbations is characterised by τ = γ/κ."
            ),
            width=90,
        ),
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
        va="top",
        linespacing=1.42,
    )
    y -= line_height * 2.65 + section_gap * 1.05

    ax.text(
        0.0,
        y,
        "Stokes drag and steady offset",
        fontsize=theory_section_fs,
        fontweight="bold",
        color=BRAND_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height * 1.15

    ax.text(
        0.0,
        y,
        textwrap.fill(
            "For a sphere of effective radius R in viscosity η, the drag coefficient is γ ≈ 6πηR. Steady balance and relaxation:",
            width=90,
        ),
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
        va="top",
        linespacing=1.4,
    )
    y -= line_height * 1.45 + section_gap * 0.55

    y -= equation_gap * 0.5
    ax.text(
        0.5,
        y,
        r"$\gamma \approx 6\pi\eta R$",
        fontsize=14,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        ha="center",
    )
    y -= equation_gap
    ax.text(
        0.5,
        y,
        r"$x_{\mathrm{ss}} = \dfrac{\gamma v}{\kappa}$",
        fontsize=14,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        ha="center",
    )
    y -= equation_gap
    ax.text(
        0.5,
        y,
        r"$\tau = \dfrac{\gamma}{\kappa}$",
        fontsize=14,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        ha="center",
    )
    y -= line_height * 1.05

    ax.text(
        0.0,
        y,
        textwrap.fill(
            (
                r"where $v$ is the steady slip speed along the drag axis, and $\gamma$ is the same drag coefficient that enters "
                r"Brownian calibration (PSD corner frequency) when overdamped dynamics apply."
            ),
            width=94,
        ),
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        fontstyle="italic",
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
        va="top",
        linespacing=1.4,
    )
    y -= line_height * 2.15 + section_gap * 1.15

    ax.text(
        0.0,
        y,
        "Signal structure and reporting windows",
        fontsize=theory_section_fs,
        fontweight="bold",
        color=BRAND_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height * 1.15

    ax.text(
        0.0,
        y,
        textwrap.fill(
            (
                "Read the trace as baseline → transition → steady plateau: baseline sets the centreing reference; the plateau carries "
                "headline numbers. Windows follow stage-truth sidecars; trajectory onset/stop overlays are QC-only, not primary definitions."
            ),
            width=90,
        ),
        fontsize=FONT_SIZE_NORMAL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
        va="top",
        linespacing=1.4,
    )
    y -= line_height * 2.45 + section_gap * 1.1

    ax.text(
        0.0,
        y,
        "Assumptions and limitations",
        fontsize=theory_section_fs,
        fontweight="bold",
        color=BRAND_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
    )
    y -= line_height * 1.1

    ax.text(
        0.0,
        y,
        textwrap.fill(
            (
                "Overdamped, inertia-free motion; 1D axis-aligned interpretation. Brownian calibration supplies κ and noise context only. "
                "Near-wall hydrodynamics, slip, heating, and non-Stokes corrections are not fully closed here—interpret margins "
                "accordingly."
            ),
            width=90,
        ),
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        fontstyle="italic",
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
        va="top",
        linespacing=1.38,
    )
    y -= line_height * 2.15 + section_gap * 1.1

    ax.text(
        0.0,
        y,
        "References",
        fontsize=theory_section_fs,
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
    y -= line_height * 0.95
    ax.text(
        0.0,
        y,
        "[2] A. Rohrbach, Opt. Express 13, 9695 (2005)",
        fontsize=FONT_SIZE_SMALL,
        color=TEXT_COLOR,
        transform=ax.transAxes,
        family=FONT_FAMILY,
        ha="left",
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

    _add_panel(fig, (0.06, 0.45, 0.88, 0.33), facecolor=CARD_BG)
    _add_panel(fig, (0.06, 0.08, 0.88, 0.33), facecolor=PANEL_BG)

    ax_top_title = fig.add_axes([PAGE_MARGIN_LEFT, 0.742, 0.84, 0.042])
    ax_top_title.axis("off")
    ax_top_title.text(0.0, 0.5, top_title, fontsize=FONT_SIZE_HEADER, fontweight="bold", 
                      color=TEXT_COLOR, va="center", family=FONT_FAMILY)

    ax_top = fig.add_axes([PAGE_MARGIN_LEFT, 0.472, 0.84, 0.26])
    ax_top.axis("off")
    top_table = ax_top.table(
        cellText=top_rows,
        colLabels=["Field", "Value"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    _style_table(top_table, body_font_size=9, header_font_size=10)

    ax_bottom_title = fig.add_axes([PAGE_MARGIN_LEFT, 0.362, 0.84, 0.042])
    ax_bottom_title.axis("off")
    ax_bottom_title.text(0.0, 0.5, bottom_title, fontsize=FONT_SIZE_HEADER, fontweight="bold", 
                         color=TEXT_COLOR, va="center", family=FONT_FAMILY)

    ax_bottom = fig.add_axes([PAGE_MARGIN_LEFT, 0.105, 0.84, 0.24])
    ax_bottom.axis("off")
    bottom_table = ax_bottom.table(
        cellText=bottom_rows,
        colLabels=["Field", "Value"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    _style_table(bottom_table, body_font_size=9, header_font_size=10)

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
        if "Power Spectral Density" in title:
            _add_figure_caption(
                fig,
                "PSD captures the frequency content of Brownian motion. Measured spectra are overlaid with Lorentzian fits to support corner-frequency and fit-quality interpretation.",
                y=0.84,
            )
        fig.subplots_adjust(top=0.77, left=0.10, right=0.92, bottom=0.085, hspace=0.40, wspace=0.28)
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
            fit_drawn = False
            y_name = parsed[3]
            overlay = _safe_psd_fit_overlay(
                label=label,
                csv_path=csv_path,
                x_values=xs,
                y_values=ys,
                y_column_name=y_name,
            )

            low_label = label.lower()
            is_psd = low_label.startswith("psd x") or low_label.startswith("psd y")
            ax.plot(xs, ys, linewidth=1.6, color=PLOT_COLOR, label="Measured PSD" if is_psd else None)
            if overlay is not None:
                xs_fit, ys_fit, fc_hz = overlay
                ax.plot(
                    xs_fit,
                    ys_fit,
                    linewidth=1.55,
                    color="#C0392B",
                    linestyle="--",
                    alpha=0.95,
                    label="Fitted PSD",
                )
                fit_drawn = True
                if fc_hz > 0 and math.isfinite(fc_hz):
                    fc_color = "#E67E22"  # warm accent: readable, distinct from measured/fitted curves
                    fc_pred = (ys_fit[min(range(len(xs_fit)), key=lambda i: abs(xs_fit[i] - fc_hz))] if xs_fit else None)
                    ax.axvline(fc_hz, color=fc_color, linestyle=(0, (3, 2)), linewidth=1.45, alpha=0.95)
                    if fc_pred is not None and math.isfinite(fc_pred) and fc_pred > 0:
                        ax.plot(
                            [fc_hz],
                            [fc_pred],
                            marker="o",
                            markersize=4.6,
                            markeredgewidth=0.7,
                            markeredgecolor="white",
                            color=fc_color,
                            zorder=5,
                        )
                    ax.text(
                        fc_hz * 1.10,
                        fc_pred * 1.20 if (fc_pred is not None and fc_pred > 0) else (max(ys_fit) * 1.05 if ys_fit else 1.0),
                        f"fc = {fc_hz:.2f} Hz",
                        fontsize=8,
                        color=fc_color,
                        ha="left",
                        va="bottom",
                    )
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
            if fit_drawn:
                ax.legend(loc="upper right", fontsize=8, frameon=True, facecolor="white", edgecolor=LINE_COLOR)
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
    _add_figure_caption(
        fig,
        "Heat map and marginal histograms summarize spatial Brownian fluctuations in the trap. Distribution symmetry and spread help assess trap behavior.",
        y=0.84,
    )

    # Scatter_hist layout: histx top, scatter bottom-left, histy right, colorbar far right
    gs = GridSpec(
        2,
        3,
        width_ratios=[4, 1, 0.35],
        height_ratios=[1, 4],
        left=PAGE_MARGIN_LEFT,
        right=1 - PAGE_MARGIN_RIGHT,
        bottom=PAGE_MARGIN_BOTTOM + 0.02,
        top=0.79,
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

    # Two rows, one column: top = Histogram R, bottom = MSD (MSD gets more height for readability)
    fig, axes = plt.subplots(2, 1, figsize=PAGE_SIZE, gridspec_kw={"height_ratios": [1.0, 1.35]})
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Histogram R And MSD", page_counter=page_counter)
    _add_figure_caption(
        fig,
        "Histogram R summarizes radial position distribution. MSD shows time-dependent mean-squared displacement and supports relaxation-dynamics interpretation.",
        y=0.84,
    )
    fig.subplots_adjust(top=0.77, left=0.10, right=0.92, bottom=0.085, hspace=0.32)

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
            finite_pairs = [
                (x, y) for x, y in zip(msd_xs, msd_ys)
                if math.isfinite(float(x)) and math.isfinite(float(y)) and float(x) > 0 and float(y) > 0
            ]
            if finite_pairs:
                xs_pos = [float(p[0]) for p in finite_pairs]
                ys_pos = [float(p[1]) for p in finite_pairs]
                ax_msd.loglog(xs_pos, ys_pos, color=PLOT_COLOR, linewidth=2.0, marker="o", markersize=2.3, alpha=0.95)
                xmin, xmax = min(xs_pos), max(xs_pos)
                ymin, ymax = min(ys_pos), max(ys_pos)
                if xmin > 0 and xmax > xmin:
                    ax_msd.set_xlim(xmin * 0.90, xmax * 1.12)
                if ymin > 0 and ymax > ymin:
                    ax_msd.set_ylim(ymin * 0.85, ymax * 1.18)
            else:
                ax_msd.plot(msd_xs, msd_ys, color=PLOT_COLOR, linewidth=1.9)
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
    _add_figure_caption(
        fig,
        "Representative frames sampled across the run for visual QA. They help verify tracking stability and localization quality over time.",
        y=0.84,
    )

    nrows, ncols = 3, 4
    gs = GridSpec(
        nrows,
        ncols,
        left=PAGE_MARGIN_LEFT,
        right=1 - PAGE_MARGIN_RIGHT,
        bottom=PAGE_MARGIN_BOTTOM + 0.02,
        top=0.79,
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


def _select_representative_preview_paths(image_paths: list[Path], max_images: int = 6) -> list[Path]:
    paths = [Path(p) for p in image_paths]
    if len(paths) <= max_images:
        return paths
    n = len(paths)
    idxs = {int(round(i * (n - 1) / float(max_images - 1))) for i in range(max_images)}
    return [paths[i] for i in sorted(idxs)]


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


def _render_drag_trace_page(
    pdf,
    trace_csv: Path,
    summary: dict[str, Any],
    *,
    page_counter: PageCounter | None = None,
) -> None:
    import matplotlib.pyplot as plt

    diagnostics = summary.get("diagnostics") or {}
    times: list[float] = []
    signal: list[float] = []
    try:
        with trace_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t_val = row.get("video_time_rel_s") or row.get("video_time_s")
                x_val = row.get("axis_px")
                if t_val is None or x_val is None:
                    continue
                try:
                    times.append(float(t_val))
                    signal.append(float(x_val))
                except Exception:
                    continue
    except Exception:
        return
    if not times or not signal:
        return

    t_first = diagnostics.get("t_first_s")

    def _rel(ts: Any) -> float | None:
        if ts is None:
            return None
        try:
            val = float(ts)
        except Exception:
            return None
        if t_first is not None and val > max(times) + 5.0:
            # stage/video absolute timestamps -> convert to relative if needed
            return val - float(t_first)
        if t_first is not None and val >= float(t_first) and val > max(times):
            return val - float(t_first)
        return val

    fig, ax = plt.subplots(1, 1, figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Drag Windows And Annotated Trace", page_counter=page_counter)
    fig.subplots_adjust(top=0.81, left=0.10, right=0.92, bottom=0.10)
    ax.set_facecolor(PANEL_BG)
    ax.plot(times, signal, linewidth=1.5, color=PLOT_COLOR, label="axis signal (px)")

    b0 = _rel(diagnostics.get("baseline_start_s"))
    b1 = _rel(diagnostics.get("baseline_end_s"))
    s0 = _rel(diagnostics.get("steady_start_s"))
    s1 = _rel(diagnostics.get("steady_end_s"))
    if b0 is not None and b1 is not None:
        ax.axvspan(b0, b1, color="#A5D6A7", alpha=0.22, label="primary baseline window")
    if s0 is not None and s1 is not None:
        ax.axvspan(s0, s1, color="#EF9A9A", alpha=0.22, label="primary steady window")

    exp_start = _rel(diagnostics.get("expected_stage_start_video_s"))
    exp_stop = _rel(diagnostics.get("expected_stage_stop_video_s"))
    det_start = _rel(diagnostics.get("detected_stage_start_video_s"))
    det_stop = _rel(diagnostics.get("detected_stage_stop_video_s"))
    if exp_start is not None:
        ax.axvline(exp_start, color="#1565C0", linestyle="-.", linewidth=1.0, label="expected stage start")
    if exp_stop is not None:
        ax.axvline(exp_stop, color="#0D47A1", linestyle="-.", linewidth=1.0, label="expected stage stop")
    if det_start is not None:
        ax.axvline(det_start, color="#000000", linestyle="--", linewidth=1.0, label="detected onset (QC)")
    if det_stop is not None:
        ax.axvline(det_stop, color="#616161", linestyle=":", linewidth=1.0, label="detected stop (QC)")

    ax.set_title("Primary stage windows with detected onset QC", fontsize=11.0, fontweight="bold")
    ax.set_xlabel("Time from video start [s]", fontsize=FONT_SIZE_SMALL)
    ax.set_ylabel("Axis position [px]", fontsize=FONT_SIZE_SMALL)
    ax.grid(True, linestyle="--", linewidth=0.5, color=LINE_COLOR)
    ax.legend(fontsize=8)
    pdf.savefig(fig)
    plt.close(fig)


def _read_csv_columns(path: Path | None) -> dict[str, np.ndarray]:
    """
    Read a CSV into numeric columns (float where possible).

    Non-numeric cells become NaN. Missing path -> empty dict.
    """
    if path is None or not Path(path).is_file():
        return {}
    cols: dict[str, list[float]] = {}
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                if not row:
                    continue
                for k, v in row.items():
                    if k is None:
                        continue
                    if k not in cols:
                        cols[k] = []
                    cols[k].append(_parse_float(v) if v not in (None, "") else float("nan"))
    except Exception:
        return {}
    return {k: np.asarray(v, dtype=np.float64) for k, v in cols.items()}


def _drag_video_time_origin_s(summary: dict[str, Any]) -> float:
    diagnostics = summary.get("diagnostics") or {}
    t0 = _parse_float(diagnostics.get("t_first_s"))
    if t0 is None:
        t0 = 0.0
    return float(t0)


def _drag_to_video_rel_s(summary: dict[str, Any], video_time_s: float | None) -> float | None:
    if video_time_s is None:
        return None
    t0 = _drag_video_time_origin_s(summary)
    return float(video_time_s) - t0


def _drag_stage_to_video_rel_s(summary: dict[str, Any], stage_time_s: float | None) -> float | None:
    """Map stage trace seconds into video-relative seconds using saved alignment offset."""
    if stage_time_s is None:
        return None
    diagnostics = summary.get("diagnostics") or {}
    off = _parse_float(diagnostics.get("alignment_offset_s"))
    if off is None:
        return None
    t_video = float(stage_time_s) + float(off)
    return _drag_to_video_rel_s(summary, t_video)


def _drag_resolve_primary_markers(
    summary: dict[str, Any],
    *,
    windows_csv: Path | None,
    stage_trace_path: Path | None,
) -> dict[str, dict[str, Any]]:
    """
    Resolve stage-truth-first diagnostic markers.

    Returns:
      {"raw": {...}, "derived": {...}}
    All marker times are in video-relative seconds (time from video start).
    """
    diagnostics = summary.get("diagnostics") or {}
    raw: dict[str, Any] = {}
    derived: dict[str, Any] = {}

    # Primary truth: expected stage start/stop in video time (already stage-aligned by analysis).
    raw["motion_start_s"] = _drag_to_video_rel_s(summary, _parse_float(diagnostics.get("expected_stage_start_video_s")))
    raw["motion_stop_s"] = _drag_to_video_rel_s(summary, _parse_float(diagnostics.get("expected_stage_stop_video_s")))

    # Optional stage trace events (script / running-confirmed), mapped via alignment offset.
    if stage_trace_path is not None and Path(stage_trace_path).is_file():
        try:
            with Path(stage_trace_path).open("r", encoding="utf-8", newline="") as f:
                rdr = csv.DictReader(f)
                for row in rdr:
                    if not row:
                        continue
                    ev = str(row.get("event", "")).strip().lower()
                    t_s = _parse_float(row.get("t_s"))
                    if t_s is None:
                        continue
                    if ev in {"motion_command_issued", "motion_running_confirmed", "motion_start", "motion_stop"}:
                        raw[ev] = _drag_stage_to_video_rel_s(summary, float(t_s))
        except Exception:
            pass

    # Windows: baseline/steady from summary; if missing, fall back to windows CSV.
    b0 = _parse_float(diagnostics.get("baseline_start_s"))
    b1 = _parse_float(diagnostics.get("baseline_end_s"))
    s0 = _parse_float(diagnostics.get("steady_start_s"))
    s1 = _parse_float(diagnostics.get("steady_end_s"))
    if (b0 is None or b1 is None or s0 is None or s1 is None) and windows_csv is not None and Path(windows_csv).is_file():
        try:
            with Path(windows_csv).open("r", encoding="utf-8", newline="") as f:
                rdr = csv.DictReader(f)
                for row in rdr:
                    name = str(row.get("window", "")).strip().lower()
                    st = _parse_float(row.get("start_s"))
                    en = _parse_float(row.get("end_s"))
                    if name == "baseline" and st is not None and en is not None:
                        b0, b1 = st, en
                    if name == "steady" and st is not None and en is not None:
                        s0, s1 = st, en
        except Exception:
            pass

    raw["baseline_start_s"] = _drag_to_video_rel_s(summary, b0)
    raw["baseline_end_s"] = _drag_to_video_rel_s(summary, b1)
    raw["steady_start_s"] = _drag_to_video_rel_s(summary, s0)
    raw["steady_end_s"] = _drag_to_video_rel_s(summary, s1)

    # Secondary QC marker: trajectory onset detection.
    derived["detected_onset_qc_s"] = _drag_to_video_rel_s(summary, _parse_float(diagnostics.get("detected_stage_start_video_s")))
    derived["detected_stop_qc_s"] = _drag_to_video_rel_s(summary, _parse_float(diagnostics.get("detected_stage_stop_video_s")))

    # Derived phase boundaries for visualization when no encoder trace exists.
    ms = raw.get("motion_start_s")
    me = raw.get("motion_stop_s")
    ss0 = raw.get("steady_start_s")
    ss1 = raw.get("steady_end_s")
    if isinstance(ms, float) and isinstance(me, float) and math.isfinite(ms) and math.isfinite(me) and me > ms:
        dur = me - ms
        a = max(0.12 * dur, 0.05)
        a = min(a, 0.33 * dur)
        derived["acceleration_end_s"] = ms + a
        derived["deceleration_start_s"] = me - a
    if isinstance(ss0, float) and math.isfinite(ss0):
        derived["steady_state_start_s"] = float(ss0)
    if isinstance(ss1, float) and math.isfinite(ss1):
        derived["steady_state_stop_s"] = float(ss1)
    if raw.get("motion_running_confirmed") is not None:
        derived["motion_running_confirmed_s"] = raw.get("motion_running_confirmed")
    else:
        if isinstance(ms, float) and isinstance(derived.get("acceleration_end_s"), float):
            derived["motion_running_confirmed_s"] = ms + 0.5 * (derived["acceleration_end_s"] - ms)
    return {"raw": raw, "derived": derived}


def _drag_um_per_px(summary: dict[str, Any]) -> float | None:
    metrics = summary.get("metrics") or {}
    v = _parse_float(metrics.get("um_per_px"))
    return float(v) if v is not None and v > 0 else None


def _drag_stage_travel_um(summary: dict[str, Any]) -> float | None:
    # Preferred: drag summary exports actual_travel_um; keep fallback conservative.
    diagnostics = summary.get("diagnostics") or {}
    v = _parse_float(diagnostics.get("actual_travel_um"))
    if v is not None and math.isfinite(v):
        return float(v)
    return None


def _drag_trace_time_and_signal_um(
    summary: dict[str, Any],
    trace_csv: Path | None,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    cols = _read_csv_columns(trace_csv)
    if not cols:
        return None, None
    t = cols.get("video_time_rel_s")
    if t is None:
        t_abs = cols.get("video_time_s")
        if t_abs is not None and len(t_abs):
            t0 = float(t_abs[0])
            t = t_abs - t0
    if t is None:
        t = cols.get("stage_time_aligned_s")
    y_um = cols.get("axis_um")
    if y_um is None:
        y_px = cols.get("axis_px")
        um_per_px = _drag_um_per_px(summary)
        if y_px is not None and um_per_px is not None:
            y_um = y_px * float(um_per_px)
    if t is None or y_um is None or len(t) == 0 or len(y_um) == 0:
        return None, None
    n = min(len(t), len(y_um))
    return t[:n], y_um[:n]


def _drag_stage_profile_from_saved_data(
    summary: dict[str, Any],
    *,
    stage_trace_path: Path | None,
    trace_csv: Path | None,
    markers: dict[str, dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    def _first_present(columns: dict[str, np.ndarray], names: tuple[str, ...]) -> np.ndarray | None:
        for name in names:
            arr = columns.get(name)
            if arr is not None:
                return arr
        return None

    cols = _read_csv_columns(stage_trace_path)
    if cols:
        t = cols.get("video_time_rel_s")
        if t is None:
            t = cols.get("stage_time_aligned_s")
        if t is None:
            t_stage = cols.get("t_s")
            if t_stage is not None:
                mapped: list[float] = []
                for v in t_stage:
                    if math.isnan(v):
                        mapped.append(float("nan"))
                    else:
                        rel = _drag_stage_to_video_rel_s(summary, float(v))
                        mapped.append(float(rel) if rel is not None else float("nan"))
                t = np.asarray(mapped, dtype=np.float64)
        pos = _first_present(cols, ("stage_position_um", "position_um", "stage_pos_um", "x_um"))
        vel = _first_present(cols, ("stage_velocity_um_s", "velocity_um_s", "stage_vel_um_s", "vx_um_s"))
        if t is not None and pos is not None and len(t) and len(pos):
            n = min(len(t), len(pos))
            t = t[:n]
            pos = pos[:n]
            finite_t = np.isfinite(t)
            finite_pos = np.isfinite(pos)
            keep = finite_t & finite_pos
            if np.any(keep):
                t = t[keep]
                pos = pos[keep]
                if vel is not None and len(vel):
                    vel = vel[:n]
                    vel = vel[keep]
                else:
                    vel = None
                if vel is None:
                    dt = np.diff(t, prepend=t[0])
                    dp = np.diff(pos, prepend=pos[0])
                    with np.errstate(divide="ignore", invalid="ignore"):
                        vel = np.where(np.abs(dt) > 1e-12, dp / dt, np.nan)
                return t, pos, np.asarray(vel, dtype=np.float64)

    travel_um = _drag_stage_travel_um(summary)
    prof = _drag_build_stage_profile_from_markers(markers, travel_um=travel_um)
    if prof is not None:
        return prof

    t_trace, y_trace_um = _drag_trace_time_and_signal_um(summary, trace_csv)
    if t_trace is None or y_trace_um is None:
        return None
    raw = markers.get("raw") or {}
    b0 = raw.get("baseline_start_s")
    b1 = raw.get("baseline_end_s")
    baseline_mask = (t_trace >= float(b0)) & (t_trace <= float(b1)) if isinstance(b0, float) and isinstance(b1, float) else None
    center = (
        float(np.nanmedian(y_trace_um[baseline_mask]))
        if (baseline_mask is not None and np.any(baseline_mask))
        else float(np.nanmedian(y_trace_um))
    )
    bead_rel = y_trace_um - center
    return t_trace, np.zeros_like(bead_rel), np.zeros_like(bead_rel)


def _drag_build_stage_profile_from_markers(
    markers: dict[str, dict[str, Any]],
    *,
    travel_um: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """
    Build an idealized trapezoidal stage profile from stage-truth markers.
    Returns (t, position_um, velocity_um_s) in video-relative seconds.
    """
    raw = markers.get("raw") or {}
    derived = markers.get("derived") or {}
    ms = raw.get("motion_start_s")
    me = raw.get("motion_stop_s")
    if not isinstance(ms, float) or not isinstance(me, float) or not math.isfinite(ms) or not math.isfinite(me) or me <= ms:
        return None
    if travel_um is None or not math.isfinite(float(travel_um)) or float(travel_um) == 0:
        return None
    travel = float(travel_um)

    a_end = derived.get("acceleration_end_s")
    d_start = derived.get("deceleration_start_s")
    if not isinstance(a_end, float) or not isinstance(d_start, float) or a_end <= ms or d_start >= me or d_start <= a_end:
        dur = me - ms
        a_end = ms + 0.2 * dur
        d_start = ms + 0.8 * dur

    dur = me - ms
    ta = a_end - ms
    td = me - d_start
    tc = max(0.0, d_start - a_end)
    area = 0.5 * ta + tc + 0.5 * td
    if area <= 0:
        return None
    v_plateau = travel / area

    n = int(max(300, min(1600, math.ceil(dur * 200))))
    t = np.linspace(ms, me, n, dtype=np.float64)
    v = np.zeros_like(t)
    accel_mask = t <= a_end
    if ta > 0:
        v[accel_mask] = v_plateau * (t[accel_mask] - ms) / ta
    cruise_mask = (t > a_end) & (t < d_start)
    v[cruise_mask] = v_plateau
    decel_mask = t >= d_start
    if td > 0:
        v[decel_mask] = v_plateau * (me - t[decel_mask]) / td

    dt = np.diff(t, prepend=t[0])
    dt[0] = 0.0
    pos = np.cumsum(v * dt)
    return t, pos, v


def _drag_plot_markers(ax, markers: dict[str, dict[str, Any]], *, include_windows: bool = True) -> None:
    raw = markers.get("raw") or {}
    derived = markers.get("derived") or {}

    if include_windows:
        b0 = raw.get("baseline_start_s")
        b1 = raw.get("baseline_end_s")
        s0 = raw.get("steady_start_s")
        s1 = raw.get("steady_end_s")
        if isinstance(b0, float) and isinstance(b1, float):
            ax.axvspan(b0, b1, color="#A5D6A7", alpha=0.22, label="baseline window (primary)")
        if isinstance(s0, float) and isinstance(s1, float):
            ax.axvspan(s0, s1, color="#EF9A9A", alpha=0.22, label="steady window (primary)")

    ms = raw.get("motion_start_s")
    me = raw.get("motion_stop_s")
    if isinstance(ms, float):
        ax.axvline(ms, color="#1565C0", linestyle="-.", linewidth=1.1, label="motion start (stage truth)")
    if isinstance(me, float):
        ax.axvline(me, color="#0D47A1", linestyle="-.", linewidth=1.1, label="motion stop (stage truth)")

    mrc = derived.get("motion_running_confirmed_s")
    if isinstance(mrc, float):
        ax.axvline(mrc, color="#1976D2", linestyle=":", linewidth=1.0, label="motion running confirmed (derived)")

    ss0 = derived.get("steady_state_start_s")
    ss1 = derived.get("steady_state_stop_s")
    if isinstance(ss0, float):
        ax.axvline(ss0, color="#2E7D32", linestyle="--", linewidth=1.0, label="steady-state start (from windows)")
    if isinstance(ss1, float):
        ax.axvline(ss1, color="#C62828", linestyle="--", linewidth=1.0, label="steady-state stop (from windows)")

    dec = derived.get("deceleration_start_s")
    if isinstance(dec, float):
        ax.axvline(dec, color="#6A1B9A", linestyle=":", linewidth=1.0, label="deceleration start (derived)")

    det_on = derived.get("detected_onset_qc_s")
    det_st = derived.get("detected_stop_qc_s")
    if isinstance(det_on, float):
        ax.axvline(det_on, color="#000000", linestyle="--", linewidth=1.0, label="detected onset (QC-only)")
    if isinstance(det_st, float):
        ax.axvline(det_st, color="#616161", linestyle=":", linewidth=1.0, label="detected stop (QC-only)")


def _drag_caption_row_text(ax_cap: Any, text: str, *, width: int = 84) -> None:
    """Caption in its own axes row — below plot/labels, never inside the plotting area."""
    ax_cap.axis("off")
    ax_cap.set_xlim(0, 1)
    ax_cap.set_ylim(0, 1)
    wrapped = textwrap.fill(text.strip(), width=width)
    ax_cap.text(
        0.5,
        1.0,
        wrapped,
        transform=ax_cap.transAxes,
        ha="center",
        va="top",
        fontsize=8.15,
        color=MUTED_COLOR,
        family=FONT_FAMILY,
        linespacing=1.38,
    )


def _drag_figure_legend_from_axes(
    fig: Any,
    source_axes: tuple[Any, ...],
    *,
    ncol: int = 4,
    fontsize: float = 7.45,
) -> None:
    """Shared legend in the bottom figure zone (below captions), print-safe."""
    lines: list[Any] = []
    labels: list[str] = []
    for ax in source_axes:
        lns, labs = ax.get_legend_handles_labels()
        lines.extend(lns)
        labels.extend(labs)
    by_label: dict[str, Any] = {}
    for ln, lb in zip(lines, labels):
        if lb and lb not in by_label:
            by_label[lb] = ln
    if not by_label:
        return
    fig.legend(
        list(by_label.values()),
        list(by_label.keys()),
        loc="upper center",
        bbox_to_anchor=(0.5, DRAG_LEGEND_FIG_Y),
        bbox_transform=fig.transFigure,
        ncol=ncol,
        fontsize=fontsize,
        frameon=True,
        framealpha=0.97,
        fancybox=False,
        edgecolor=LINE_COLOR,
        columnspacing=1.08,
        handlelength=1.55,
        handletextpad=0.55,
        borderpad=0.52,
        labelspacing=0.85,
    )


def _drag_pick_preview_index(target_rel_s: float, elapsed_s: float, n: int) -> int:
    if n <= 1 or elapsed_s <= 0:
        return 0
    frac = min(max(target_rel_s / elapsed_s, 0.0), 1.0)
    return int(round(frac * float(n - 1)))


def _drag_select_stage_truth_preview_paths(
    summary: dict[str, Any],
    preview_paths: list[Path],
) -> list[tuple[str, Path]]:
    if not preview_paths:
        return []
    diagnostics = summary.get("diagnostics") or {}
    markers = _drag_resolve_primary_markers(summary, windows_csv=None, stage_trace_path=None)
    raw = markers.get("raw") or {}
    elapsed = _parse_float(diagnostics.get("elapsed_time_s"))
    elapsed_s = float(elapsed) if elapsed is not None and elapsed > 0 else float(max(1, len(preview_paths) - 1))

    b0 = raw.get("baseline_start_s")
    b1 = raw.get("baseline_end_s")
    s0 = raw.get("steady_start_s")
    s1 = raw.get("steady_end_s")
    ms = raw.get("motion_start_s")
    me = raw.get("motion_stop_s")
    baseline_t = (float(b0) + float(b1)) * 0.5 if isinstance(b0, float) and isinstance(b1, float) else 0.12 * elapsed_s
    steady_t = (float(s0) + float(s1)) * 0.5 if isinstance(s0, float) and isinstance(s1, float) else 0.60 * elapsed_s
    if isinstance(me, float):
        post_t = min(0.95 * elapsed_s, me + max(0.3, 0.3 * max(0.0, elapsed_s - me)))
    elif isinstance(ms, float):
        post_t = min(0.95 * elapsed_s, ms + 0.75 * max(0.1, elapsed_s - ms))
    else:
        post_t = 0.88 * elapsed_s

    picks = [
        ("Baseline (stage-truth window)", _drag_pick_preview_index(baseline_t, elapsed_s, len(preview_paths))),
        ("Steady-state (stage-truth window)", _drag_pick_preview_index(steady_t, elapsed_s, len(preview_paths))),
        ("Post-stop quiet segment", _drag_pick_preview_index(post_t, elapsed_s, len(preview_paths))),
    ]
    used: set[int] = set()
    selected: list[tuple[str, Path]] = []
    for label, idx in picks:
        j = min(max(int(idx), 0), len(preview_paths) - 1)
        while j in used and j + 1 < len(preview_paths):
            j += 1
        if j in used:
            j = max(0, min(len(preview_paths) - 1, j - 1))
        used.add(j)
        selected.append((label, preview_paths[j]))
    return selected


def _drag_reference_line_x_px(summary: dict[str, Any], trace_csv: Path | None) -> float | None:
    diagnostics = summary.get("diagnostics") or {}
    x = _parse_float(diagnostics.get("baseline_position_px"))
    if x is not None and math.isfinite(x):
        return float(x)
    cols = _read_csv_columns(trace_csv)
    t = cols.get("video_time_rel_s")
    y = cols.get("axis_px")
    if t is None or y is None or len(t) == 0 or len(y) == 0:
        return None
    b0 = _drag_to_video_rel_s(summary, _parse_float(diagnostics.get("baseline_start_s")))
    b1 = _drag_to_video_rel_s(summary, _parse_float(diagnostics.get("baseline_end_s")))
    mask = (t >= float(b0)) & (t <= float(b1)) if isinstance(b0, float) and isinstance(b1, float) else None
    if mask is not None and np.any(mask):
        return float(np.nanmedian(y[mask]))
    return float(np.nanmedian(y))


def _drag_load_trajectory_numeric(path: Path | None) -> dict[str, np.ndarray]:
    """Load trajectory CSV including leading '#' metadata lines."""
    if path is None or not Path(path).is_file():
        return {}
    try:
        from barakuda.core.trajectory_csv_io import read_trajectory_csv

        tab = read_trajectory_csv(Path(path))
    except Exception:
        return {}
    if not tab.header or not tab.rows:
        return {}
    out: dict[str, list[float]] = {h: [] for h in tab.header}
    for row in tab.rows:
        for h in tab.header:
            out[h].append(_parse_float(row.get(h)) if row.get(h) not in (None, "") else float("nan"))
    return {k: np.asarray(v, dtype=np.float64) for k, v in out.items()}


def _drag_run_json_tracking_roi(summary: dict[str, Any]) -> tuple[float, float, float, float] | None:
    run = summary.get("run_json") or {}
    roi = (run.get("config") or {}).get("tracking", {}).get("roi")
    if not roi or len(roi) < 4:
        return None
    try:
        x, y, w, h = (float(roi[0]), float(roi[1]), float(roi[2]), float(roi[3]))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return x, y, w, h


def _drag_axis_key(summary: dict[str, Any]) -> str:
    d = summary.get("diagnostics") or {}
    ax = str(d.get("drag_analysis_axis") or "").strip().lower()
    if ax in ("x", "y"):
        return ax
    run = summary.get("run_json") or {}
    post = (run.get("config") or {}).get("postprocess") or {}
    ax2 = str(post.get("drag_axis") or "x").strip().lower()
    return ax2 if ax2 in ("x", "y") else "x"


def _drag_rel_time_for_preview_index(idx: int, n: int, elapsed_s: float) -> float:
    if n <= 1:
        return 0.0
    return (float(idx) / float(n - 1)) * float(elapsed_s)


def _drag_roi_origin_at_trajectory_row(traj: dict[str, np.ndarray], row: int, summary: dict[str, Any]) -> tuple[float, float]:
    if "roi_x" in traj and "roi_y" in traj and row < len(traj["roi_x"]):
        return float(traj["roi_x"][row]), float(traj["roi_y"][row])
    r = _drag_run_json_tracking_roi(summary)
    if r:
        return r[0], r[1]
    return 0.0, 0.0


def _drag_pick_trajectory_row_for_preview(
    traj: dict[str, np.ndarray],
    preview_idx: int,
    n_previews: int,
    summary: dict[str, Any],
) -> int:
    frames = traj.get("frame")
    if frames is not None and len(frames) and n_previews > 1:
        f0 = float(np.nanmin(frames))
        f1 = float(np.nanmax(frames))
        f_tar = f0 + (f1 - f0) * (float(preview_idx) / float(n_previews - 1))
        return int(np.nanargmin(np.abs(frames - f_tar)))

    t_rel = traj.get("video_time_rel_s")
    t_raw = traj.get("t_s")
    t_arr = t_rel if t_rel is not None and len(t_rel) else t_raw
    if t_arr is None or len(t_arr) == 0:
        return 0
    t_series = np.asarray(t_arr, dtype=np.float64)
    if np.nanmin(t_series) > 500.0:
        t_series = t_series - float(_drag_video_time_origin_s(summary))
    elif np.nanmin(t_series) > 1.0 and np.nanmax(t_series) > float(np.nanmin(t_series)) + 10.0:
        t_series = t_series - float(np.nanmin(t_series))

    diagnostics = summary.get("diagnostics") or {}
    elapsed = _parse_float(diagnostics.get("elapsed_time_s"))
    elapsed_s = float(elapsed) if elapsed is not None and elapsed > 0 else float(max(1, n_previews - 1))
    t_q = _drag_rel_time_for_preview_index(preview_idx, n_previews, elapsed_s)
    return int(np.nanargmin(np.abs(t_series - t_q)))


def _drag_shared_cover_reference_line(
    summary: dict[str, Any],
    preview_paths: list[Path],
    trajectory_csv: Path | None,
    trace_csv: Path | None,
) -> tuple[str, float] | None:
    """
    Shared equilibrium reference in full-frame image pixels for the baseline preview instant.

    Returns ("v", x_px) for a vertical line (drag along x) or ("h", y_px) for horizontal (drag along y).
    """
    if not preview_paths:
        return None
    selected = _drag_select_stage_truth_preview_paths(summary, preview_paths)
    baseline_path = selected[0][1]
    try:
        preview_idx = next(i for i, p in enumerate(preview_paths) if Path(p).resolve() == Path(baseline_path).resolve())
    except StopIteration:
        preview_idx = 0
    n_prev = len(preview_paths)
    axis = _drag_axis_key(summary)

    traj_path = Path(trajectory_csv) if trajectory_csv else None
    traj = _drag_load_trajectory_numeric(traj_path) if (traj_path and traj_path.is_file()) else {}
    if traj and "x_px" in traj and "y_px" in traj:
        ri = _drag_pick_trajectory_row_for_preview(traj, preview_idx, n_prev, summary)
        ri = max(0, min(ri, len(traj["x_px"]) - 1))
        rx, ry = _drag_roi_origin_at_trajectory_row(traj, ri, summary)
        x_tr = float(traj["x_px"][ri])
        y_tr = float(traj["y_px"][ri])
        if axis == "x":
            return ("v", float(rx + x_tr))
        return ("h", float(ry + y_tr))

    diagnostics = summary.get("diagnostics") or {}
    elapsed = _parse_float(diagnostics.get("elapsed_time_s"))
    elapsed_s = float(elapsed) if elapsed is not None and elapsed > 0 else float(max(1, n_prev - 1))
    t_q = _drag_rel_time_for_preview_index(preview_idx, n_prev, elapsed_s)
    cols = _read_csv_columns(trace_csv)
    t = cols.get("video_time_rel_s")
    axp = cols.get("axis_px")
    if t is not None and axp is not None and len(t) and len(axp):
        finite = np.isfinite(t) & np.isfinite(axp)
        if np.any(finite):
            t2 = t[finite]
            a2 = axp[finite]
            order = np.argsort(t2)
            t2 = t2[order]
            a2 = a2[order]
            t_qc = float(np.clip(t_q, float(t2[0]), float(t2[-1])))
            val = float(np.interp(t_qc, t2, a2))
            r = _drag_run_json_tracking_roi(summary)
            if r:
                if axis == "x":
                    return ("v", float(r[0] + val))
                return ("h", float(r[1] + val))
            if axis == "x":
                return ("v", float(val))
            return ("h", float(val))

    x_roi = _drag_reference_line_x_px(summary, trace_csv)
    if x_roi is None:
        return None
    r = _drag_run_json_tracking_roi(summary)
    if r:
        if axis == "x":
            return ("v", float(r[0] + x_roi))
        return ("h", float(r[1] + x_roi))
    if axis == "x":
        return ("v", float(x_roi))
    return ("h", float(x_roi))


def _drag_crop_pad_center_vertical_line(
    img: np.ndarray,
    x_ref_full: float,
    *,
    crop_width_frac: float = 0.36,
) -> tuple[np.ndarray, float]:
    """
    Pad horizontally then crop so the reference x sits near the horizontal center of the crop.

    Returns (cropped_image, x_line_in_crop) for axvline after imshow.
    """
    if img.ndim < 2:
        return img, 0.0
    h, w = int(img.shape[0]), int(img.shape[1])
    if w <= 1:
        return img, 0.0
    cw = int(max(120, min(w, round(float(w) * crop_width_frac))))
    half = cw // 2
    xr = float(np.clip(x_ref_full, 0.0, float(w - 1)))
    pad_l = max(0, int(math.ceil(half - xr)))
    xr_pad = xr + float(pad_l)
    wp = w + pad_l
    pad_r = max(0, int(math.ceil(xr_pad + float(cw - half) - float(wp))))
    if img.ndim == 2:
        padded = np.pad(img, ((0, 0), (pad_l, pad_r)), mode="edge")
    else:
        padded = np.pad(img, ((0, 0), (pad_l, pad_r), (0, 0)), mode="edge")
    Wp = int(padded.shape[1])
    x0 = int(round(xr_pad - half))
    x0 = max(0, min(x0, Wp - cw))
    x1 = x0 + cw
    cropped = padded[:, x0:x1] if img.ndim == 2 else padded[:, x0:x1, :]
    return cropped, float(xr_pad - float(x0))


def _drag_crop_pad_center_horizontal_line(
    img: np.ndarray,
    y_ref_full: float,
    *,
    crop_height_frac: float = 0.36,
) -> tuple[np.ndarray, float]:
    """Pad vertically then crop so reference y is near the vertical center of the crop (imshow row index, top=0)."""
    if img.ndim < 2:
        return img, 0.0
    h, w = int(img.shape[0]), int(img.shape[1])
    if h <= 1:
        return img, 0.0
    ch = int(max(120, min(h, round(float(h) * crop_height_frac))))
    half = ch // 2
    yr = float(np.clip(y_ref_full, 0.0, float(h - 1)))
    pad_t = max(0, int(math.ceil(half - yr)))
    yr_pad = yr + float(pad_t)
    hp = h + pad_t
    pad_b = max(0, int(math.ceil(yr_pad + float(ch - half) - float(hp))))
    if img.ndim == 2:
        padded = np.pad(img, ((pad_t, pad_b), (0, 0)), mode="edge")
    else:
        padded = np.pad(img, ((pad_t, pad_b), (0, 0), (0, 0)), mode="edge")
    Hp = int(padded.shape[0])
    y0 = int(round(yr_pad - half))
    y0 = max(0, min(y0, Hp - ch))
    y1 = y0 + ch
    cropped = padded[y0:y1, :] if img.ndim == 2 else padded[y0:y1, :, :]
    return cropped, float(yr_pad - float(y0))


def _drag_full_bead_xy_at_preview_index(
    summary: dict[str, Any],
    traj: dict[str, np.ndarray],
    trace_csv: Path | None,
    preview_idx: int,
    n_prev: int,
) -> tuple[float, float] | None:
    """Bead center in full-frame image pixels for the preview index (trajectory or annotated trace)."""
    if traj and "x_px" in traj and "y_px" in traj and len(traj["x_px"]):
        ri = _drag_pick_trajectory_row_for_preview(traj, preview_idx, n_prev, summary)
        ri = max(0, min(ri, len(traj["x_px"]) - 1))
        rx, ry = _drag_roi_origin_at_trajectory_row(traj, ri, summary)
        return float(rx + float(traj["x_px"][ri])), float(ry + float(traj["y_px"][ri]))
    cols = _read_csv_columns(trace_csv)
    t = cols.get("video_time_rel_s")
    axp = cols.get("axis_px")
    if t is None or axp is None or len(t) == 0:
        return None
    diagnostics = summary.get("diagnostics") or {}
    elapsed = _parse_float(diagnostics.get("elapsed_time_s"))
    elapsed_s = float(elapsed) if elapsed is not None and elapsed > 0 else float(max(1, n_prev - 1))
    t_q = _drag_rel_time_for_preview_index(preview_idx, n_prev, elapsed_s)
    finite = np.isfinite(t) & np.isfinite(axp)
    if not np.any(finite):
        return None
    t2 = t[finite]
    a2 = axp[finite]
    order = np.argsort(t2)
    t2 = t2[order]
    a2 = a2[order]
    t_qc = float(np.clip(t_q, float(t2[0]), float(t2[-1])))
    val = float(np.interp(t_qc, t2, a2))
    r = _drag_run_json_tracking_roi(summary)
    if not r:
        return None
    axis = _drag_axis_key(summary)
    if axis == "x":
        return float(r[0] + val), float(r[1] + 0.5 * r[3])
    return float(r[0] + 0.5 * r[2]), float(r[1] + val)


def _drag_crop_vertical_ref_bead_fallback(
    img: np.ndarray,
    x_ref_full: float,
    bead_x_full: float,
    bead_y_full: float,
    *,
    margin_frac: float = 0.06,
    crop_width_fracs: tuple[float, ...] = (0.28, 0.38, 0.50, 0.64, 0.82, 1.0),
) -> tuple[np.ndarray, float, float, float]:
    """
    Crop columns centered on x_ref; widen until bead sits inside horizontal margins (or full width).

    Returns (cropped_image, x_line_in_crop, bead_x_in_crop, bead_y_in_crop) for imshow + scatter.
    """
    if img.ndim < 2:
        return img, 0.0, 0.0, 0.0
    h, w = int(img.shape[0]), int(img.shape[1])
    if w <= 1:
        return img, 0.0, 0.0, 0.0
    xr = float(np.clip(x_ref_full, 0.0, float(w - 1)))
    bx = float(np.clip(bead_x_full, 0.0, float(w - 1)))
    by = float(np.clip(bead_y_full, 0.0, float(h - 1)))

    def _attempt(crop_frac: float) -> tuple[np.ndarray, float, float, float]:
        cw = int(max(96, min(w, round(float(w) * crop_frac))))
        half = cw // 2
        pad_l = max(0, int(math.ceil(half - xr)))
        xr_pad = xr + float(pad_l)
        wp = w + pad_l
        pad_r = max(0, int(math.ceil(xr_pad + float(cw - half) - float(wp))))
        if img.ndim == 2:
            padded = np.pad(img, ((0, 0), (pad_l, pad_r)), mode="edge")
        else:
            padded = np.pad(img, ((0, 0), (pad_l, pad_r), (0, 0)), mode="edge")
        Wp = int(padded.shape[1])
        x0 = int(round(xr_pad - half))
        x0 = max(0, min(x0, Wp - cw))
        cropped = padded[:, x0 : x0 + cw] if img.ndim == 2 else padded[:, x0 : x0 + cw, :]
        x_line = float(xr_pad - float(x0))
        bx_crop = bx + float(pad_l) - float(x0)
        return cropped, x_line, bx_crop, by

    best: tuple[np.ndarray, float, float, float] | None = None
    for frac in crop_width_fracs:
        cr, xl, bxc, byc = _attempt(frac)
        ch, cw = int(cr.shape[0]), int(cr.shape[1])
        if cw < 32 or ch < 32:
            continue
        ok = margin_frac * cw <= bxc <= (1.0 - margin_frac) * cw
        if ok:
            return cr, xl, bxc, byc
        best = (cr, xl, bxc, byc)
    return best if best is not None else _attempt(1.0)


def _drag_crop_horizontal_ref_bead_fallback(
    img: np.ndarray,
    y_ref_full: float,
    bead_x_full: float,
    bead_y_full: float,
    *,
    margin_frac: float = 0.06,
    crop_height_fracs: tuple[float, ...] = (0.28, 0.38, 0.50, 0.64, 0.82, 1.0),
) -> tuple[np.ndarray, float, float, float]:
    """Crop rows centered on y_ref; widen until bead sits inside vertical margins."""
    if img.ndim < 2:
        return img, 0.0, 0.0, 0.0
    h, w = int(img.shape[0]), int(img.shape[1])
    if h <= 1:
        return img, 0.0, 0.0, 0.0
    yr = float(np.clip(y_ref_full, 0.0, float(h - 1)))
    bx = float(np.clip(bead_x_full, 0.0, float(w - 1)))
    by = float(np.clip(bead_y_full, 0.0, float(h - 1)))

    def _attempt(crop_frac: float) -> tuple[np.ndarray, float, float, float]:
        ch = int(max(96, min(h, round(float(h) * crop_frac))))
        half = ch // 2
        pad_t = max(0, int(math.ceil(half - yr)))
        yr_pad = yr + float(pad_t)
        hp = h + pad_t
        pad_b = max(0, int(math.ceil(yr_pad + float(ch - half) - float(hp))))
        if img.ndim == 2:
            padded = np.pad(img, ((pad_t, pad_b), (0, 0)), mode="edge")
        else:
            padded = np.pad(img, ((pad_t, pad_b), (0, 0), (0, 0)), mode="edge")
        Hp = int(padded.shape[0])
        y0 = int(round(yr_pad - half))
        y0 = max(0, min(y0, Hp - ch))
        cropped = padded[y0 : y0 + ch, :] if img.ndim == 2 else padded[y0 : y0 + ch, :, :]
        y_line = float(yr_pad - float(y0))
        by_crop = by + float(pad_t) - float(y0)
        bx_crop = bx
        return cropped, y_line, bx_crop, by_crop

    best: tuple[np.ndarray, float, float, float] | None = None
    for frac in crop_height_fracs:
        cr, yl, bxc, byc = _attempt(frac)
        ch, cw = int(cr.shape[0]), int(cr.shape[1])
        if cw < 32 or ch < 32:
            continue
        ok = margin_frac * ch <= byc <= (1.0 - margin_frac) * ch
        if ok:
            return cr, yl, bxc, byc
        best = (cr, yl, bxc, byc)
    return best if best is not None else _attempt(1.0)


def _drag_humanize_timing_source(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return "n/a"
    if ";" in s:
        s = s.split(";", 1)[0].strip()
    if "timestamps_csv:" in s:
        s = s.replace("timestamps_csv:", "Timestamps: ")
    if len(s) > 64:
        s = s[:61] + "…"
    return s


def _drag_humanize_kappa_source(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return "n/a"
    if "brownian_calibration" in s.lower():
        return "Brownian calibration (trap stiffness from paired run)"
    if len(s) > 56:
        return s[:53] + "…"
    return s


def _drag_format_rel_time_window(summary: dict[str, Any], start_key: str, end_key: str) -> str:
    diagnostics = summary.get("diagnostics") or {}
    t0 = _drag_to_video_rel_s(summary, _parse_float(diagnostics.get(start_key)))
    t1 = _drag_to_video_rel_s(summary, _parse_float(diagnostics.get(end_key)))
    if not isinstance(t0, float) or not isinstance(t1, float):
        return "n/a"
    return f"{t0:.2f}–{t1:.2f} s (from video start)"


def _drag_format_motion_window(summary: dict[str, Any]) -> str:
    markers = _drag_resolve_primary_markers(summary, windows_csv=None, stage_trace_path=None)
    raw = markers.get("raw") or {}
    ms = raw.get("motion_start_s")
    me = raw.get("motion_stop_s")
    if isinstance(ms, float) and isinstance(me, float) and me > ms:
        return f"{ms:.2f}–{me:.2f} s (stage truth)"
    return "n/a"


def _drag_pick_important_warning(summary: dict[str, Any]) -> str | None:
    warnings = [str(w).strip() for w in (summary.get("warnings") or []) if str(w).strip()]
    if not warnings:
        return None
    phys = [w for w in warnings if "PHYSICS_WARNING" in w.upper() or "FAIL" in w.upper()]
    pick = phys[0] if phys else warnings[0]
    pick = pick.replace("PHYSICS_WARNING:", "").strip()
    if len(pick) > 120:
        pick = pick[:117] + "…"
    return pick


def _render_drag_cover_page(
    pdf,
    summary: dict[str, Any],
    *,
    page_counter: PageCounter | None = None,
) -> None:
    """Drag-specific cover: summary table only (no video preview strip)."""
    import matplotlib.pyplot as plt

    left_rows, right_rows = _drag_cover_rows(summary)
    title = f"DRAG Item Report: {summary.get('item_id')}"
    subtitle = "Stage-truth-first diagnostic report (report-only rebuild)"

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, page_note=None, cover=True, page_counter=page_counter)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.50, 0.812, "DRAG Summary", fontsize=10.5, color=ACCENT_COLOR, fontweight="bold", ha="center")
    ax.text(0.50, 0.768, title, fontsize=24, fontweight="bold", color=TEXT_COLOR, ha="center")
    ax.text(0.50, 0.729, subtitle, fontsize=11.2, color=MUTED_COLOR, ha="center")
    ax.text(
        0.50,
        0.688,
        "Primary truth is stage timing; trajectory onset is shown as QC-only.",
        fontsize=10.4,
        color=TEXT_COLOR,
        ha="center",
        wrap=True,
    )

    table_rows = _build_single_cover_table_rows(title, left_rows, right_rows)
    # Larger table band when no preview strip: balanced whitespace above/below.
    bounds = (DRAG_CONTENT_LEFT, 0.14, DRAG_CONTENT_RIGHT - DRAG_CONTENT_LEFT, 0.52)
    _add_panel(fig, bounds, facecolor=CARD_BG)
    ax_tbl = fig.add_axes([bounds[0] + 0.015, bounds[1] + 0.020, bounds[2] - 0.030, bounds[3] - 0.040])
    ax_tbl.axis("off")
    wrapped_rows = [[_cover_cell_text(r[0]), _cover_cell_text(r[1])] for r in table_rows]
    table = ax_tbl.table(
        cellText=wrapped_rows,
        colLabels=["Field", "Value"],
        cellLoc="left",
        colLoc="left",
        colWidths=[0.36, 0.64],
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    table.auto_set_font_size(False)
    nrows = len(wrapped_rows) + 1
    row_h = 0.98 / max(1, nrows)
    for (row_idx, col_idx), cell in table.get_celld().items():
        text_obj = cell.get_text()
        cell.PAD = 0.13
        cell.set_edgecolor(LINE_COLOR)
        cell.set_linewidth(0.45)
        text_obj.set_wrap(True)
        text_obj.set_ha("left")
        text_obj.set_va("center")
        if row_idx == 0:
            cell.set_facecolor(BRAND_COLOR)
            text_obj.set_color("white")
            text_obj.set_fontweight("bold")
            text_obj.set_fontsize(10.3)
        else:
            cell.set_facecolor("white" if row_idx % 2 else PANEL_BG)
            text_obj.set_color(TEXT_COLOR)
            text_obj.set_fontsize(9.2 if col_idx == 0 else 9.0)
            if col_idx == 0:
                text_obj.set_fontweight("bold")
        cell.set_height(row_h)

    pdf.savefig(fig)
    plt.close(fig)


def _render_drag_method_conditions_page(pdf, summary: dict[str, Any], *, page_counter: PageCounter | None = None) -> None:
    diagnostics = summary.get("diagnostics") or {}
    metrics = summary.get("metrics") or {}
    um_px = _parse_float(metrics.get("um_per_px"))
    lateral_nm = f"{um_px * 1000.0:.1f} nm" if um_px is not None else "n/a"
    bd = _parse_float(metrics.get("bead_diameter_um"))
    bead_s = f"{bd:.1f} µm" if bd is not None else "n/a"
    tc = _parse_float(metrics.get("temperature_c"))
    temp_s = f"{tc:.1f} °C" if tc is not None else "n/a"
    req = diagnostics.get("drag_anchor_mode_requested")
    eff = diagnostics.get("drag_anchor_mode_effective")
    anchor_s = f"{req} → {eff}" if req is not None or eff is not None else "n/a"
    onset_v = _parse_float(diagnostics.get("detected_stage_start_video_s"))
    onset_rel = _drag_to_video_rel_s(summary, onset_v) if onset_v is not None else None
    onset_s = f"{onset_rel:.2f} s (QC-only)" if isinstance(onset_rel, float) else "n/a (QC-only)"

    timing_rows = [
        ["Timing", _drag_humanize_timing_source(diagnostics.get("timing_source"))],
        ["Anchor (req. → eff.)", str(anchor_s)],
        ["Windows source", _wrap(diagnostics.get("primary_timing_source_for_windows"), 40)],
        ["Motion (stage)", _drag_format_motion_window(summary)],
        ["Baseline", _drag_format_rel_time_window(summary, "baseline_start_s", "baseline_end_s")],
        ["Steady", _drag_format_rel_time_window(summary, "steady_start_s", "steady_end_s")],
        ["Onset QC", str(onset_s)],
    ]
    cond_rows = [
        ["Bead Ø", bead_s],
        ["Temp.", temp_s],
        ["Lateral scale", lateral_nm],
        ["κ source", _drag_humanize_kappa_source(diagnostics.get("kappa_source"))],
    ]
    qc_rows = [
        ["Alignment", _wrap(diagnostics.get("alignment_status"), 40)],
        [
            "Gates (phys / det / verdict)",
            _wrap(
                f"{diagnostics.get('physics_primary_gate')} / {diagnostics.get('detection_qc_gate')} / {diagnostics.get('final_drag_verdict')}",
                40,
            ),
        ],
    ]
    warn = _drag_pick_important_warning(summary)

    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Method + Conditions + Compact QC", subtitle="Compact blocks; audit on disk", page_counter=page_counter)

    def _card(bounds: tuple[float, float, float, float], title: str, rows: list[list[str]]) -> None:
        _add_panel(fig, bounds, facecolor=CARD_BG)
        fig.text(
            bounds[0] + 0.012,
            bounds[1] + bounds[3] - 0.016,
            title,
            fontsize=10.2,
            fontweight="bold",
            color=BRAND_COLOR,
            family=FONT_FAMILY,
            va="top",
            ha="left",
        )
        ax_tbl = fig.add_axes([bounds[0] + 0.02, bounds[1] + 0.016, bounds[2] - 0.04, bounds[3] - 0.052])
        ax_tbl.axis("off")
        tbl = ax_tbl.table(
            cellText=rows,
            colLabels=["Field", "Value"],
            cellLoc="left",
            colLoc="left",
            colWidths=[0.34, 0.66],
            bbox=[0, 0, 1, 1],
        )
        _style_table(tbl, body_font_size=8.2, header_font_size=9.2)

    _w = DRAG_CONTENT_RIGHT - DRAG_CONTENT_LEFT
    _card((DRAG_CONTENT_LEFT, 0.565, _w, 0.265), "Timing / anchoring", timing_rows)
    _card((DRAG_CONTENT_LEFT, 0.365, _w, 0.165), "Conditions / calibration", cond_rows)
    _card((DRAG_CONTENT_LEFT, 0.145, _w, 0.185), "QC / verdict", qc_rows)
    if warn:
        fig.text(
            DRAG_CONTENT_LEFT + 0.01,
            0.065,
            f"Note: {warn}",
            fontsize=8.0,
            color=MUTED_COLOR,
            family=FONT_FAMILY,
            ha="left",
            va="top",
            wrap=True,
            style="italic",
            bbox=dict(boxstyle="round,pad=0.35", fc="#FAFAFA", ec=LINE_COLOR, lw=0.35, alpha=0.95),
        )

    pdf.savefig(fig)
    plt.close(fig)


def _render_drag_stage_diagnostics_pages(
    pdf,
    summary: dict[str, Any],
    *,
    trace_csv: Path | None,
    windows_csv: Path | None,
    stage_trace_path: Path | None,
    page_counter: PageCounter | None = None,
) -> None:
    """Stage position and velocity stacked vertically; captions in dedicated rows; legend in bottom figure zone."""
    import matplotlib.pyplot as plt

    markers = _drag_resolve_primary_markers(summary, windows_csv=windows_csv, stage_trace_path=stage_trace_path)
    prof = _drag_stage_profile_from_saved_data(
        summary,
        stage_trace_path=stage_trace_path,
        trace_csv=None,
        markers=markers,
    )

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Secondary diagnostics", subtitle="Stage kinematics", page_counter=page_counter)
    gs = fig.add_gridspec(
        4,
        1,
        left=DRAG_CONTENT_LEFT,
        right=DRAG_CONTENT_RIGHT,
        top=DRAG_STACK_TOP,
        bottom=DRAG_STACK_BOTTOM,
        height_ratios=[2.0, 0.42, 2.0, 0.42],
        hspace=0.46,
    )
    ax_pos = fig.add_subplot(gs[0, 0])
    ax_cap1 = fig.add_subplot(gs[1, 0])
    ax_vel = fig.add_subplot(gs[2, 0], sharex=ax_pos)
    ax_cap2 = fig.add_subplot(gs[3, 0])
    for ax in (ax_pos, ax_vel):
        ax.set_facecolor(PANEL_BG)
        ax.grid(True, linestyle="--", linewidth=0.5, color=LINE_COLOR)
    raw = markers.get("raw") or {}
    derived = markers.get("derived") or {}
    diagnostics = summary.get("diagnostics") or {}
    v_rep = _parse_float(diagnostics.get("actual_speed_um_s"))
    if prof is None:
        ax_pos.text(0.5, 0.5, "Stage position unavailable.", ha="center", va="center", color=MUTED_COLOR, family=FONT_FAMILY)
        ax_vel.text(0.5, 0.5, "Stage velocity unavailable.", ha="center", va="center", color=MUTED_COLOR, family=FONT_FAMILY)
        ax_vel.set_xlabel("Time from video start [s]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
    else:
        t, pos, _v = prof
        ax_pos.plot(t, pos, linewidth=1.6, color=PLOT_COLOR, label="Stage position")
        ms = raw.get("motion_start_s")
        mrc = derived.get("motion_running_confirmed_s")
        dec = derived.get("deceleration_start_s")
        me = raw.get("motion_stop_s")
        if isinstance(ms, float) and isinstance(mrc, float) and mrc > ms:
            ax_pos.axvspan(ms, mrc, color="#E3F2FD", alpha=0.25, label="Acceleration")
        if isinstance(mrc, float) and isinstance(dec, float) and dec > mrc:
            ax_pos.axvspan(mrc, dec, color="#E8F5E9", alpha=0.24, label="Steady-speed")
        if isinstance(dec, float) and isinstance(me, float) and me > dec:
            ax_pos.axvspan(dec, me, color="#FCE4EC", alpha=0.24, label="Deceleration")
        _drag_plot_markers(ax_pos, markers, include_windows=True)
        ax_pos.set_ylabel("Stage position [µm]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
        _t, _p, v = prof
        ax_vel.plot(_t, v, linewidth=1.6, color=PLOT_COLOR, label="Stage velocity")
        if v_rep is not None and math.isfinite(float(v_rep)):
            ax_vel.axhline(
                float(v_rep),
                color="#C62828",
                linestyle="--",
                linewidth=1.35,
                zorder=4,
                label="Steady speed (summary)",
            )
        _drag_plot_markers(ax_vel, markers, include_windows=True)
        ax_vel.set_ylabel("Stage velocity [µm/s]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
        ax_vel.set_xlabel("Time from video start [s]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)

    ax_pos.tick_params(labelbottom=False)
    ax_pos.set_xlabel("")
    ax_pos.margins(x=0.03, y=0.07)
    ax_vel.margins(x=0.03, y=0.07)
    ax_pos.tick_params(axis="y", which="major", pad=5)
    ax_vel.tick_params(axis="both", which="major", pad=4)

    _drag_caption_row_text(
        ax_cap1,
        "Stage position with motion-phase shading; window boundaries follow stage truth and match the bead page.",
    )
    _drag_caption_row_text(
        ax_cap2,
        "Stage velocity with summary steady-speed reference (dashed); markers repeat stage truth and QC-only trajectory timing.",
    )
    _drag_figure_legend_from_axes(fig, (ax_pos, ax_vel), ncol=4)
    pdf.savefig(fig)
    plt.close(fig)


def _render_drag_bead_diagnostics_pages(
    pdf,
    summary: dict[str, Any],
    *,
    trace_csv: Path | None,
    windows_csv: Path | None,
    stage_trace_path: Path | None,
    page_counter: PageCounter | None = None,
) -> None:
    """Primary diagnostic: full bead trace over full timeline, steady detail below; captions + bottom legend; vertical stack only."""
    import matplotlib.pyplot as plt

    markers = _drag_resolve_primary_markers(summary, windows_csv=windows_csv, stage_trace_path=stage_trace_path)
    t, y_um = _drag_trace_time_and_signal_um(summary, trace_csv)
    diagnostics = summary.get("diagnostics") or {}
    offset_reported = _parse_float(diagnostics.get("offset_um"))

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_brand_header(fig, "Main diagnostics", subtitle="Bead response vs stage-truth windows", page_counter=page_counter)

    gs = fig.add_gridspec(
        4,
        1,
        left=DRAG_CONTENT_LEFT,
        right=DRAG_CONTENT_RIGHT,
        top=DRAG_STACK_TOP,
        bottom=DRAG_STACK_BOTTOM,
        height_ratios=[2.38, 0.46, 1.08, 0.46],
        hspace=0.44,
    )
    ax_bead = fig.add_subplot(gs[0, 0])
    ax_cap1 = fig.add_subplot(gs[1, 0])
    ax_steady = fig.add_subplot(gs[2, 0])
    ax_cap2 = fig.add_subplot(gs[3, 0])
    ax_bead.set_facecolor(PANEL_BG)
    ax_steady.set_facecolor(PANEL_BG)
    ax_bead.grid(True, linestyle="--", linewidth=0.5, color=LINE_COLOR)
    ax_steady.grid(True, linestyle="--", linewidth=0.5, color=LINE_COLOR)

    if t is not None and y_um is not None and len(t):
        raw = markers.get("raw") or {}
        b0 = raw.get("baseline_start_s")
        b1 = raw.get("baseline_end_s")
        s0 = raw.get("steady_start_s")
        s1 = raw.get("steady_end_s")
        baseline_mask = (t >= float(b0)) & (t <= float(b1)) if isinstance(b0, float) and isinstance(b1, float) else None
        center = float(np.nanmedian(y_um[baseline_mask])) if (baseline_mask is not None and np.any(baseline_mask)) else float(np.nanmedian(y_um))
        y_c = y_um - center
        ax_bead.plot(t, y_c, linewidth=1.2, color="#0D47A1", label="Bead offset (baseline-centered)")
        ax_bead.axhline(0.0, color="#424242", linestyle=":", linewidth=1.15, zorder=3, label="Baseline mean (0)")
        steady_mean: float | None = None
        if isinstance(s0, float) and isinstance(s1, float):
            sm = (t >= float(s0)) & (t <= float(s1))
            if np.any(sm):
                steady_mean = float(np.nanmedian(y_c[sm]))
                ax_bead.axhline(
                    steady_mean,
                    color="#AD1457",
                    linestyle="--",
                    linewidth=1.25,
                    zorder=3,
                    label="Steady-window mean",
                )
        if steady_mean is not None:
            mid_t = 0.5 * (float(s0) + float(s1)) if isinstance(s0, float) and isinstance(s1, float) else float(t[len(t) // 2])
            y0, y1 = (0.0, steady_mean) if steady_mean >= 0.0 else (steady_mean, 0.0)
            ax_bead.annotate(
                "",
                xy=(mid_t, y1),
                xytext=(mid_t, y0),
                arrowprops=dict(arrowstyle="<->", color="#37474F", lw=1.0, shrinkA=0, shrinkB=0),
            )
            ax_bead.text(
                mid_t,
                0.5 * (y0 + y1),
                r"$\Delta x$",
                fontsize=8.5,
                ha="center",
                va="center",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=LINE_COLOR, lw=0.4, alpha=0.92),
            )
        if offset_reported is not None and math.isfinite(float(offset_reported)):
            ax_bead.text(
                0.99,
                0.03,
                f"|offset| (summary): {abs(float(offset_reported)):.3f} µm",
                transform=ax_bead.transAxes,
                ha="right",
                va="bottom",
                fontsize=7.2,
                color=MUTED_COLOR,
                family=FONT_FAMILY,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=LINE_COLOR, lw=0.35, alpha=0.88),
            )
        _drag_plot_markers(ax_bead, markers, include_windows=True)
        ax_bead.set_ylabel("Bead position [µm]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
        ax_bead.set_xlabel("")
        ax_bead.tick_params(labelbottom=False)
        ax_bead.margins(x=0.03, y=0.08)
        ax_bead.tick_params(axis="y", which="major", pad=5)

        # Steady-window detail: zoom + numeric summary
        if isinstance(s0, float) and isinstance(s1, float) and (s1 > s0):
            sm = (t >= float(s0)) & (t <= float(s1))
            if np.any(sm):
                t_s = t[sm]
                y_s = y_c[sm]
                ax_steady.plot(t_s, y_s, linewidth=1.35, color="#0D47A1", label="Bead offset")
                ax_steady.axhline(0.0, color="#424242", linestyle=":", linewidth=1.15, zorder=3)
                if steady_mean is not None:
                    ax_steady.axhline(steady_mean, color="#AD1457", linestyle="--", linewidth=1.2, zorder=3)
                span = float(s1 - s0)
                margin = max(0.02 * span, 1e-6)
                ax_steady.set_xlim(float(s0) - margin, float(s1) + margin)
                y_min = float(np.nanmin(y_s))
                y_max = float(np.nanmax(y_s))
                pad = max(0.12 * max(abs(y_max - y_min), 1e-9), 1e-4)
                ax_steady.set_ylim(y_min - pad, y_max + pad)
                ax_steady.margins(x=0.035, y=0.09)
                ax_steady.tick_params(axis="both", which="major", pad=4)
                ax_steady.set_title("Steady window (detail)", fontsize=9.0, fontweight="bold", color=TEXT_COLOR, family=FONT_FAMILY)
                ax_steady.set_xlabel("Time from video start [s]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
                ax_steady.set_ylabel("Bead position [µm]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
                sm_txt = f"{steady_mean:.4f}" if steady_mean is not None else "n/a"
                dx_txt = f"{abs(steady_mean):.4f}" if steady_mean is not None else "n/a"
                off_txt = f"{abs(float(offset_reported)):.4f}" if offset_reported is not None else "n/a"
                ax_steady.text(
                    0.04,
                    0.97,
                    "Medians (this window)\n"
                    f"Baseline (ref): 0 µm\n"
                    f"Steady: {sm_txt} µm\n"
                    f"|Δx| (median): {dx_txt} µm\n"
                    f"|offset| (summary): {off_txt} µm",
                    transform=ax_steady.transAxes,
                    ha="left",
                    va="top",
                    fontsize=7.1,
                    color=TEXT_COLOR,
                    family=FONT_FAMILY,
                    bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=LINE_COLOR, lw=0.4, alpha=0.92),
                )
            else:
                ax_steady.text(0.5, 0.5, "No samples in steady window.", ha="center", va="center", color=MUTED_COLOR, family=FONT_FAMILY)
                ax_steady.set_title("Steady window (detail)", fontsize=9.0, fontweight="bold", color=TEXT_COLOR, family=FONT_FAMILY)
                ax_steady.set_xlabel("Time from video start [s]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
                ax_steady.set_ylabel("Bead position [µm]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
        else:
            ax_steady.text(
                0.5,
                0.5,
                "Steady window not defined\nin saved timing.",
                ha="center",
                va="center",
                color=MUTED_COLOR,
                family=FONT_FAMILY,
            )
            ax_steady.set_title("Steady window (detail)", fontsize=9.0, fontweight="bold", color=TEXT_COLOR, family=FONT_FAMILY)
            ax_steady.set_xlabel("Time from video start [s]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
            ax_steady.set_ylabel("Bead position [µm]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)

        _drag_caption_row_text(
            ax_cap1,
            "Full-timeline bead response: baseline-centred trace with stage-truth windows and QC-only trajectory markers; "
            "Δx compares baseline and steady medians. Stage kinematics are on the next page.",
        )
        _drag_caption_row_text(
            ax_cap2,
            "Steady-window zoom with the same baseline and steady references; the box lists medians for Δx and summary offset check.",
        )
        _drag_figure_legend_from_axes(fig, (ax_bead,), ncol=3)
    else:
        ax_bead.text(0.5, 0.5, "Bead trace not available in µm.", ha="center", va="center", color=MUTED_COLOR, family=FONT_FAMILY)
        ax_bead.set_xlabel("Time from video start [s]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
        ax_bead.set_ylabel("Bead position [µm]", fontsize=FONT_SIZE_SMALL, family=FONT_FAMILY)
        ax_steady.axis("off")
        ax_steady.text(0.5, 0.5, "n/a", ha="center", va="center", color=MUTED_COLOR, family=FONT_FAMILY)
        _drag_caption_row_text(
            ax_cap1,
            "Bead response could not be loaded from saved trace artefacts; stage kinematics are on the following page.",
        )
        _drag_caption_row_text(ax_cap2, "No steady-window detail without a bead trace.")

    pdf.savefig(fig)
    plt.close(fig)


def _render_drag_compact_qc_page(pdf, summary: dict[str, Any], *, page_counter: PageCounter | None = None) -> None:
    diagnostics = summary.get("diagnostics") or {}
    artifacts = summary.get("artifacts") or {}
    windows_csv = Path(artifacts.get("drag_windows_csv")) if artifacts.get("drag_windows_csv") else None
    stage_trace_path = Path(diagnostics.get("selected_stage_trace_path")) if diagnostics.get("selected_stage_trace_path") else None
    markers = _drag_resolve_primary_markers(
        summary,
        windows_csv=windows_csv if (windows_csv and windows_csv.is_file()) else None,
        stage_trace_path=stage_trace_path if (stage_trace_path and stage_trace_path.is_file()) else None,
    )
    raw = markers.get("raw") or {}
    derived = markers.get("derived") or {}
    rows = [
        ["Expected motion start/stop (stage truth)", _wrap(f"{raw.get('motion_start_s')} s → {raw.get('motion_stop_s')} s", 52)],
        ["Baseline / steady windows", _wrap(f"{raw.get('baseline_start_s')}–{raw.get('baseline_end_s')} s; {raw.get('steady_start_s')}–{raw.get('steady_end_s')} s", 52)],
        ["Detected onset (QC-only)", _wrap(derived.get("detected_onset_qc_s"), 52)],
        ["Stage–video delta", _wrap(f"start {diagnostics.get('stage_video_start_delta_s')} s; stop {diagnostics.get('stage_video_stop_delta_s')} s", 52)],
        ["Alignment status / sanity", _wrap(f"{diagnostics.get('alignment_status')} / {diagnostics.get('alignment_sanity_flag')}", 52)],
        ["Primary physics gate", _wrap(diagnostics.get("physics_primary_gate"), 52)],
        ["Detection QC gate", _wrap(diagnostics.get("detection_qc_gate"), 52)],
        ["Final drag verdict", _wrap(diagnostics.get("final_drag_verdict"), 52)],
        ["Drag validation gate", _wrap(diagnostics.get("drag_validation_gate"), 52)],
        ["Physics status", _wrap(diagnostics.get("physics_status"), 52)],
        ["Confidence / warning", _wrap(f"{diagnostics.get('drag_physics_confidence')}; {diagnostics.get('drag_physics_warning')}", 52)],
    ]
    _render_paginated_table(
        pdf,
        "Compact QC and timing",
        ["Field", "Value"],
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
    if not drag_mode:
        preview_paths = _select_representative_preview_paths(preview_paths, max_images=6)

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
            diagnostics = summary.get("diagnostics") or {}
            page_counter.total = 5

            # Cover / summary (Drag family)
            trace_csv_p = Path(artifacts.get("drag_trace_annotated_csv")) if artifacts.get("drag_trace_annotated_csv") else None
            _render_drag_cover_page(
                pdf,
                summary,
                page_counter=page_counter,
            )

            # Theory page before diagnostics
            _render_drag_theory_page(pdf, page_counter=page_counter)

            # Method + conditions + compact QC page
            _render_drag_method_conditions_page(pdf, summary, page_counter=page_counter)

            # Stage/trace sources
            windows_csv_p = Path(artifacts.get("drag_windows_csv")) if artifacts.get("drag_windows_csv") else None
            stage_trace_p = Path(diagnostics.get("selected_stage_trace_path")) if diagnostics.get("selected_stage_trace_path") else None

            # Main diagnostic page
            _render_drag_bead_diagnostics_pages(
                pdf,
                summary,
                trace_csv=trace_csv_p if (trace_csv_p and trace_csv_p.is_file()) else None,
                windows_csv=windows_csv_p if (windows_csv_p and windows_csv_p.is_file()) else None,
                stage_trace_path=stage_trace_p if (stage_trace_p and stage_trace_p.is_file()) else None,
                page_counter=page_counter,
            )

            # Secondary compact diagnostics page
            _render_drag_stage_diagnostics_pages(
                pdf,
                summary,
                trace_csv=trace_csv_p if (trace_csv_p and trace_csv_p.is_file()) else None,
                windows_csv=windows_csv_p if (windows_csv_p and windows_csv_p.is_file()) else None,
                stage_trace_path=stage_trace_p if (stage_trace_p and stage_trace_p.is_file()) else None,
                page_counter=page_counter,
            )
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
            hist_r = artifacts.get("hist_r_csv")
            msd = artifacts.get("msd_csv")
            if hist_r or msd:
                _render_histogram_r_and_msd_page(
                    pdf,
                    hist_r,
                    msd,
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
