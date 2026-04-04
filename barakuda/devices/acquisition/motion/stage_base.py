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
    # Optional backend diagnostics for speed-control auditability.
    commanded_speed_raw: Optional[float] = None
    speed_reg_readback_raw: Optional[float] = None
    pre_motion_flags: Optional[int] = None
    pre_motion_gpio_flags: Optional[int] = None
    pre_motion_mv_cmd_sts: Optional[int] = None
    pre_motion_alarm_nonfatal_allowed: Optional[bool] = None


class AbstractStage(ABC):
    """Minimal stage backend interface.

    Backends must implement connect/disconnect, get_position, and move_constant_velocity.
    They must NOT know about recording, physics, or DRAG analysis.

    Unit contract for Acquisition Motion workflow:
    - travel is stage user units (derived from UI travel_um / stage_um_per_unit)
    - speed/accel/decel are backend command units. For XIMC this is raw firmware
      register semantics, not metric µm/s or µm/s².
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
        speed: float,            # backend command units (XIMC raw register path)
        accel: float,            # backend command units (XIMC raw register path)
        decel: float,            # backend command units (XIMC raw register path)
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
