from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from barakuda.core.trajectory_csv_io import read_trajectory_csv

from ..io import DragIoError


def _interp_time_for_frames(
    frame_indices: Sequence[int],
    frame_times: Sequence[float],
    target_frames: Sequence[int],
) -> list[float]:
    """Map trajectory frame indices to authoritative video timestamps (nearest neighbor)."""
    if not frame_indices or not frame_times or len(frame_indices) != len(frame_times):
        raise ValueError("Invalid frame_indices/frame_times inputs")
    index_to_time = {int(f): float(t) for f, t in zip(frame_indices, frame_times)}
    missing_frames = [int(fi) for fi in target_frames if int(fi) not in index_to_time]
    if missing_frames:
        preview = ", ".join(str(fi) for fi in missing_frames[:5])
        extra = "" if len(missing_frames) <= 5 else f" (+{len(missing_frames) - 5} more)"
        raise DragIoError(
            "Trajectory frame indices are missing in timestamps mapping; "
            "refusing silent frame->time clipping. "
            f"Missing frames: {preview}{extra}"
        )
    out: list[float] = []
    for fi in target_frames:
        t = index_to_time[int(fi)]
        out.append(float(t))
    return out


def _extract_axis_series(
    traj_path: Path,
    axis: str,
    um_per_px: float | None,
) -> tuple[list[int], list[float], list[float] | None]:
    """Extract frame indices and axis signal (px and optional µm) from trajectory CSV."""
    table = read_trajectory_csv(traj_path)
    rows = table.rows

    frame_col = "frame"
    if frame_col not in table.header:
        raise DragIoError(f"Trajectory CSV {traj_path.name} must contain 'frame' column")

    axis_px_col = f"{axis}_px"
    axis_um_col = f"{axis}_um"
    if axis_px_col not in table.header:
        raise DragIoError(f"Trajectory CSV {traj_path.name} must contain '{axis_px_col}' column")

    frames: list[int] = []
    sig_px: list[float] = []
    sig_um: list[float] | None = [] if um_per_px is not None or axis_um_col in table.header else None

    for r in rows:
        try:
            fi = int(float(r.get(frame_col, "nan")))
            x_px = float(r.get(axis_px_col, "nan"))
        except Exception:  # noqa: BLE001
            continue
        if not math.isfinite(x_px):
            continue
        frames.append(fi)
        sig_px.append(x_px)
        if sig_um is not None:
            if axis_um_col in table.header:
                try:
                    x_um = float(r.get(axis_um_col, "nan"))
                except Exception:  # noqa: BLE001
                    x_um = math.nan
            else:
                x_um = x_px * float(um_per_px or 0.0)
            sig_um.append(x_um)

    if sig_um is not None and not sig_um:
        sig_um = None

    return frames, sig_px, sig_um

