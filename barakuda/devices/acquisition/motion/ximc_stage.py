"""XIMC stage backend (Standa XIMC / XILab).

This project targets Windows and must work with typical XILab installations.

Important: XIMC devices may enumerate as USB ("probe") *or* as serial COM ports.
For example, the same controller visible in XILab may only show up via
ENUMERATE_ALL_COM (URIs like ``xi-com:\\\\.\\COM5``). Therefore the backend
must enumerate more than just PROBE.

Dependency strategy:
- Prefer `libximc` (PyPI) because it ships its own ctypes bindings and bundled
  DLLs under `libximc/library-files/` and is installable into the BARAKUDA env.
- Fall back to vendor `pyximc` (if present) for compatibility.
"""
from __future__ import annotations

import time
import threading
from typing import Optional

from .stage_base import AbstractStage, MotionResult, StageDeviceInfo

try:
    # Preferred: PyPI libximc
    from libximc import highlevel as _hl  # type: ignore
    from libximc.lowlevel import _lowlevel as _ll  # type: ignore

    _BACKEND = "libximc"
    XIMC_AVAILABLE = True
except Exception:
    try:
        # Fallback: vendor pyximc (not available on PyPI on Windows in many setups)
        import pyximc  # type: ignore
        from pyximc import lib as _lib  # type: ignore

        _BACKEND = "pyximc"
        XIMC_AVAILABLE = True
    except Exception:
        XIMC_AVAILABLE = False
        _BACKEND = "none"
        pyximc = None  # type: ignore
        _lib = None  # type: ignore
        _hl = None  # type: ignore
        _ll = None  # type: ignore


def enumerate_ximc_devices() -> list[StageDeviceInfo]:
    """Return a list of discoverable XIMC devices, or empty list if SDK unavailable."""
    if not XIMC_AVAILABLE:
        return []
    results: list[StageDeviceInfo] = []

    # Prefer libximc highlevel.enumerate_devices if available.
    if _BACKEND == "libximc":
        try:
            # Try PROBE first (USB), then COM (serial), then NETWORK.
            for flag in (
                _hl.EnumerateFlags.ENUMERATE_PROBE,
                _hl.EnumerateFlags.ENUMERATE_ALL_COM,
                _hl.EnumerateFlags.ENUMERATE_NETWORK,
            ):
                devs = _hl.enumerate_devices(flag)
                for d in devs:
                    uri = str(d.get("uri") or "").strip()
                    if not uri:
                        continue
                    results.append(
                        StageDeviceInfo(
                            device_id=uri,
                            display_name=f"XIMC: {uri}",
                            backend="ximc",
                        )
                    )
            # De-duplicate by device_id while preserving order
            seen: set[str] = set()
            uniq: list[StageDeviceInfo] = []
            for r in results:
                if r.device_id in seen:
                    continue
                seen.add(r.device_id)
                uniq.append(r)
            return uniq
        except Exception:
            return []

    # Fallback: vendor pyximc enumerate_devices
    try:  # pragma: no cover
        probe_flags = pyximc.EnumerateFlags.ENUMERATE_PROBE
        device_names = _lib.enumerate_devices(probe_flags, None)
        count = _lib.get_device_count(device_names)
        for i in range(count):
            raw = _lib.get_device_name(device_names, i)
            dev_id = raw.decode() if isinstance(raw, bytes) else str(raw)
            results.append(
                StageDeviceInfo(
                    device_id=dev_id,
                    display_name=f"XIMC #{i}: {dev_id}",
                    backend="ximc",
                )
            )
        return results
    except Exception:  # pragma: no cover
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
                "XIMC backend is not available. "
                "Install `libximc` into the BARAKUDA env (recommended), "
                "or vendor `pyximc` from the XILab SDK."
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
        if _BACKEND == "libximc":
            handle = _ll.lib.open_device(device_id.encode())
        else:  # pragma: no cover
            handle = _lib.open_device(device_id.encode())
        if handle == -1:
            raise RuntimeError(f"XIMC: failed to open device {device_id!r}")
        self._device_id = handle
        self._dev_str = device_id

    def disconnect(self) -> None:
        if self._device_id is not None:
            try:
                if _BACKEND == "libximc":
                    _ll.lib.close_device(self._device_id)
                else:  # pragma: no cover
                    _lib.close_device(self._device_id)
            except Exception:
                pass
            self._device_id = None

    def get_position(self) -> float:
        self._require_connected()
        if _BACKEND == "libximc":
            pos = _ll.get_position_t()
            result = _ll.lib.get_position(self._device_id, pos)
            if result != _ll.Result.Ok:
                raise RuntimeError(f"XIMC get_position failed: {result}")
            # XIMC reports position as integer steps + microsteps (uPosition, 1/256 step).
            return float(pos.Position) + (float(pos.uPosition) / 256.0)
        else:  # pragma: no cover
            pos = pyximc.get_position_t()
            result = _lib.get_position(self._device_id, pos)
            if result != pyximc.Result.Ok:
                raise RuntimeError(f"XIMC get_position failed: {result}")
            return float(pos.Position) + (float(getattr(pos, "uPosition", 0)) / 256.0)

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
        if _BACKEND == "libximc":
            mvst = _ll.move_settings_t()
            r = _ll.lib.get_move_settings(self._device_id, mvst)
            if r != _ll.Result.Ok:
                raise RuntimeError(f"XIMC get_move_settings failed: {r}")
            mvst.Speed = max(1, int(round(abs(speed))))
            mvst.Accel = max(1, int(round(abs(accel))))
            mvst.Decel = max(1, int(round(abs(decel))))
            r = _ll.lib.set_move_settings(self._device_id, mvst)
            if r != _ll.Result.Ok:
                raise RuntimeError(f"XIMC set_move_settings failed: {r}")
        else:  # pragma: no cover
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
        if _BACKEND == "libximc":
            r = _ll.lib.command_move(self._device_id, target, 0)
            if r != _ll.Result.Ok:
                raise RuntimeError(f"XIMC command_move failed: {r}")
        else:  # pragma: no cover
            r = _lib.command_move(self._device_id, target, 0)
            if r != pyximc.Result.Ok:
                raise RuntimeError(f"XIMC command_move failed: {r}")

        # Poll until stopped
        status = _ll.status_t() if _BACKEND == "libximc" else pyximc.status_t()  # type: ignore[name-defined]
        while True:
            if stop_event is not None and stop_event.is_set():
                self.stop()
                break
            if _BACKEND == "libximc":
                r = _ll.lib.get_status(self._device_id, status)
                if r != _ll.Result.Ok:
                    raise RuntimeError(f"XIMC get_status failed: {r}")
                if not (status.MvCmdSts & _ll.MvcmdStatus.MVCMD_RUNNING):
                    break
            else:  # pragma: no cover
                r = _lib.get_status(self._device_id, status)
                if r != pyximc.Result.Ok:
                    raise RuntimeError(f"XIMC get_status failed: {r}")
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
                if _BACKEND == "libximc":
                    _ll.lib.command_sstp(self._device_id)
                else:  # pragma: no cover
                    _lib.command_sstp(self._device_id)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_connected(self) -> None:
        if self._device_id is None:
            raise RuntimeError("XIMC stage is not connected")
