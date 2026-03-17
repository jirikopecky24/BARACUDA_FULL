from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .schema import DragAnalysisResult, AlignmentDiagnostics

# Match OT styling constants from postprocess_ot
FIGURE_SIZE = (7, 5)
AXIS_LABEL_FONTSIZE = 11
TICK_LABEL_FONTSIZE = 9
TITLE_FONTSIZE = 12
PLOT_DPI = 300
PLOT_COLOR = "#1F6AA5"
GRID_COLOR = "#CAD5E0"
PANEL_BG = "#F8FBFD"


def plot_alignment_debug(
    t_s: Sequence[float],
    signal_px: Sequence[float],
    diagnostics: AlignmentDiagnostics,
    motion_start_stage_s: float,
    motion_stop_stage_s: float | None,
    output_path: Path,
) -> Path:
    """Plot signal vs time with baseline band, threshold, candidate onsets, and stage window.

    Used when alignment fails to debug onset detection.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ax.set_facecolor(PANEL_BG)

    ax.plot(t_s, signal_px, color=PLOT_COLOR, alpha=0.7, label="signal (px)", zorder=3)

    med = diagnostics.baseline_median
    thresh = diagnostics.onset_threshold_abs
    if thresh == thresh:  # not nan
        ax.axhspan(med - thresh, med + thresh, color="#E8F5E9", alpha=0.4, label="baseline ± threshold")
    ax.axhline(med, color="#2E7D32", linestyle="-", linewidth=1.0, label="baseline median")

    for i, t_cand in enumerate(diagnostics.candidate_onset_times_s):
        ax.axvline(
            t_cand,
            color="#FF9800",
            linestyle="--",
            linewidth=0.8,
            alpha=0.8,
            label="candidate onset" if i == 0 else None,
        )
    if motion_stop_stage_s is not None:
        ax.axvspan(
            motion_start_stage_s,
            motion_stop_stage_s,
            color="#B3E5FC",
            alpha=0.25,
            label="stage motion (stage clock)",
        )
    else:
        ax.axvline(
            motion_start_stage_s,
            color="#0288D1",
            linestyle=":",
            linewidth=1.0,
            label="stage motion_start (stage clock)",
        )

    ax.set_xlabel("time [s]", fontsize=AXIS_LABEL_FONTSIZE)
    ax.set_ylabel("position [px]", fontsize=AXIS_LABEL_FONTSIZE)
    title = "DRAG alignment debug"
    if diagnostics.failure_reason:
        title += f" — {diagnostics.failure_reason}"
    ax.set_title(title, fontsize=TITLE_FONTSIZE, fontweight="bold")
    ax.tick_params(labelsize=TICK_LABEL_FONTSIZE)
    ax.grid(True, linestyle="--", linewidth=0.5, color=GRID_COLOR)
    ax.legend(fontsize=TICK_LABEL_FONTSIZE)

    fig.tight_layout()
    fig.savefig(output_path, dpi=PLOT_DPI)
    plt.close(fig)
    return output_path


def plot_drag_diagnostic(
    t_s: Sequence[float],
    signal_px: Sequence[float],
    result: DragAnalysisResult,
    output_dir: Path,
) -> Path:
    """Create a simple diagnostic plot of the drag response."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.basename}_drag_diagnostic.png"

    fig, ax = plt.subplots(figsize=FIGURE_SIZE)
    ax.set_facecolor(PANEL_BG)

    ax.plot(t_s, signal_px, color=PLOT_COLOR, alpha=0.7, label="signal (px)")

    # Windows as spans
    ax.axvspan(
        result.windows.baseline_start_s,
        result.windows.baseline_end_s,
        color="#A5D6A7",
        alpha=0.2,
        label="baseline window",
    )
    ax.axvspan(
        result.windows.steady_start_s,
        result.windows.steady_end_s,
        color="#EF9A9A",
        alpha=0.2,
        label="steady window",
    )

    # Motion times
    ax.axvline(
        result.motion_start_video_s_detected,
        color="#000000",
        linestyle="--",
        linewidth=1.0,
        label="motion start (detected)",
    )
    if result.motion_stop_video_s_stage_aligned is not None:
        ax.axvline(
            result.motion_stop_video_s_stage_aligned,
            color="#555555",
            linestyle=":",
            linewidth=1.0,
            label="motion stop (stage-aligned)",
        )

    # Baseline / steady medians
    ax.hlines(
        result.baseline_position_px,
        result.windows.baseline_start_s,
        result.windows.baseline_end_s,
        colors="#2E7D32",
        linestyles="-",
        linewidth=1.5,
        label="baseline median",
    )
    ax.hlines(
        result.steady_position_px,
        result.windows.steady_start_s,
        result.windows.steady_end_s,
        colors="#C62828",
        linestyles="-",
        linewidth=1.5,
        label="steady median",
    )

    ax.set_xlabel("time [s]", fontsize=AXIS_LABEL_FONTSIZE)
    ax.set_ylabel("position [px]", fontsize=AXIS_LABEL_FONTSIZE)
    ax.set_title("DRAG diagnostic", fontsize=TITLE_FONTSIZE, fontweight="bold")
    ax.tick_params(labelsize=TICK_LABEL_FONTSIZE)
    ax.grid(True, linestyle="--", linewidth=0.5, color=GRID_COLOR)
    ax.legend(fontsize=TICK_LABEL_FONTSIZE)

    fig.tight_layout()
    fig.savefig(path, dpi=PLOT_DPI)
    plt.close(fig)
    return path

