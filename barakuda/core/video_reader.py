from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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


class VideoReader:
    """
    Preview + tracking reader:
      - otevře video jednou
      - get_frame(i): náhodný přístup
      - optimalizace: pokud i == last_i+1 → čte sekvenčně bez seeku
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._cap = None
        self._meta: VideoMeta | None = None

        self._last_i: int | None = None
        self._last_rgb: np.ndarray | None = None

        self._open()

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None
        self._meta = None
        self._last_i = None
        self._last_rgb = None

    @property
    def meta(self) -> VideoMeta:
        if self._meta is None:
            raise RuntimeError("Video meta nejsou dostupná (reader není otevřen).")
        return self._meta

    def get_frame(self, i: int) -> np.ndarray:
        if self._cap is None:
            raise RuntimeError("VideoReader není otevřený (cap=None).")

        import cv2

        meta = self.meta
        if meta.frame_count > 0:
            i = max(0, min(int(i), meta.frame_count - 1))
        else:
            i = max(0, int(i))

        if self._last_i == i and self._last_rgb is not None:
            return self._last_rgb

        # rychlá cesta: sekvenční čtení
        if self._last_i is not None and i == self._last_i + 1:
            ok, frame_bgr = self._cap.read()
            if not ok or frame_bgr is None:
                raise RuntimeError(f"Nelze načíst frame {i} (sekvenčně) z videa: {self.path}")
        else:
            # seek
            ok = self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
            if not ok:
                pass
            ok, frame_bgr = self._cap.read()
            if not ok or frame_bgr is None:
                raise RuntimeError(f"Nelze načíst frame {i} z videa: {self.path}")

        frame_rgb = frame_bgr[:, :, ::-1].copy()

        self._last_i = i
        self._last_rgb = frame_rgb.astype(np.uint8, copy=False)
        return self._last_rgb

    def _open(self) -> None:
        try:
            import cv2
        except Exception as e:
            raise RuntimeError(
                "OpenCV (cv2) není dostupné, ale je potřeba pro video preview/tracking. "
                "Nainstaluj opencv-python."
            ) from e

        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise RuntimeError(f"Video nejde otevřít: {self.path}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        ok, frame_bgr = cap.read()
        if not ok or frame_bgr is None:
            cap.release()
            raise RuntimeError(f"Nelze načíst první snímek z videa: {self.path}")

        frame_rgb = frame_bgr[:, :, ::-1].copy()
        if width <= 0:
            width = int(frame_rgb.shape[1])
        if height <= 0:
            height = int(frame_rgb.shape[0])

        self._cap = cap
        self._meta = VideoMeta(fps=fps, width=width, height=height, frame_count=frame_count)

        self._last_i = 0
        self._last_rgb = frame_rgb.astype(np.uint8, copy=False)
