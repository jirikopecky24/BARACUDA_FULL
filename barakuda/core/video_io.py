from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class VideoMeta:
    fps: float
    width: int
    height: int
    frame_count: int

    @property
    def duration_s(self) -> Optional[float]:
        if self.fps <= 0 or self.frame_count <= 0:
            return None
        return float(self.frame_count) / float(self.fps)


def is_video_file(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext in {".mp4", ".avi", ".mov", ".mkv", ".m4v"}


def read_first_frame(path: Path) -> Tuple[np.ndarray, VideoMeta]:
    """
    Načte první snímek z videa přes OpenCV (VideoCapture).
    Vrací:
      - frame_rgb: (H,W,3) uint8 (RGB)
      - meta: fps, size, frame_count

    Chyby hází jako RuntimeError s jasnou hláškou.
    """
    try:
        import cv2
    except Exception as e:
        raise RuntimeError(
            "OpenCV (cv2) není dostupné, ale je potřeba pro načítání videa. "
            "Nainstaluj opencv-python."
        ) from e

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Video nejde otevřít: {path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    ok, frame_bgr = cap.read()
    cap.release()

    if not ok or frame_bgr is None:
        raise RuntimeError(f"Nelze načíst první snímek z videa: {path}")

    # BGR -> RGB
    frame_rgb = frame_bgr[:, :, ::-1].copy()

    meta = VideoMeta(
        fps=fps,
        width=width if width > 0 else int(frame_rgb.shape[1]),
        height=height if height > 0 else int(frame_rgb.shape[0]),
        frame_count=frame_count,
    )
    return frame_rgb.astype(np.uint8, copy=False), meta
