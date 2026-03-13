from __future__ import annotations

import json
import math
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any


PAGE_SIZE = (8.27, 11.69)
BRAND_NAME = "BARAKUDA"
REPORT_NAME = "AFM Bacteria Analysis Report"
BRAND_COLOR = "#0F3D5E"
ACCENT_COLOR = "#1F6AA5"
TEXT_COLOR = "#162534"
MUTED_COLOR = "#586574"
LINE_COLOR = "#CAD5E0"
CARD_BG = "#FFFFFF"
PANEL_BG = "#F8FBFD"


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _wrap(value: Any, width: int = 42) -> str:
    text = str(value if value not in (None, "") else "n/a")
    return textwrap.fill(text, width=width, break_long_words=False, break_on_hyphens=False)


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
    return text if text == "n/a" or not unit else f"{text} {unit}"


def _branding_asset_path(file_name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "branding" / "barakuda" / file_name


def _load_header_logo() -> Any | None:
    logo_path = _branding_asset_path("logo_dark.png")
    if not logo_path.is_file():
        return None
    try:
        import matplotlib.image as mpimg

        return mpimg.imread(logo_path)
    except Exception:
        return None


def _discover_afm_artifacts(analysis_dir: Path, base_name: str) -> dict[str, str]:
    results_dir = analysis_dir / "results"
    csv_dir = analysis_dir / "csv"
    audit_dir = analysis_dir / "audit"
    artifacts = {
        "run_json": _first_existing(audit_dir / "run.json"),
        "summary_json": _first_existing(audit_dir / f"{base_name}_summary.json"),
        "hist_json": _first_existing(audit_dir / f"{base_name}_orientation_hist.json"),
        "rods_csv": _first_existing(csv_dir / f"{base_name}_rods_props.csv"),
        "mask_png": _first_existing(results_dir / f"{base_name}_rods_mask.png"),
        "overlay_png": _first_existing(results_dir / f"{base_name}_overlay.png"),
        "contours_png": _first_existing(results_dir / f"{base_name}_contours.png"),
        "hist_raw_png": _first_existing(results_dir / f"{base_name}_orientation_hist_rad_count.png"),
        "hist_density_png": _first_existing(results_dir / f"{base_name}_orientation_hist_deg_density.png"),
        "hist_folded_png": _first_existing(results_dir / f"{base_name}_orientation_folded_hist_deg_density.png"),
        "item_pdf": _first_existing(results_dir / f"{base_name}_summary.pdf"),
    }
    return {key: str(path) for key, path in artifacts.items() if path is not None}


def build_afm_item_summary(
    *,
    analysis_dir: Path | str,
    base_name: str,
    item_id: str,
    source_input_path: str | None,
    status: str,
    run_id: str,
    batch_id: str | None,
    output_root: str | None = None,
    file_name: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    analysis_dir = Path(analysis_dir)
    artifacts = _discover_afm_artifacts(analysis_dir, base_name)
    run_json = _load_json(Path(artifacts["run_json"])) if "run_json" in artifacts else {}
    summary_json = _load_json(Path(artifacts["summary_json"])) if "summary_json" in artifacts else {}
    cellpose = dict((summary_json.get("audit") or {}).get("cellpose") or {})
    created_at = str(run_json.get("created_at") or datetime.now().isoformat(timespec="seconds"))
    return {
        "item_id": item_id,
        "status": status,
        "run_id": run_id,
        "batch_id": batch_id,
        "created_at": created_at,
        "analysis_dir": str(analysis_dir),
        "output_root": output_root,
        "source_input_path": source_input_path,
        "file_name": file_name or base_name,
        "error": error,
        "metrics": {
            "n_rods": summary_json.get("n_rods"),
            "n_labels": summary_json.get("n_labels"),
            "um_per_px": summary_json.get("afm_um_per_px"),
            "diameter_effective_px": summary_json.get("diameter_effective_px"),
            "selected_channel": summary_json.get("selected_channel"),
            "cellpose_model": summary_json.get("cellpose_model"),
        },
        "diagnostics": {
            "requested_profile": summary_json.get("compute_profile_requested", cellpose.get("requested_profile")),
            "resolved_profile": summary_json.get("compute_profile_resolved", cellpose.get("resolved_profile", summary_json.get("compute_profile"))),
            "resolved_device": summary_json.get("compute_device_resolved", cellpose.get("device")),
            "timings_ms": summary_json.get("timings_ms") or {},
        },
        "artifacts": artifacts,
    }


def _add_header(fig, title: str, subtitle: str | None = None, page_note: str | None = None) -> None:
    from matplotlib.lines import Line2D

    logo = _load_header_logo()
    if logo is not None:
        ax_logo = fig.add_axes([0.07, 0.92, 0.22, 0.05], anchor="NW")
        ax_logo.imshow(logo)
        ax_logo.axis("off")
    else:
        fig.text(0.07, 0.952, BRAND_NAME, fontsize=18, fontweight="bold", color=BRAND_COLOR)
    fig.text(0.50, 0.952, REPORT_NAME, fontsize=10.5, color=MUTED_COLOR, ha="center")
    fig.text(0.50, 0.915, title, fontsize=18.5, fontweight="bold", color=TEXT_COLOR, ha="center")
    if subtitle:
        fig.text(0.50, 0.890, subtitle, fontsize=10.0, color=MUTED_COLOR, ha="center")
    if page_note:
        fig.text(0.93, 0.952, page_note, fontsize=9, color=MUTED_COLOR, ha="right")
    fig.add_artist(Line2D([0.06, 0.94], [0.875, 0.875], transform=fig.transFigure, color=ACCENT_COLOR, linewidth=1.4))


def _render_table_page(pdf, title: str, rows: list[list[str]], *, subtitle: str | None = None, headers: list[str] | None = None) -> None:
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=PAGE_SIZE)
    fig.patch.set_facecolor("white")
    _add_header(fig, title, subtitle=subtitle)
    ax = fig.add_axes([0.07, 0.10, 0.86, 0.73])
    ax.axis("off")
    table = ax.table(
        cellText=rows,
        colLabels=headers or ["Field", "Value"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    table.auto_set_font_size(False)
    for (row_idx, col_idx), cell in table.get_celld().items():
        cell.PAD = 0.12
        cell.set_edgecolor(LINE_COLOR)
        cell.set_linewidth(0.45)
        text = cell.get_text()
        text.set_wrap(True)
        text.set_ha("left")
        if row_idx == 0:
            cell.set_facecolor(BRAND_COLOR)
            text.set_color("white")
            text.set_fontsize(10)
            text.set_fontweight("bold")
        else:
            cell.set_facecolor(PANEL_BG if row_idx % 2 == 0 else CARD_BG)
            text.set_color(TEXT_COLOR)
            text.set_fontsize(9)
            if col_idx == 0:
                text.set_fontweight("bold")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _render_image_pages(pdf, title: str, entries: list[tuple[str, Path]], *, items_per_page: int = 2) -> None:
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    if not entries:
        return
    chunks = [entries[i : i + items_per_page] for i in range(0, len(entries), items_per_page)]
    for idx, chunk in enumerate(chunks, start=1):
        fig, axes = plt.subplots(len(chunk), 1, figsize=PAGE_SIZE)
        fig.patch.set_facecolor("white")
        _add_header(fig, title, page_note=(f"Page {idx}/{len(chunks)}" if len(chunks) > 1 else None))
        fig.subplots_adjust(top=0.81, left=0.08, right=0.95, bottom=0.08, hspace=0.34)
        flat_axes = list(axes if isinstance(axes, (list, tuple)) else getattr(axes, "flatten", lambda: [axes])())
        if not flat_axes:
            flat_axes = [axes]
        for ax in flat_axes:
            ax.axis("off")
        for ax, (label, image_path) in zip(flat_axes, chunk):
            try:
                image = mpimg.imread(image_path)
                ax.imshow(image)
                ax.set_title(label, fontsize=11.5, fontweight="bold", color=TEXT_COLOR, pad=10)
                ax.axis("off")
            except Exception:
                ax.axis("off")
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def export_afm_item_pdf(report_path: Path | str, summary: dict[str, Any]) -> Path:
    try:
        from matplotlib.backends.backend_pdf import PdfPages
    except Exception as exc:
        raise RuntimeError("matplotlib with PdfPages is required for AFM PDF export.") from exc

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    metrics = summary.get("metrics") or {}
    diagnostics = summary.get("diagnostics") or {}
    artifacts = summary.get("artifacts") or {}
    cover_rows = [
        ["Item", _wrap(summary.get("item_id"), 34)],
        ["Status", _wrap(summary.get("status"), 34)],
        ["Run ID", _wrap(summary.get("run_id"), 34)],
        ["Batch ID", _wrap(summary.get("batch_id"), 34)],
        ["Generated", _wrap(summary.get("created_at"), 34)],
        ["Source file", _wrap(Path(str(summary.get("file_name") or "")).name if summary.get("file_name") else "n/a", 34)],
    ]
    result_rows = [
        ["Rod count", _fmt_value(metrics.get("n_rods"))],
        ["Label count", _fmt_value(metrics.get("n_labels"))],
        ["Scale", _fmt_measure(metrics.get("um_per_px"), "um/px")],
        ["Resolved profile", _fmt_value(diagnostics.get("resolved_profile"))],
        ["Resolved device", _fmt_value(diagnostics.get("resolved_device"))],
        ["Effective diameter", _fmt_measure(metrics.get("diameter_effective_px"), "px")],
    ]
    runtime_rows = [
        ["Cellpose model", _fmt_value(metrics.get("cellpose_model"))],
        ["Selected channel", _fmt_value(metrics.get("selected_channel"))],
        ["Requested profile", _fmt_value(diagnostics.get("requested_profile"))],
        ["Total runtime", _fmt_measure((diagnostics.get("timings_ms") or {}).get("total_ms"), "ms")],
    ]
    artifact_rows = [[key.replace("_", " ").title(), _wrap(path, 56)] for key, path in sorted(artifacts.items())]
    image_entries = [
        (label, Path(path))
        for label, key in (
            ("Overlay image", "overlay_png"),
            ("Rod mask", "mask_png"),
            ("Contours", "contours_png"),
            ("Orientation histogram", "hist_raw_png"),
            ("Orientation density", "hist_density_png"),
            ("Folded orientation density", "hist_folded_png"),
        )
        if (path := artifacts.get(key))
    ]

    with PdfPages(report_path) as pdf:
        _render_table_page(pdf, f"Item Report: {summary.get('item_id')}", cover_rows, subtitle="AFM item-level summary")
        _render_table_page(pdf, "AFM Results And Runtime", result_rows + [["", ""]] + runtime_rows)
        if image_entries:
            _render_image_pages(pdf, "AFM Result Images", image_entries, items_per_page=2)
        if artifact_rows:
            _render_table_page(pdf, "Artifact Appendix", artifact_rows, subtitle="Relevant output files for this AFM item")
    return report_path


def export_afm_batch_pdf(report_path: Path | str, batch_summary: dict[str, Any]) -> Path:
    try:
        from matplotlib.backends.backend_pdf import PdfPages
    except Exception as exc:
        raise RuntimeError("matplotlib with PdfPages is required for AFM PDF export.") from exc

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    items = list(batch_summary.get("items") or [])
    successes = [item for item in items if str(item.get("status")).lower() == "success"]
    failures = [item for item in items if str(item.get("status")).lower() != "success"]

    cover_rows = [
        ["Batch ID", _wrap(batch_summary.get("batch_id"), 34)],
        ["Items total", str(len(items))],
        ["Successful", str(len(successes))],
        ["Failed", str(len(failures))],
        ["Generated", datetime.now().isoformat(timespec="seconds")],
    ]
    summary_rows = [
        [
            _wrap(item.get("item_id"), 20),
            _wrap(item.get("status"), 12),
            _fmt_value((item.get("metrics") or {}).get("n_rods")),
            _fmt_measure((item.get("metrics") or {}).get("um_per_px"), "um/px"),
            _fmt_value((item.get("diagnostics") or {}).get("resolved_device")),
        ]
        for item in items
    ]
    image_entries = [
        (f"Overlay: {item.get('item_id')}", Path((item.get("artifacts") or {}).get("overlay_png")))
        for item in successes
        if (item.get("artifacts") or {}).get("overlay_png")
    ]
    with PdfPages(report_path) as pdf:
        _render_table_page(pdf, f"Batch Report: {batch_summary.get('batch_id') or 'AFM batch'}", cover_rows, subtitle="AFM batch summary")
        if summary_rows:
            _render_table_page(
                pdf,
                "Batch Summary Table",
                summary_rows,
                subtitle="One row per AFM item for quick comparison",
                headers=["Item", "Status", "Rod count", "Scale", "Device"],
            )
        if image_entries:
            _render_image_pages(pdf, "Grouped Overlay Images", image_entries, items_per_page=2)
    return report_path
