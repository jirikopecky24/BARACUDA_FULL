from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import json as _json

from barakuda.core.truth_resolvers import resolve_timing_truth_for_run


@dataclass(frozen=True)
class VideoMeta:
    fps: float
    width: int
    height: int
    frame_count: int
    effective_fps: float | None = None
    timing_source: str = "estimated"
    timing_source_detail: str = ""
    t_first_s: float | None = None
    t_last_s: float | None = None
    elapsed_time_s: float | None = None
    timestamp_validation_pass: bool = False
    timestamp_validation_message: str = ""

    @property
    def duration_s(self) -> Optional[float]:
        if self.fps <= 0 or self.frame_count <= 0:
            return None
        return float(self.frame_count) / float(self.fps)


def is_video_file(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext in {".mp4", ".avi", ".mov", ".mkv", ".m4v", ".raw"}


def read_first_frame(path: Path) -> Tuple[np.ndarray, VideoMeta]:
    """
    Read the first video frame using OpenCV (VideoCapture).
    Returns:
      - frame_rgb: (H,W,3) uint8 (RGB)
      - meta: fps, size, frame_count

    Raises RuntimeError with a clear message on failure.
    """
    try:
        import cv2
    except Exception as e:
        raise RuntimeError(
            "OpenCV (cv2) is not available, but required for video loading. "
            "Install opencv-python."
        ) from e

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    meta_payload: dict | None = None
    for suffix in (
        path.stem + "_meta.json",
        path.name + "_meta.json",
        "video_meta.json",
    ):
        meta_path = path.parent / suffix
        if not meta_path.exists():
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as _mf:
                payload = _json.load(_mf)
            if isinstance(payload, dict):
                meta_payload = payload
                break
        except Exception:
            pass

    ok, frame_bgr = cap.read()
    cap.release()

    if not ok or frame_bgr is None:
        raise RuntimeError(f"Failed to read the first frame from video: {path}")

    # BGR -> RGB
    frame_rgb = frame_bgr[:, :, ::-1].copy()
    timing_truth = resolve_timing_truth_for_run(
        video_path=path,
        frame_count=frame_count,
        fps_hint=fps,
        meta=meta_payload,
    )
    if timing_truth.effective_fps is not None and timing_truth.effective_fps > 0:
        fps = float(timing_truth.effective_fps)

    meta = VideoMeta(
        fps=fps,
        width=width if width > 0 else int(frame_rgb.shape[1]),
        height=height if height > 0 else int(frame_rgb.shape[0]),
        frame_count=frame_count,
        effective_fps=(
            float(timing_truth.effective_fps)
            if timing_truth.effective_fps is not None and timing_truth.effective_fps > 0
            else float(fps) if fps > 0 else None
        ),
        timing_source=timing_truth.timing_source,
        timing_source_detail=timing_truth.timing_source_detail,
        t_first_s=timing_truth.t_first_s,
        t_last_s=timing_truth.t_last_s,
        elapsed_time_s=timing_truth.elapsed_time_s,
        timestamp_validation_pass=timing_truth.timestamp_validation_pass,
        timestamp_validation_message=timing_truth.timestamp_validation_message,
    )
    return frame_rgb.astype(np.uint8, copy=False), meta
