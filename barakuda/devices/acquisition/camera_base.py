"""Abstract camera interface and device-info dataclass.

Any camera backend (Basler, webcam, IDS, FLIR, …) must subclass AbstractCamera
and implement every abstract method.  The camera_factory module uses this
interface so that the rest of the application never needs to know which
physical SDK is in use.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class CameraDeviceInfo:
    """Describes one enumerated camera device."""

    backend: str          # e.g. "basler", "webcam", "ids", "flir"
    index: int            # SDK-specific index / slot
    display_name: str     # human-readable label shown in the selection dialog
    serial: str = ""
    model: str = ""
    extra: dict = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [self.display_name]
        if self.serial:
            parts.append(f"S/N {self.serial}")
        return "  |  ".join(parts)


class AbstractCamera(ABC):
    """Protocol that every camera backend must satisfy.

    Lifecycle
    ---------
    1. ``cls.enumerate()``  — discover available devices (class method, no side-effects)
    2. ``connect(info)``    — open the chosen device
    3. preview / record operations
    4. ``disconnect()``     — release the device

    Thread safety
    -------------
    All methods may be called from the Qt main thread.  Implementations are
    responsible for any internal threading they need.
    """

    # ------------------------------------------------------------------ #
    #  Enumeration                                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    @abstractmethod
    def enumerate(cls) -> list[CameraDeviceInfo]:
        """Return a list of available devices for this backend.

        Must never raise — return an empty list if the SDK is unavailable or
        no devices are found.
        """

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def connect(self, info: CameraDeviceInfo) -> None:
        """Open the device described by *info*."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the device and release all resources."""

    # ------------------------------------------------------------------ #
    #  State properties                                                    #
    # ------------------------------------------------------------------ #

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @property
    @abstractmethod
    def is_previewing(self) -> bool: ...

    # ------------------------------------------------------------------ #
    #  Sensor info                                                         #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def get_sensor_size(self) -> tuple[int, int]:
        """Return (width, height) of the full sensor in pixels."""

    @abstractmethod
    def get_roi_config(self) -> dict:
        """Return ROI alignment constraints.

        Required keys (all int):
            w_inc, h_inc, ox_inc, oy_inc  — alignment increments (≥1)
            w_min, h_min                   — minimum ROI dimensions
        """

    # ------------------------------------------------------------------ #
    #  Preview                                                             #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def start_preview(self, callback, exposure_us: Optional[float] = None) -> None:
        """Start live preview.  *callback* kept for API compatibility but
        implementations may ignore it in favour of the latest-frame buffer."""

    @abstractmethod
    def stop_preview(self) -> None:
        """Stop live preview."""

    @abstractmethod
    def get_latest_preview(self) -> tuple[Optional[np.ndarray], float]:
        """Return ``(frame, timestamp)`` of the most recent preview frame.

        Returns ``(None, 0.0)`` if no frame is available yet.
        """

    # ------------------------------------------------------------------ #
    #  Camera settings                                                     #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def set_exposure_live(self, us: float) -> Optional[float]:
        """Set exposure to *us* microseconds; return actual value or None."""

    @abstractmethod
    def set_gain_live(self, db: float) -> Optional[float]:
        """Set gain to *db* dB; return actual value or None."""

    # ------------------------------------------------------------------ #
    #  FPS utilities                                                       #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def test_fps(self, **kwargs) -> dict:
        """Run a quick FPS measurement and return a result dict."""

    @abstractmethod
    def benchmark_fps(self, **kwargs) -> dict:
        """Run a longer benchmark and return a result dict."""

    # ------------------------------------------------------------------ #
    #  Recording                                                           #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def stop_record(self) -> None:
        """Stop any in-progress recording."""
