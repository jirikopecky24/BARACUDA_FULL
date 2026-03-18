"""XIMC stage backend.

Uses pyximc (Standa XILab Python SDK). Import is lazy — if pyximc is not
installed the module loads cleanly and XIMC_AVAILABLE is False.

Mirrors the pypylon guard pattern used in BaslerCamera.
"""
from __future__ import annotations

import time
import threading
from typing import Optional

from .stage_base import AbstractStage, MotionResult, StageDeviceInfo

try:
    import pyximc  # type: ignore
    from pyximc import lib as _lib  # type: ignore
    XIMC_AVAILABLE = True
except Exception:
    XIMC_AVAILABLE = False
    pyximc = None
    _lib = None


def enumerate_ximc_devices() -> list[StageDeviceInfo]:
    """Return a list of discoverable XIMC devices, or empty list if SDK unavailable."""
    if not XIMC_AVAILABLE:
        return []
    try:
        probe_flags = pyximc.EnumerateFlags.ENUMERATE_PROBE
        device_names = _lib.enumerate_devices(probe_flags, None)
        count = _lib.get_device_count(device_names)
        results: list[StageDeviceInfo] = []
        for i in range(count):
            raw = _lib.get_device_name(device_names, i)
            dev_id = raw.decode() if isinstance(raw, bytes) else str(raw)
            results.append(StageDeviceInfo(
                device_id=dev_id,
                display_name=f"XIMC #{i}: {dev_id}",
                backend="ximc",
            ))
        return results
    except Exception:
        return []


class XimcStage(AbstractStage):
    """XIMC/Standa stage backend.

    Step-unit ↔ user-unit conversion:
      By default 1 step = 1 user unit (raw encoder steps).
      Set stage_um_per_unit on the instance if the scale is known.
    """

    CONTROLLER_NAME = "ximc"

    def __init__(self, stage_um_per_unit: Optional[float] = None) -> None:
        if not XIMC_AVAILABLE:
            raise RuntimeError(
                "pyximc is not installed. "
                "Install the Standa XILab SDK and run: pip install pyximc"
            )
        self._device_id: Optional[int] = None   # open device handle
        self._dev_str: str = ""
        self.stage_um_per_unit = stage_um_per_unit

    # ------------------------------------------------------------------
    # AbstractStage interface
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._device_id is not None

    def connect(self, device_id: str) -> None:
        if self._device_id is not None:
            self.disconnect()
        handle = _lib.open_device(device_id.encode())
        if handle == -1:
            raise RuntimeError(f"XIMC: failed to open device {device_id!r}")
        self._device_id = handle
        self._dev_str = device_id

    def disconnect(self) -> None:
        if self._device_id is not None:
            try:
                _lib.close_device(self._device_id)
            except Exception:
                pass
            self._device_id = None

    def get_position(self) -> float:
        self._require_connected()
        pos = pyximc.get_position_t()
        result = _lib.get_position(self._device_id, pos)
        if result != pyximc.Result.Ok:
            raise RuntimeError(f"XIMC get_position failed: {result}")
        return float(pos.Position)

    def move_constant_velocity(
        self,
        direction: int,
        travel: float,
        speed: float,
        accel: float,
        decel: float,
        stop_event: Optional[threading.Event] = None,
    ) -> MotionResult:
        self._require_connected()

        pos_before = self.get_position()
        t_start = time.perf_counter()

        # Set speed profile
        mvst = pyximc.move_settings_t()
        r = _lib.get_move_settings(self._device_id, mvst)
        if r != pyximc.Result.Ok:
            raise RuntimeError(f"XIMC get_move_settings failed: {r}")
        mvst.Speed = max(1, int(round(abs(speed))))
        mvst.Accel = max(1, int(round(abs(accel))))
        mvst.Decel = max(1, int(round(abs(decel))))
        r = _lib.set_move_settings(self._device_id, mvst)
        if r != pyximc.Result.Ok:
            raise RuntimeError(f"XIMC set_move_settings failed: {r}")

        # Compute target position
        signed_travel = int(round(abs(travel) * direction))
        target = int(pos_before) + signed_travel
        r = _lib.command_move(self._device_id, target, 0)
        if r != pyximc.Result.Ok:
            raise RuntimeError(f"XIMC command_move failed: {r}")

        # Poll until stopped
        status = pyximc.status_t()
        while True:
            if stop_event is not None and stop_event.is_set():
                self.stop()
                break
            r = _lib.get_status(self._device_id, status)
            if r != pyximc.Result.Ok:
                raise RuntimeError(f"XIMC get_status failed: {r}")
            moving_flags = (
                pyximc.MoveState.MOVE_STATE_MOVING
                | pyximc.MoveState.MOVE_STATE_TARGET_SPEED
            )
            if not (status.MvCmdSts & pyximc.MvcmdStatus.MVCMD_RUNNING):
                break
            time.sleep(0.005)

        t_stop = time.perf_counter()
        pos_after = self.get_position()
        actual_travel = abs(pos_after - pos_before)
        actual_duration = t_stop - t_start
        actual_speed = actual_travel / actual_duration if actual_duration > 0 else 0.0

        return MotionResult(
            actual_travel_user=actual_travel,
            actual_duration_s=actual_duration,
            actual_speed_user_s=actual_speed,
            controller=self.CONTROLLER_NAME,
            stage_um_per_unit=self.stage_um_per_unit,
        )

    def stop(self) -> None:
        if self._device_id is not None:
            try:
                _lib.command_sstp(self._device_id)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_connected(self) -> None:
        if self._device_id is None:
            raise RuntimeError("XIMC stage is not connected")
