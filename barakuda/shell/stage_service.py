from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, Literal

from barakuda.devices.acquisition.motion.stage_base import AbstractStage


LeaseOwner = Literal["acquisition", "stage_console"]


@dataclass(frozen=True)
class StageLeaseState:
    connected: bool
    owner: Optional[LeaseOwner]
    busy: bool
    run_active: bool
    stage_um_per_unit: Optional[float]
    monitor_only_reason: Optional[str] = None


class StageService:
    """Process-wide stage connection + exclusive control lease.

    Design goals:
    - single stage connection per process (no competing command streams)
    - explicit lease ownership (acquisition vs stage_console)
    - MVP-safe: stage_console is monitor-only during acquisition / active runs
    """

    # Internal defaults: XIMC registers (NOT user-facing metric values)
    _DEFAULT_SPEED_REG = 50.0
    _DEFAULT_ACCEL_REG = 100.0
    _DEFAULT_DECEL_REG = 100.0

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stage: AbstractStage | None = None
        self._stage_um_per_unit: Optional[float] = None
        self._owner: Optional[LeaseOwner] = None
        self._busy: bool = False
        self._run_active: bool = False

    # ---------------- basic accessors ----------------
    @property
    def stage(self) -> AbstractStage | None:
        with self._lock:
            return self._stage

    def lease_state(self) -> StageLeaseState:
        with self._lock:
            connected = bool(self._stage is not None and self._stage.is_connected)
            reason: Optional[str] = None
            if self._run_active and self._owner != "acquisition":
                reason = "Acquisition active (Record+Motion)"
            return StageLeaseState(
                connected=connected,
                owner=self._owner,
                busy=self._busy,
                run_active=self._run_active,
                stage_um_per_unit=self._stage_um_per_unit,
                monitor_only_reason=reason,
            )

    # ---------------- connection (owned by acquisition UI path) ----------------
    def connect_ximc(self, *, uri: str, stage_um_per_unit: Optional[float]) -> None:
        """Connect using the existing XIMC backend.

        Note: this does not automatically grant the control lease to acquisition.
        Lease is acquired explicitly when needed (e.g., starting Record+Motion).
        """
        from barakuda.devices.acquisition.motion.ximc_stage import XimcStage

        with self._lock:
            if self._stage is not None and self._stage.is_connected:
                # Already connected (single shared connection per process).
                return
            st = XimcStage(stage_um_per_unit=stage_um_per_unit)
            st.connect(uri)
            self._stage = st
            self._stage_um_per_unit = stage_um_per_unit
            self._owner = None
            self._busy = False
            self._run_active = False

    def disconnect(self) -> None:
        with self._lock:
            if self._busy or self._run_active:
                raise RuntimeError("Stage is busy; cannot disconnect.")
            if self._stage is not None:
                self._stage.disconnect()
            self._stage = None
            self._stage_um_per_unit = None
            self._owner = None
            self._busy = False
            self._run_active = False

    # ---------------- lease / acquisition interaction ----------------
    def request_lease(self, owner: LeaseOwner, *, force: bool = False) -> tuple[bool, str]:
        with self._lock:
            if self._stage is None or not self._stage.is_connected:
                return False, "Stage not connected."
            if self._run_active and owner != "acquisition":
                return False, "Monitor-only: acquisition is active."
            if self._busy and self._owner != owner:
                return False, "Stage busy."
            if self._owner is None or self._owner == owner:
                self._owner = owner
                return True, "OK"
            if force and owner == "acquisition":
                # Acquisition priority takeover (Phase 3 policy).
                self._owner = owner
                return True, "OK (forced takeover)"
            return False, f"Stage owned by {self._owner}."

    def release_lease(self, owner: LeaseOwner) -> None:
        with self._lock:
            if self._owner != owner:
                return
            if self._run_active:
                return
            if self._busy:
                return
            self._owner = None

    def set_run_active(self, active: bool) -> None:
        with self._lock:
            self._run_active = bool(active)
            if self._run_active:
                # Ensure acquisition owns the lease while running.
                self._owner = "acquisition"

    # ---------------- safe readbacks ----------------
    def get_position_um(self) -> Optional[float]:
        with self._lock:
            if self._stage is None or not self._stage.is_connected:
                return None
            if self._stage_um_per_unit is None or self._stage_um_per_unit <= 0:
                return None
            pos_user = float(self._stage.get_position())
            return pos_user * float(self._stage_um_per_unit)

    # ---------------- manual control (Phase 6) ----------------
    def stop(self, *, owner: LeaseOwner) -> None:
        with self._lock:
            if self._stage is None or not self._stage.is_connected:
                raise RuntimeError("Stage not connected.")
            if self._owner != owner:
                raise RuntimeError("Stop not permitted: not lease owner.")
            # MVP policy: stop only available to current lease owner (Option A).
            self._stage.stop()

    def move_relative_um(self, *, owner: LeaseOwner, delta_um: float) -> None:
        with self._lock:
            if self._stage is None or not self._stage.is_connected:
                raise RuntimeError("Stage not connected.")
            if self._run_active:
                raise RuntimeError("Monitor-only: acquisition is active.")
            if self._owner != owner:
                raise RuntimeError("Move not permitted: not lease owner.")
            if self._busy:
                raise RuntimeError("Stage busy.")
            if self._stage_um_per_unit is None or self._stage_um_per_unit <= 0:
                raise RuntimeError("Stage scale (µm/unit) is unknown; cannot move in metric units.")
            self._busy = True

        try:
            # Convert metric intent (µm) to stage user units for travel only.
            travel_user = abs(float(delta_um)) / float(self._stage_um_per_unit)
            direction = 1 if float(delta_um) >= 0 else -1
            self._stage.move_constant_velocity(
                direction=direction,
                travel=travel_user,
                speed=self._DEFAULT_SPEED_REG,
                accel=self._DEFAULT_ACCEL_REG,
                decel=self._DEFAULT_DECEL_REG,
                stop_event=None,
            )
        finally:
            with self._lock:
                self._busy = False

    def move_to_um(self, *, owner: LeaseOwner, target_um: float) -> None:
        with self._lock:
            if self._stage is None or not self._stage.is_connected:
                raise RuntimeError("Stage not connected.")
            if self._stage_um_per_unit is None or self._stage_um_per_unit <= 0:
                raise RuntimeError("Stage scale (µm/unit) is unknown; cannot move in metric units.")
            pos_user = float(self._stage.get_position())
            current_um = pos_user * float(self._stage_um_per_unit)
            delta_um = float(target_um) - float(current_um)
        self.move_relative_um(owner=owner, delta_um=delta_um)


_STAGE_SERVICE_SINGLETON: StageService | None = None


def get_stage_service() -> StageService:
    global _STAGE_SERVICE_SINGLETON
    if _STAGE_SERVICE_SINGLETON is None:
        _STAGE_SERVICE_SINGLETON = StageService()
    return _STAGE_SERVICE_SINGLETON

