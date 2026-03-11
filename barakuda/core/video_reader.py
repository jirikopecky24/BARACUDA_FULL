from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import json as _json
import numpy as np

from barakuda.devices.optical_tweezers import perf as ot_perf


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

        # RAW memmap support
        self._raw_mmap: np.ndarray | None = None
        self._raw_h: int = 0
        self._raw_w: int = 0

        self._open()

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None
        self._raw_mmap = None
        self._meta = None
        self._last_i = None
        self._last_rgb = None

    @property
    def meta(self) -> VideoMeta:
        if self._meta is None:
            raise RuntimeError("Video meta nejsou dostupná (reader není otevřen).")
        return self._meta

    def get_frame(self, i: int) -> np.ndarray:
        with ot_perf.record("video_reader.get_frame"):
            # --- RAW path ---
            if self._raw_mmap is not None:
                meta = self.meta
                if meta.frame_count > 0:
                    i = max(0, min(int(i), meta.frame_count - 1))
                else:
                    i = max(0, int(i))
                if self._last_i == i and self._last_rgb is not None:
                    return self._last_rgb
                gray = self._raw_mmap[i]
                frame_rgb = np.stack([gray, gray, gray], axis=-1)
                self._last_i = i
                self._last_rgb = frame_rgb.astype(np.uint8, copy=False)
                return self._last_rgb

            # --- AVI / standard video path ---
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
        # --- RAW binary format ---
        if self.path.suffix.lower() == ".raw":
            self._open_raw()
            return

        # --- Standard video (AVI etc.) ---
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

        # --- Check sibling meta.json for fps_effective ---
        # Patterns: <stem>_meta.json  OR  <filename>_meta.json
        _fps_from_meta = False
        for suffix in (
            self.path.stem + "_meta.json",
            self.path.name + "_meta.json",
        ):
            meta_path = self.path.parent / suffix
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as _mf:
                        _ext = _json.load(_mf)
                    _val = float(_ext.get("fps_effective", 0))
                    if 0 < _val < 100_000:
                        fps = _val
                        _fps_from_meta = True
                        print(f"FPS override from meta.json: {_val}")
                        break
                except Exception:
                    pass

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

    def _open_raw(self) -> None:
        """Open a .raw recording using memmap + sibling _meta.json."""
        meta_path = self.path.parent / (self.path.stem + "_meta.json")
        if not meta_path.exists():
            raise RuntimeError(
                f"RAW meta not found: {meta_path}\n"
                "Expected <basename>_meta.json next to the .raw file."
            )

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = _json.load(f)

        roi = meta.get("record_roi", {})
        w = int(roi.get("w", 0))
        h = int(roi.get("h", 0))
        frame_bytes = int(meta.get("frame_bytes", w * h))
        fps = float(meta.get("fps_effective", 0) or 0)

        if w <= 0 or h <= 0:
            raise RuntimeError(f"Invalid dimensions in meta: w={w} h={h}")

        file_size = self.path.stat().st_size
        frame_count = file_size // frame_bytes if frame_bytes > 0 else 0

        if frame_count <= 0:
            raise RuntimeError(f"RAW file is empty or meta mismatch: {self.path}")

        self._raw_mmap = np.memmap(
            str(self.path), dtype="uint8", mode="r",
            shape=(frame_count, h, w),
        )
        self._raw_h = h
        self._raw_w = w

        self._meta = VideoMeta(fps=fps, width=w, height=h, frame_count=frame_count)

        # Cache first frame as RGB
        gray = self._raw_mmap[0]
        self._last_i = 0
        self._last_rgb = np.stack([gray, gray, gray], axis=-1).astype(np.uint8, copy=False)
