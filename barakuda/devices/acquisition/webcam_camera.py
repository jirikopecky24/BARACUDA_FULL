"""OpenCV webcam backend for the BARAKUDA camera abstraction.

cv2 (opencv-python) is an OPTIONAL dependency — if it is not installed,
``enumerate()`` returns an empty list and ``connect()`` raises a clear error.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from barakuda.devices.acquisition.camera_base import AbstractCamera, CameraDeviceInfo

try:
    import cv2  # type: ignore[import-untyped]
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None  # type: ignore[assignment]
    CV2_AVAILABLE = False

_MAX_PROBE_INDEX = 5  # probe indices 0 … _MAX_PROBE_INDEX-1


class WebcamCamera(AbstractCamera):
    """Webcam backend using OpenCV VideoCapture."""

    # ------------------------------------------------------------------ #
    #  Enumeration                                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def enumerate(cls) -> list[CameraDeviceInfo]:
        """Probe indices 0…{max} and return those that open successfully."""
        if not CV2_AVAILABLE:
            return []
        result = []
        for idx in range(_MAX_PROBE_INDEX):
            try:
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
                    result.append(CameraDeviceInfo(
                        backend="webcam",
                        index=idx,
                        display_name=f"Webcam {idx}  ({w}×{h})",
                        extra={"native_w": w, "native_h": h},
                    ))
                else:
                    cap.release()
            except Exception:
                pass
        return result

    # ------------------------------------------------------------------ #
    #  Init                                                                #
    # ------------------------------------------------------------------ #

    def __init__(self) -> None:
        self._cap: Optional[object] = None  # cv2.VideoCapture
        self._connected = False
        self._sensor_w: int = 0
        self._sensor_h: int = 0

        self._preview_stop = threading.Event()
        self._preview_thread: Optional[threading.Thread] = None
        self._latest_preview_frame: Optional[np.ndarray] = None
        self._latest_preview_ts: float = 0.0
        self._preview_lock = threading.Lock()

        # Exposure / gain via cv2 props (best-effort)
        self._exposure_us: float = 10000.0
        self._gain: float = 0.0

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def connect(self, info: CameraDeviceInfo | None = None) -> None:
        if not CV2_AVAILABLE:
            raise RuntimeError(
                "opencv-python is not installed.  "
                "Run: pip install opencv-python"
            )
        if self._connected:
            return
        idx = info.index if info is not None else 0
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Cannot open webcam index {idx}")
        self._cap = cap
        self._sensor_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._sensor_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._connected = True

    def disconnect(self) -> None:
        self.stop_preview()
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
        self._cap = None
        self._connected = False

    # ------------------------------------------------------------------ #
    #  State                                                               #
    # ------------------------------------------------------------------ #

    @property
    def is_connected(self) -> bool:
        return self._connected and self._cap is not None

    @property
    def is_previewing(self) -> bool:
        return self._preview_thread is not None and self._preview_thread.is_alive()

    # ------------------------------------------------------------------ #
    #  Sensor / ROI                                                        #
    # ------------------------------------------------------------------ #

    def get_sensor_size(self) -> tuple[int, int]:
        return self._sensor_w, self._sensor_h

    def get_roi_config(self) -> dict:
        return {"w_inc": 1, "h_inc": 1, "ox_inc": 1, "oy_inc": 1,
                "w_min": 1, "h_min": 1}

    # ------------------------------------------------------------------ #
    #  Preview                                                             #
    # ------------------------------------------------------------------ #

    def start_preview(self, callback=None, exposure_us: Optional[float] = None) -> None:
        if not self.is_connected:
            raise RuntimeError("Webcam not connected")
        if self.is_previewing:
            return
        if exposure_us is not None:
            self.set_exposure_live(exposure_us)
        self._preview_stop.clear()
        self._preview_thread = threading.Thread(
            target=self._grab_loop, daemon=True, name="webcam-preview"
        )
        self._preview_thread.start()

    def stop_preview(self) -> None:
        self._preview_stop.set()
        if self._preview_thread is not None:
            self._preview_thread.join(timeout=2.0)
            self._preview_thread = None

    def get_latest_preview(self) -> tuple[Optional[np.ndarray], float]:
        with self._preview_lock:
            return self._latest_preview_frame, self._latest_preview_ts

    def _grab_loop(self) -> None:
        cap = self._cap
        last_display = 0.0
        while not self._preview_stop.is_set():
            try:
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue
                # Convert BGR → grayscale uint8 for display consistency
                if frame.ndim == 3:
                    gray = np.mean(frame, axis=2).astype(np.uint8)
                else:
                    gray = frame.astype(np.uint8)
                now = time.perf_counter()
                if now - last_display >= 0.04:
                    last_display = now
                    with self._preview_lock:
                        self._latest_preview_frame = gray
                        self._latest_preview_ts = now
            except Exception:
                time.sleep(0.01)

    # ------------------------------------------------------------------ #
    #  Camera settings                                                     #
    # ------------------------------------------------------------------ #

    def set_exposure_live(self, us: float) -> Optional[float]:
        if not self.is_connected:
            return None
        self._exposure_us = float(us)
        try:
            # cv2 exposure is in log2(seconds) on some backends, or direct ms
            # Use CAP_PROP_EXPOSURE best-effort; read back immediately
            self._cap.set(cv2.CAP_PROP_EXPOSURE, us / 1_000_000)
            val = self._cap.get(cv2.CAP_PROP_EXPOSURE)
            return float(val) * 1_000_000 if val else us
        except Exception:
            return us

    def set_gain_live(self, db: float) -> Optional[float]:
        if not self.is_connected:
            return None
        self._gain = float(db)
        try:
            self._cap.set(cv2.CAP_PROP_GAIN, db)
            val = self._cap.get(cv2.CAP_PROP_GAIN)
            return float(val) if val else db
        except Exception:
            return db

    # ------------------------------------------------------------------ #
    #  FPS utilities (minimal stubs)                                       #
    # ------------------------------------------------------------------ #

    def test_fps(self, **kwargs) -> dict:
        return {"fps": 0.0, "note": "FPS test not supported for webcam"}

    def benchmark_fps(self, **kwargs) -> dict:
        return {"fps": 0.0, "note": "Benchmark not supported for webcam"}

    # ------------------------------------------------------------------ #
    #  Recording                                                           #
    # ------------------------------------------------------------------ #

    def stop_record(self) -> None:
        pass  # Webcam recording not implemented
