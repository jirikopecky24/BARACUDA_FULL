"""
Basler camera wrapper for BARAKUDA Acquisition module.

pypylon is an OPTIONAL dependency — the app starts without it.
If pypylon or Basler Pylon SDK is not installed, ``PYPYLON_AVAILABLE``
will be False and ``BaslerCamera`` methods raise clear errors.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from barakuda.devices.acquisition.camera_base import AbstractCamera, CameraDeviceInfo

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

class BaslerCamera(AbstractCamera):
    """
    High-level wrapper around a single Basler camera via pypylon.

    All public methods check ``PYPYLON_AVAILABLE`` and raise a clear
    ``RuntimeError`` when the SDK is missing.
    """

    # ------------------------------------------------------------------ #
    #  Enumeration                                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def enumerate(cls) -> list[CameraDeviceInfo]:
        """Return a CameraDeviceInfo for every Basler device currently visible."""
        if not PYPYLON_AVAILABLE:
            return []
        try:
            tl_factory = pylon.TlFactory.GetInstance()
            devices = tl_factory.EnumerateDevices()
            result = []
            for i, dev in enumerate(devices):
                try:
                    serial = dev.GetSerialNumber()
                    model = dev.GetModelName()
                    name = f"{model} (S/N {serial})" if serial else model
                except Exception:
                    serial = ""
                    model = ""
                    name = f"Basler camera {i}"
                result.append(CameraDeviceInfo(
                    backend="basler",
                    index=i,
                    display_name=name,
                    serial=serial,
                    model=model,
                    extra={"pylon_device_info": dev},
                ))
            return result
        except Exception:
            return []

    def __init__(self) -> None:
        self._cam = None
        self._connected = False
        self._preview_thread: Optional[threading.Thread] = None
        self._preview_stop = threading.Event()
        self._record_thread: Optional[threading.Thread] = None
        self._record_stop = threading.Event()
        self._sensor_w: int = 0
        self._sensor_h: int = 0
        self._latest_preview_frame: Optional[np.ndarray] = None
        self._latest_preview_ts: float = 0.0
        self._preview_lock = threading.Lock()
        # Live-settings: pending values queued for grab-thread application
        self._pending_exposure_us: Optional[float] = None
        self._pending_gain_db: Optional[float] = None
        self._readback_exposure_us: Optional[float] = None
        self._readback_gain_db: Optional[float] = None
        self._settings_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    #  Connection
    # ------------------------------------------------------------------ #

    def connect(self, info: CameraDeviceInfo | None = None) -> None:
        """Open the Basler camera described by *info*, or the first available."""
        self._require_pypylon()
        if self._connected:
            return

        tl_factory = pylon.TlFactory.GetInstance()
        pylon_dev_info = info.extra.get("pylon_device_info") if info else None
        if pylon_dev_info is not None:
            self._cam = pylon.InstantCamera(tl_factory.CreateDevice(pylon_dev_info))
        else:
            self._cam = pylon.InstantCamera(tl_factory.CreateFirstDevice())
        self._cam.Open()
        self._connected = True

        # Cache full sensor size (with ROI reset to max)
        nm = self._cam.GetNodeMap()
        # Reset offsets first so Width/Height.Max reflect full sensor
        try:
            self._cam.OffsetX.SetValue(0)
        except Exception:
            pass
        try:
            self._cam.OffsetY.SetValue(0)
        except Exception:
            pass
        try:
            self._cam.Width.SetValue(self._cam.Width.Max)
            self._sensor_w = int(self._cam.Width.Max)
        except Exception:
            pass
        try:
            self._cam.Height.SetValue(self._cam.Height.Max)
            self._sensor_h = int(self._cam.Height.Max)
        except Exception:
            pass

        # Disable auto exposure/gain so manual values take effect immediately
        try:
            self._cam.ExposureAuto.SetValue("Off")
        except Exception:
            pass
        try:
            self._cam.GainAuto.SetValue("Off")
        except Exception:
            pass

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

    def get_roi_config(self) -> dict:
        """Return ROI alignment constraints read from the camera nodemap."""
        result = {"w_inc": 1, "h_inc": 1, "ox_inc": 1, "oy_inc": 1,
                  "w_min": 1, "h_min": 1}
        if self._cam is None:
            return result
        try:
            result["w_inc"] = int(getattr(self._cam.Width, "Inc", 1) or 1)
            result["h_inc"] = int(getattr(self._cam.Height, "Inc", 1) or 1)
            result["ox_inc"] = int(getattr(self._cam.OffsetX, "Inc", 1) or 1)
            result["oy_inc"] = int(getattr(self._cam.OffsetY, "Inc", 1) or 1)
            result["w_min"] = int(self._cam.Width.Min)
            result["h_min"] = int(self._cam.Height.Min)
        except Exception:
            pass
        return result

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
        try:
            self._cam.OffsetX.SetValue(0)
        except Exception:
            pass
        try:
            self._cam.OffsetY.SetValue(0)
        except Exception:
            pass
        try:
            self._cam.Width.SetValue(self._cam.Width.Max)
        except Exception:
            pass
        try:
            self._cam.Height.SetValue(self._cam.Height.Max)
        except Exception:
            pass

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
        # Only stop if actually running — avoids blocking join when already stopped
        if self.is_previewing:
            self.stop_preview()

        # Ensure full-frame
        self._apply_full_frame()

        if exposure_us is not None:
            self._set_exposure(exposure_us)

        self._preview_stop.clear()

        def _grab_loop() -> None:
            _last_display_time = 0.0
            _settings_last = 0.0

            try:
                self._cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
                while not self._preview_stop.is_set():
                    grab = self._cam.RetrieveResult(
                        500, pylon.TimeoutHandling_Return
                    )
                    if grab is None:
                        continue
                    if not grab.GrabSucceeded():
                        grab.Release()
                        continue
                    img_raw = grab.Array.copy()  # snapshot
                    grab.Release()

                    now = time.perf_counter()

                    # -- Apply pending exposure/gain (5 Hz, from grab thread) --
                    if now - _settings_last >= 0.2:
                        _settings_last = now
                        with self._settings_lock:
                            _pexp = self._pending_exposure_us
                            _pgain = self._pending_gain_db
                            self._pending_exposure_us = None
                            self._pending_gain_db = None
                        if _pexp is not None:
                            try:
                                self._cam.ExposureTime.SetValue(_pexp)
                                _rb = float(self._cam.ExposureTime.Value)
                                with self._settings_lock:
                                    self._readback_exposure_us = _rb
                            except Exception:
                                pass
                        if _pgain is not None:
                            _gain_applied = False
                            try:
                                self._cam.Gain.SetValue(_pgain)
                                _rb = float(self._cam.Gain.Value)
                                with self._settings_lock:
                                    self._readback_gain_db = _rb
                                _gain_applied = True
                            except Exception:
                                pass
                            if not _gain_applied:
                                try:
                                    self._cam.GainRaw.SetValue(int(round(_pgain)))
                                    _rb = float(self._cam.GainRaw.Value)
                                    with self._settings_lock:
                                        self._readback_gain_db = _rb
                                except Exception:
                                    pass

                    # -- Throttled display update (~25 fps) --
                    if now - _last_display_time >= 0.04:
                        _last_display_time = now
                        # Pass raw pixels to UI; convert >8-bit to uint8 by top-byte shift
                        if img_raw.dtype == np.uint8:
                            img = img_raw
                        elif img_raw.dtype == np.uint16:
                            img = (img_raw >> 8).astype(np.uint8)
                        else:
                            img = np.clip(img_raw, 0, 255).astype(np.uint8)

                        with self._preview_lock:
                            self._latest_preview_frame = img
                            self._latest_preview_ts = now
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

    def get_latest_preview(self) -> tuple[Optional[np.ndarray], float]:
        """Return (frame, timestamp) of the most recent preview frame, or (None, 0.0)."""
        with self._preview_lock:
            return self._latest_preview_frame, self._latest_preview_ts

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
                if duration_s > 0 and elapsed >= duration_s:
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

    def benchmark_fps(
        self,
        duration_s: float,
        roi: tuple[int, int, int, int],
        exposure_us: float,
        gain: Optional[float] = None,
        pixel_format: str = "Mono8",
        stop_event: Optional[threading.Event] = None,
    ) -> dict:
        """
        Benchmark achievable FPS without writing to disk.

        Grabs frames for *duration_s* seconds using the same camera
        settings as record, counts frames and failures.
        """
        self._require_connected()
        self.stop_preview()

        w, h, ox, oy = self.snap_roi(*roi)
        self._apply_roi(w, h, ox, oy)
        self._set_exposure(exposure_us)
        if gain is not None:
            self._set_gain(gain)
        self._set_pixel_format(pixel_format)

        frames = 0
        dropped = 0
        timestamps: list[float] = []

        try:
            self._cam.StartGrabbing(pylon.GrabStrategy_OneByOne)
            t0 = time.perf_counter()

            while True:
                elapsed = time.perf_counter() - t0
                if elapsed >= duration_s:
                    break
                if stop_event is not None and stop_event.is_set():
                    break

                grab = self._cam.RetrieveResult(
                    2000, pylon.TimeoutHandling_Return
                )
                if grab is None:
                    continue
                if not grab.GrabSucceeded():
                    dropped += 1
                    grab.Release()
                    continue

                grab.Release()  # don't write — just count
                frames += 1
                timestamps.append(time.perf_counter())

        finally:
            try:
                if self._cam is not None and self._cam.IsGrabbing():
                    self._cam.StopGrabbing()
            except Exception:
                pass
            self._apply_full_frame()

        fps_effective = 0.0
        if len(timestamps) > 1:
            fps_effective = (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])

        actual_duration = (timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0.0

        return {
            "frames": frames,
            "fps_effective": fps_effective,
            "dropped_frames": dropped,
            "duration_s": round(actual_duration, 6),
        }

    def record_raw(
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
        Record raw binary frames + timestamps CSV + meta JSON.

        Much faster than AVI — no codec overhead.
        If duration_s <= 0, records until stop_record() is called.
        """
        self._require_connected()
        self.stop_preview()

        w, h, ox, oy = self.snap_roi(*roi)
        self._apply_roi(w, h, ox, oy)
        self._set_exposure(exposure_us)
        if gain is not None:
            self._set_gain(gain)
        self._set_pixel_format(pixel_format)

        os.makedirs(output_dir, exist_ok=True)
        raw_path = os.path.join(output_dir, basename + ".raw")
        ts_path = os.path.join(output_dir, basename + "_timestamps.csv")
        meta_path = os.path.join(output_dir, basename + "_meta.json")

        frame_bytes = w * h  # Mono8

        _QUEUE_MAXSIZE = 1024
        frames = 0
        dropped = 0
        timestamps: list[float] = []
        self._record_stop.clear()

        write_q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)

        def _writer() -> None:
            with open(raw_path, "wb") as raw_f:
                while True:
                    item = write_q.get()
                    if item is None:  # sentinel
                        break
                    data, ts = item
                    raw_f.write(data)
                    timestamps.append(ts)

        writer_thread = threading.Thread(target=_writer, daemon=True)
        writer_thread.start()

        try:
            self._cam.StartGrabbing(
                pylon.GrabStrategy_OneByOne,
                pylon.GrabLoop_ProvidedByInstantCamera,
            )
            t0 = time.perf_counter()

            while not self._record_stop.is_set():
                elapsed = time.perf_counter() - t0
                if duration_s > 0 and elapsed >= duration_s:
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

                data = grab.Array.tobytes()
                ts = time.perf_counter()
                grab.Release()

                try:
                    write_q.put_nowait((data, ts))
                    frames += 1
                except queue.Full:
                    dropped += 1

                if progress_callback is not None and frames % 100 == 0:
                    progress_callback(frames, time.perf_counter() - t0)

        finally:
            write_q.put(None)  # sentinel — stop writer
            writer_thread.join()
            try:
                if self._cam is not None and self._cam.IsGrabbing():
                    self._cam.StopGrabbing()
            except Exception:
                pass

        # Write timestamps CSV
        with open(ts_path, "w", encoding="utf-8") as tf:
            tf.write("frame,timestamp_s\n")
            for idx, ts in enumerate(timestamps):
                tf.write(f"{idx},{ts:.9f}\n")

        # Compute effective fps
        fps_effective: Optional[float] = None
        if len(timestamps) > 1:
            fps_effective = (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])

        actual_duration = (timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0.0

        actual_gain: Optional[float] = None
        try:
            if "Gain" in self._cam.GetNodeMap():
                actual_gain = float(self._cam.Gain.Value)
        except Exception:
            pass

        meta = {
            "format": "raw",
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
            "frame_bytes": frame_bytes,
            "dtype": "uint8",
            "raw_path": raw_path,
            "timestamps_path": ts_path,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dropped_frames": dropped,
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        self._apply_full_frame()

        return RecordResult(
            video_path=raw_path,
            meta_path=meta_path,
            frames_written=frames,
            fps_effective=fps_effective,
            dropped=dropped,
            meta=meta,
        )

    @staticmethod
    def simulate_record_raw(
        output_dir: str,
        basename: str,
        width: int,
        height: int,
        fps_target: float,
        duration_s: float,
        pattern: str = "noise",
    ) -> dict:
        """
        Generate a synthetic .raw recording without a camera.

        Writes basename.raw + basename_timestamps.csv + basename_meta.json
        using the same schema as record_raw.
        """
        import numpy as np

        os.makedirs(output_dir, exist_ok=True)
        raw_path = os.path.join(output_dir, basename + ".raw")
        ts_path = os.path.join(output_dir, basename + "_timestamps.csv")
        meta_path = os.path.join(output_dir, basename + "_meta.json")

        frame_bytes = width * height
        frames = 0
        timestamps: list[float] = []
        delay = 1.0 / fps_target if fps_target > 0 else 0.0

        with open(raw_path, "wb") as raw_f:
            t0 = time.perf_counter()
            while True:
                elapsed = time.perf_counter() - t0
                if elapsed >= duration_s:
                    break

                if pattern == "gradient":
                    row = np.arange(width, dtype=np.uint8)
                    frame = np.tile(row, (height, 1))
                    frame = ((frame.astype(np.uint16) + frames) % 256).astype(np.uint8)
                else:  # noise
                    frame = np.random.randint(0, 256, (height, width), dtype=np.uint8)

                raw_f.write(frame.tobytes())
                frames += 1
                timestamps.append(time.perf_counter())

                # throttle to approximate fps_target
                if delay > 0:
                    next_t = t0 + frames * delay
                    wait = next_t - time.perf_counter()
                    if wait > 0:
                        time.sleep(wait)

        # Write timestamps CSV
        with open(ts_path, "w", encoding="utf-8") as tf:
            tf.write("frame,timestamp_s\n")
            for idx, ts in enumerate(timestamps):
                tf.write(f"{idx},{ts:.9f}\n")

        # Compute effective fps
        fps_effective = 0.0
        if len(timestamps) > 1:
            fps_effective = (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])

        actual_duration = (timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0.0

        meta = {
            "format": "raw",
            "fps_effective": fps_effective,
            "fps_target_hint": fps_target,
            "frames_written": frames,
            "duration_s": round(actual_duration, 6),
            "exposure_us": 0,
            "gain": None,
            "full_frame_w": width,
            "full_frame_h": height,
            "record_roi": {"x": 0, "y": 0, "w": width, "h": height},
            "pixel_format": "Mono8",
            "frame_bytes": frame_bytes,
            "dtype": "uint8",
            "raw_path": raw_path,
            "timestamps_path": ts_path,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dropped_frames": 0,
            "simulated": True,
            "pattern": pattern,
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return {
            "fps_effective": fps_effective,
            "frames_written": frames,
            "dropped_frames": 0,
            "raw_path": raw_path,
            "meta_path": meta_path,
            "ts_path": ts_path,
        }

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
        try:
            self._cam.OffsetX.SetValue(0)
        except Exception:
            pass
        try:
            self._cam.OffsetY.SetValue(0)
        except Exception:
            pass
        try:
            self._cam.Width.SetValue(self._cam.Width.Max)
        except Exception:
            pass
        try:
            self._cam.Height.SetValue(self._cam.Height.Max)
        except Exception:
            pass

    def _apply_roi(self, w: int, h: int, ox: int, oy: int) -> None:
        """Apply ROI to camera. Order matters: offsets first (set to 0), then size, then offsets."""
        # Reset offsets first
        try:
            self._cam.OffsetX.SetValue(0)
        except Exception:
            pass
        try:
            self._cam.OffsetY.SetValue(0)
        except Exception:
            pass
        try:
            self._cam.Width.SetValue(w)
        except Exception:
            pass
        try:
            self._cam.Height.SetValue(h)
        except Exception:
            pass
        try:
            self._cam.OffsetX.SetValue(ox)
        except Exception:
            pass
        try:
            self._cam.OffsetY.SetValue(oy)
        except Exception:
            pass

    def _set_exposure(self, us: float) -> None:
        try:
            self._cam.ExposureTime.SetValue(float(us))
        except Exception:
            pass

    def _set_gain(self, val: float) -> None:
        try:
            self._cam.Gain.SetValue(float(val))
        except Exception:
            pass

    def set_exposure_live(self, us: float) -> Optional[float]:
        """Apply exposure (µs) to camera; tries immediate set, queues for grab thread on failure."""
        if not self.is_connected:
            return None
        us = float(us)
        try:
            self._cam.ExposureTime.SetValue(us)
            val = float(self._cam.ExposureTime.Value)
            with self._settings_lock:
                self._readback_exposure_us = val
            return val
        except Exception:
            pass
        # Node locked while grabbing — queue for grab-thread application
        with self._settings_lock:
            self._pending_exposure_us = us
        return us

    def set_gain_live(self, db: float) -> Optional[float]:
        """Apply gain (dB) to camera; tries Gain node then GainRaw fallback, queues on failure."""
        if not self.is_connected:
            return None
        db = float(db)
        # Try Gain (dB, modern cameras)
        try:
            self._cam.Gain.SetValue(db)
            val = float(self._cam.Gain.Value)
            with self._settings_lock:
                self._readback_gain_db = val
            return val
        except Exception:
            pass
        # Try GainRaw (integer steps, older cameras)
        try:
            self._cam.GainRaw.SetValue(int(round(db)))
            val = float(self._cam.GainRaw.Value)
            with self._settings_lock:
                self._readback_gain_db = val
            return val
        except Exception:
            pass
        # Queue for grab-thread application
        with self._settings_lock:
            self._pending_gain_db = db
        return db

    def get_camera_settings(self) -> dict:
        """Return last confirmed camera exposure/gain values (from read-back after set)."""
        with self._settings_lock:
            return {
                "exposure_us": self._readback_exposure_us,
                "gain_db": self._readback_gain_db,
            }

    def _set_pixel_format(self, fmt: str) -> None:
        try:
            self._cam.PixelFormat.SetValue(fmt)
        except Exception:
            pass  # Camera may not support the format

