from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import json as _json
import numpy as np

from barakuda.core.truth_resolvers import resolve_timing_truth_for_run
from barakuda.devices.optical_tweezers import perf as ot_perf


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
    frame_to_time_s: dict[int, float] | None = None

    @property
    def duration_s(self) -> Optional[float]:
        if self.elapsed_time_s is not None:
            return float(self.elapsed_time_s)
        if self.fps <= 0 or self.frame_count <= 0:
            return None
        return float(self.frame_count) / float(self.fps)


class VideoReader:
    """
    Preview + tracking reader:
      - opens the video once
      - get_frame(i): random frame access
      - optimization: if i == last_i+1, reads sequentially without seek
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
            raise RuntimeError("Video metadata are not available (reader is not open).")
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
                raise RuntimeError("VideoReader is not open (cap=None).")

            import cv2

            meta = self.meta
            if meta.frame_count > 0:
                i = max(0, min(int(i), meta.frame_count - 1))
            else:
                i = max(0, int(i))

            if self._last_i == i and self._last_rgb is not None:
                return self._last_rgb

            # Fast path: sequential read
            if self._last_i is not None and i == self._last_i + 1:
                ok, frame_bgr = self._cap.read()
                if not ok or frame_bgr is None:
                    raise RuntimeError(f"Failed to read frame {i} (sequential) from video: {self.path}")
            else:
                # seek
                ok = self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
                if not ok:
                    pass
                ok, frame_bgr = self._cap.read()
                if not ok or frame_bgr is None:
                    raise RuntimeError(f"Failed to read frame {i} from video: {self.path}")

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
                "OpenCV (cv2) is not available, but required for video preview/tracking. "
                "Install opencv-python."
            ) from e

        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.path}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        # --- Check sibling meta.json for fps_effective ---
        # Patterns: <stem>_meta.json  OR  <filename>_meta.json
        _fps_from_meta = False
        meta_payload: dict | None = None
        for suffix in (
            self.path.stem + "_meta.json",
            self.path.name + "_meta.json",
        ):
            meta_path = self.path.parent / suffix
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as _mf:
                        _ext = _json.load(_mf)
                    if isinstance(_ext, dict):
                        meta_payload = _ext
                    _val = float(_ext.get("fps_effective", 0))
                    if 0 < _val < 100_000:
                        fps = _val
                        _fps_from_meta = True
                        print(f"FPS override from meta.json: {_val}")
                        break
                except Exception:
                    pass

        timing_truth = resolve_timing_truth_for_run(
            video_path=self.path,
            frame_count=frame_count,
            fps_hint=fps,
            meta=meta_payload,
        )
        if timing_truth.effective_fps is not None and timing_truth.effective_fps > 0:
            fps = float(timing_truth.effective_fps)

        ok, frame_bgr = cap.read()
        if not ok or frame_bgr is None:
            cap.release()
            raise RuntimeError(f"Failed to read the first frame from video: {self.path}")

        frame_rgb = frame_bgr[:, :, ::-1].copy()
        if width <= 0:
            width = int(frame_rgb.shape[1])
        if height <= 0:
            height = int(frame_rgb.shape[0])

        self._cap = cap
        self._meta = VideoMeta(
            fps=fps,
            width=width,
            height=height,
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
            frame_to_time_s=timing_truth.frame_to_time_s,
        )

        self._last_i = 0
        self._last_rgb = frame_rgb.astype(np.uint8, copy=False)

    def _open_raw(self) -> None:
        """Open a .raw recording using memmap + sibling _meta.json."""
        meta_candidates = [
            self.path.parent / (self.path.stem + "_meta.json"),
            self.path.parent / "video_meta.json",
            self.path.parent / (self.path.name + "_meta.json"),
        ]
        meta_path = next((p for p in meta_candidates if p.exists()), None)
        if meta_path is None:
            raise RuntimeError(
                "RAW meta not found next to the .raw file.\n"
                f"Tried: {', '.join(str(p) for p in meta_candidates)}"
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

        timing_truth = resolve_timing_truth_for_run(
            video_path=self.path,
            frame_count=frame_count,
            fps_hint=fps,
            meta=meta,
        )
        if timing_truth.effective_fps is not None and timing_truth.effective_fps > 0:
            fps = float(timing_truth.effective_fps)

        self._meta = VideoMeta(
            fps=fps,
            width=w,
            height=h,
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
            frame_to_time_s=timing_truth.frame_to_time_s,
        )

        # Cache first frame as RGB
        gray = self._raw_mmap[0]
        self._last_i = 0
        self._last_rgb = np.stack([gray, gray, gray], axis=-1).astype(np.uint8, copy=False)
