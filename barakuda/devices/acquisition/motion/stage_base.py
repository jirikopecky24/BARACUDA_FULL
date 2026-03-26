"""Abstract stage interface.

Defines the minimal contract every stage backend must satisfy.
Motion physics and drag analysis are never the concern of this layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class StageDeviceInfo:
    """Identification record for a discovered stage device."""
    device_id: str
    display_name: str
    backend: str  # e.g. "ximc", "sim"

    def __str__(self) -> str:
        return f"{self.display_name} [{self.backend} / {self.device_id}]"


@dataclass
class MotionResult:
    """Outcome reported after a move command completes."""
    actual_travel_user: float        # in stage user units
    actual_duration_s: float         # wall-clock seconds from move start to stop
    actual_speed_user_s: float       # derived: actual_travel / actual_duration
    controller: str                  # backend name, e.g. "ximc"
    stage_um_per_unit: Optional[float] = None  # if known from backend
    # Optional backend-reported delay between move command issuance and confirmed
    # transition to controller running state.
    running_confirmed_delay_s: Optional[float] = None


class AbstractStage(ABC):
    """Minimal stage backend interface.

    Backends must implement connect/disconnect, get_position, and move_constant_velocity.
    They must NOT know about recording, physics, or DRAG analysis.
    """

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def connect(self, device_id: str) -> None:
        """Connect to the stage device by ID."""

    @abstractmethod
    def disconnect(self) -> None:
        """Release the stage connection cleanly."""

    @abstractmethod
    def get_position(self) -> float:
        """Return current position in stage user units."""

    @abstractmethod
    def move_constant_velocity(
        self,
        direction: int,          # +1 or -1
        travel: float,           # user units
        speed: float,            # user units / s
        accel: float,            # user units / s²
        decel: float,            # user units / s²
        stop_event=None,         # threading.Event — checked during move for early abort
    ) -> MotionResult:
        """Execute a constant-velocity move and block until complete.

        Returns a MotionResult with actual measured values.
        Raises RuntimeError on hardware failure.
        """

    @abstractmethod
    def stop(self) -> None:
        """Emergency stop (best effort)."""

    # ------------------------------------------------------------------
    # Optional metadata hooks (non-breaking defaults)
    # ------------------------------------------------------------------
    def get_stage_um_per_unit(self) -> Optional[float]:
        """Return stage scale in µm/user-unit if known.

        Non-abstract default keeps compatibility: backends may return None
        when the scale is not known or not provided.
        """
        return None
