"""
Basler camera wrapper for BARAKUDA Acquisition module.

pypylon is an OPTIONAL dependency — the app starts without it.
If pypylon or Basler Pylon SDK is not installed, ``PYPYLON_AVAILABLE``
will be False and ``BaslerCamera`` methods raise clear errors.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

# ---------- Import guard for pypylon ----------
try:
    from pypylon import pylon  # type: ignore[import-untyped]

    PYPYLON_AVAILABLE = True
except ImportError:
    pylon = None  # type: ignore[assignment]
    PYPYLON_AVAILABLE = False


# ---------- Data classes ----------

@dataclass
class RecordResult:
    """Returned by BaslerCamera.record()."""
    video_path: str
    meta_path: str
    frames_written: int
    fps_effective: Optional[float]
    dropped: int
    meta: dict = field(default_factory=dict)


# ---------- BaslerCamera ----------

class BaslerCamera:
    """
    High-level wrapper around a single Basler camera via pypylon.

    All public methods check ``PYPYLON_AVAILABLE`` and raise a clear
    ``RuntimeError`` when the SDK is missing.
    """

    def __init__(self) -> None:
        self._cam = None
        self._connected = False
        self._preview_thread: Optional[threading.Thread] = None
        self._preview_stop = threading.Event()
        self._record_thread: Optional[threading.Thread] = None
        self._record_stop = threading.Event()
        self._sensor_w: int = 0
        self._sensor_h: int = 0

    # ------------------------------------------------------------------ #
    #  Connection
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        """Open the first available Basler camera."""
        self._require_pypylon()
        if self._connected:
            return

        tl_factory = pylon.TlFactory.GetInstance()
        self._cam = pylon.InstantCamera(tl_factory.CreateFirstDevice())
        self._cam.Open()
        self._connected = True

        # Cache full sensor size (with ROI reset to max)
        nm = self._cam.GetNodeMap()
        # Reset offsets first so Width/Height.Max reflect full sensor
        if "OffsetX" in nm:
            self._cam.OffsetX.SetValue(0)
        if "OffsetY" in nm:
            self._cam.OffsetY.SetValue(0)
        if "Width" in nm:
            self._cam.Width.SetValue(self._cam.Width.Max)
            self._sensor_w = int(self._cam.Width.Max)
        if "Height" in nm:
            self._cam.Height.SetValue(self._cam.Height.Max)
            self._sensor_h = int(self._cam.Height.Max)

    def disconnect(self) -> None:
        """Stop all activity and close the camera."""
        self.stop_preview()
        self.stop_record()
        if self._cam is not None:
            try:
                if self._cam.IsGrabbing():
                    self._cam.StopGrabbing()
                self._cam.Close()
            except Exception:
                pass
        self._cam = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._cam is not None

    def get_sensor_size(self) -> tuple[int, int]:
        """Return (max_width, max_height) of the sensor."""
        self._require_connected()
        return self._sensor_w, self._sensor_h

    # ------------------------------------------------------------------ #
    #  ROI helpers
    # ------------------------------------------------------------------ #

    def snap_roi(
        self, w: int, h: int, ox: int, oy: int
    ) -> tuple[int, int, int, int]:
        """
        Snap ROI values to camera-valid increments.

        Returns (width, height, offsetX, offsetY) that the camera will accept.
        """
        self._require_connected()
        nm = self._cam.GetNodeMap()

        def _snap_down(val: int, inc: int, mn: int, mx: int) -> int:
            val = max(mn, min(val, mx))
            return val - ((val - mn) % inc) if inc > 0 else val

        # Reset offsets to 0 so Width/Height max reflect full sensor
        if "OffsetX" in nm:
            self._cam.OffsetX.SetValue(0)
        if "OffsetY" in nm:
            self._cam.OffsetY.SetValue(0)
        if "Width" in nm:
            self._cam.Width.SetValue(self._cam.Width.Max)
        if "Height" in nm:
            self._cam.Height.SetValue(self._cam.Height.Max)

        w_inc = int(getattr(self._cam.Width, "Inc", 1) or 1)
        h_inc = int(getattr(self._cam.Height, "Inc", 1) or 1)
        ox_inc = int(getattr(self._cam.OffsetX, "Inc", 1) or 1)
        oy_inc = int(getattr(self._cam.OffsetY, "Inc", 1) or 1)

        w_min = int(self._cam.Width.Min)
        h_min = int(self._cam.Height.Min)

        w = _snap_down(w, w_inc, w_min, self._sensor_w)
        h = _snap_down(h, h_inc, h_min, self._sensor_h)
        ox = _snap_down(ox, ox_inc, 0, self._sensor_w - w)
        oy = _snap_down(oy, oy_inc, 0, self._sensor_h - h)

        return w, h, ox, oy

    # ------------------------------------------------------------------ #
    #  Preview (full-frame, latest-frame strategy)
    # ------------------------------------------------------------------ #

    def start_preview(
        self,
        callback: Callable[[np.ndarray], None],
        exposure_us: Optional[float] = None,
    ) -> None:
        """
        Start full-frame preview grabbing in a background thread.

        ``callback`` is called with the latest grabbed ``np.ndarray`` frame.
        Uses *latest-frame* strategy — frames are dropped if UI cannot keep up.
        """
        self._require_connected()
        self.stop_preview()

        # Ensure full-frame
        self._apply_full_frame()

        if exposure_us is not None:
            self._set_exposure(exposure_us)

        self._preview_stop.clear()

        def _grab_loop() -> None:
            try:
                self._cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
                while not self._preview_stop.is_set() and self._cam.IsGrabbing():
                    grab = self._cam.RetrieveResult(
                        500, pylon.TimeoutHandling_Return
                    )
                    if grab is None:
                        continue
                    if not grab.GrabSucceeded():
                        grab.Release()
                        continue
                    img = grab.Array.copy()  # snapshot
                    grab.Release()
                    try:
                        callback(img)
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                try:
                    if self._cam is not None and self._cam.IsGrabbing():
                        self._cam.StopGrabbing()
                except Exception:
                    pass

        self._preview_thread = threading.Thread(
            target=_grab_loop, daemon=True, name="basler-preview"
        )
        self._preview_thread.start()

    def stop_preview(self) -> None:
        """Stop the preview grab loop."""
        self._preview_stop.set()
        if self._preview_thread is not None:
            self._preview_thread.join(timeout=3.0)
            self._preview_thread = None
        # Ensure grabbing is really stopped
        if self._cam is not None:
            try:
                if self._cam.IsGrabbing():
                    self._cam.StopGrabbing()
            except Exception:
                pass

    @property
    def is_previewing(self) -> bool:
        return (
            self._preview_thread is not None and self._preview_thread.is_alive()
        )

    # ------------------------------------------------------------------ #
    #  Test FPS
    # ------------------------------------------------------------------ #

    def test_fps(
        self,
        roi: tuple[int, int, int, int],
        exposure_us: float,
        gain: Optional[float] = None,
        test_duration: float = 1.0,
    ) -> float:
        """
        Measure effective fps for the given ROI/exposure for *test_duration* seconds.

        Temporarily applies the record-ROI settings, grabs for ~``test_duration``
        seconds, computes fps from timestamps, then restores full-frame preview.

        Returns the estimated fps (float). Raises on error.
        """
        self._require_connected()
        was_previewing = self.is_previewing
        self.stop_preview()

        w, h, ox, oy = self.snap_roi(*roi)
        self._apply_roi(w, h, ox, oy)
        self._set_exposure(exposure_us)
        if gain is not None:
            self._set_gain(gain)

        timestamps: list[float] = []
        try:
            self._cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            t0 = time.perf_counter()
            while (time.perf_counter() - t0) < test_duration:
                grab = self._cam.RetrieveResult(
                    2000, pylon.TimeoutHandling_Return
                )
                if grab is None:
                    continue
                if grab.GrabSucceeded():
                    timestamps.append(time.perf_counter())
                grab.Release()
        finally:
            try:
                self._cam.StopGrabbing()
            except Exception:
                pass
            # Restore full frame
            self._apply_full_frame()

        if len(timestamps) < 2:
            return 0.0
        return (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])

    # ------------------------------------------------------------------ #
    #  Record
    # ------------------------------------------------------------------ #

    def record(
        self,
        output_dir: str,
        basename: str,
        duration_s: float,
        roi: tuple[int, int, int, int],
        exposure_us: float,
        gain: Optional[float] = None,
        fps_hint: float = 2000.0,
        pixel_format: str = "Mono8",
        progress_callback: Optional[Callable[[int, float], None]] = None,
    ) -> RecordResult:
        """
        Record video to AVI (MJPG) + meta.json.

        Parameters
        ----------
        output_dir : str
            Directory for output files.
        basename : str
            File stem (without extension).
        duration_s : float
            Recording duration in seconds.
        roi : tuple
            (width, height, offsetX, offsetY) — will be snapped to camera increments.
        exposure_us : float
            Exposure time in microseconds.
        gain : float or None
            Camera gain (applied if not None).
        fps_hint : float
            Target fps hint (written into video container metadata).
        pixel_format : str
            Pixel format (default Mono8).
        progress_callback : callable or None
            Called with (frames_written, elapsed_seconds) periodically.

        Returns
        -------
        RecordResult
        """
        import cv2

        self._require_connected()
        self.stop_preview()

        # Snap ROI
        w, h, ox, oy = self.snap_roi(*roi)

        # Apply camera settings
        self._apply_roi(w, h, ox, oy)
        self._set_exposure(exposure_us)
        if gain is not None:
            self._set_gain(gain)
        self._set_pixel_format(pixel_format)

        os.makedirs(output_dir, exist_ok=True)
        video_path = os.path.join(output_dir, basename + ".avi")
        meta_path = os.path.join(output_dir, basename + "_meta.json")

        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        is_color = pixel_format not in ("Mono8", "Mono12", "Mono16")
        writer = cv2.VideoWriter(
            video_path, fourcc, fps_hint, (w, h), isColor=is_color
        )
        if not writer.isOpened():
            raise RuntimeError(
                f"cv2.VideoWriter failed to open for {video_path}. "
                "Check codec/container support."
            )

        frames = 0
        dropped = 0
        timestamps: list[float] = []
        self._record_stop.clear()

        try:
            self._cam.StartGrabbing(
                pylon.GrabStrategy_OneByOne,
                pylon.GrabLoop_ProvidedByInstantCamera,
            )
            t0 = time.perf_counter()

            while not self._record_stop.is_set():
                elapsed = time.perf_counter() - t0
                if elapsed >= duration_s:
                    break

                grab = self._cam.RetrieveResult(
                    5000, pylon.TimeoutHandling_Return
                )
                if grab is None:
                    continue
                if not grab.GrabSucceeded():
                    dropped += 1
                    grab.Release()
                    continue

                img = grab.Array
                grab.Release()
                writer.write(img)
                frames += 1
                timestamps.append(time.perf_counter())

                if progress_callback is not None and frames % 100 == 0:
                    progress_callback(frames, time.perf_counter() - t0)

        finally:
            writer.release()
            try:
                if self._cam is not None and self._cam.IsGrabbing():
                    self._cam.StopGrabbing()
            except Exception:
                pass

        # Compute effective fps from actual timestamps
        fps_effective: Optional[float] = None
        if len(timestamps) > 1:
            fps_effective = (len(timestamps) - 1) / (
                timestamps[-1] - timestamps[0]
            )

        actual_duration = (
            (timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0.0
        )

        # Read actual gain value
        actual_gain: Optional[float] = None
        try:
            if "Gain" in self._cam.GetNodeMap():
                actual_gain = float(self._cam.Gain.Value)
        except Exception:
            pass

        meta = {
            "fps_effective": fps_effective,
            "fps_target_hint": fps_hint,
            "frames_written": frames,
            "duration_s": round(actual_duration, 6),
            "exposure_us": exposure_us,
            "gain": actual_gain,
            "full_frame_w": self._sensor_w,
            "full_frame_h": self._sensor_h,
            "record_roi": {"x": ox, "y": oy, "w": w, "h": h},
            "pixel_format": pixel_format,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dropped_frames": dropped,
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        # Restore full frame for subsequent preview
        self._apply_full_frame()

        return RecordResult(
            video_path=video_path,
            meta_path=meta_path,
            frames_written=frames,
            fps_effective=fps_effective,
            dropped=dropped,
            meta=meta,
        )

    def stop_record(self) -> None:
        """Request a running record to stop early."""
        self._record_stop.set()

    # ------------------------------------------------------------------ #
    #  Private helpers
    # ------------------------------------------------------------------ #

    def _require_pypylon(self) -> None:
        if not PYPYLON_AVAILABLE:
            raise RuntimeError(
                "pypylon is not installed. "
                "Install the Basler Pylon SDK and then: pip install pypylon"
            )

    def _require_connected(self) -> None:
        self._require_pypylon()
        if not self.is_connected:
            raise RuntimeError("Camera is not connected. Call connect() first.")

    def _apply_full_frame(self) -> None:
        """Reset ROI to full sensor."""
        nm = self._cam.GetNodeMap()
        if "OffsetX" in nm:
            self._cam.OffsetX.SetValue(0)
        if "OffsetY" in nm:
            self._cam.OffsetY.SetValue(0)
        if "Width" in nm:
            self._cam.Width.SetValue(self._cam.Width.Max)
        if "Height" in nm:
            self._cam.Height.SetValue(self._cam.Height.Max)

    def _apply_roi(self, w: int, h: int, ox: int, oy: int) -> None:
        """Apply ROI to camera. Order matters: offsets first (set to 0), then size, then offsets."""
        nm = self._cam.GetNodeMap()
        # Reset offsets first
        if "OffsetX" in nm:
            self._cam.OffsetX.SetValue(0)
        if "OffsetY" in nm:
            self._cam.OffsetY.SetValue(0)
        if "Width" in nm:
            self._cam.Width.SetValue(w)
        if "Height" in nm:
            self._cam.Height.SetValue(h)
        if "OffsetX" in nm:
            self._cam.OffsetX.SetValue(ox)
        if "OffsetY" in nm:
            self._cam.OffsetY.SetValue(oy)

    def _set_exposure(self, us: float) -> None:
        nm = self._cam.GetNodeMap()
        if "ExposureTime" in nm:
            self._cam.ExposureTime.SetValue(float(us))

    def _set_gain(self, val: float) -> None:
        nm = self._cam.GetNodeMap()
        if "Gain" in nm:
            self._cam.Gain.SetValue(float(val))

    def _set_pixel_format(self, fmt: str) -> None:
        nm = self._cam.GetNodeMap()
        if "PixelFormat" in nm:
            try:
                self._cam.PixelFormat.SetValue(fmt)
            except Exception:
                pass  # Camera may not support the format
