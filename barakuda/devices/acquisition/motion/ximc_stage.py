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
from ctypes import byref
from typing import Optional

from .stage_base import AbstractStage, MotionResult, MotionTraceSample, StageDeviceInfo

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


def _is_nonfatal_alarm_combo(flags: int) -> bool:
    """
    Allow known nonfatal ALARM combinations observed in production setups.

    Observed case:
    - XILab shows HOMD + ErrV
    - manual motion is still valid
    - controller Flags include ALARM bit with ErrV (+ optional HOMD)

    We keep fail-loud behavior for all other ALARM combinations.
    """
    alarm = 0x20
    errv = 0x10
    homd = 0x04
    allowed_mask = alarm | errv | homd
    has_alarm = (flags & alarm) != 0
    has_errv = (flags & errv) != 0
    has_only_allowed_bits = (flags & ~allowed_mask) == 0
    return has_alarm and has_errv and has_only_allowed_bits


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

    def get_stage_um_per_unit(self) -> Optional[float]:
        return self.stage_um_per_unit

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
            result = _ll.lib.get_position(self._device_id, byref(pos))
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
        """Execute a constant-velocity move and block until complete.

        Polling is split into two phases to handle the COM-port latency between
        command_move() and the controller actually setting MVCMD_RUNNING:

          Phase 1 — wait for move to start (MVCMD_RUNNING becomes set).
                    Without this, get_status immediately after command_move
                    still sees MVCMD_RUNNING = 0 and the loop exits before
                    the motor moves at all.

          Phase 2 — wait for move to finish (MVCMD_RUNNING clears).
                    Includes a safety timeout proportional to expected travel.
        """
        self._require_connected()

        # #region agent log setup — MUST be before get_position
        import json as _json, pathlib as _pl
        def _dbg(msg, hyp, data):
            e = _json.dumps({"sessionId":"a34608","hypothesisId":hyp,"timestamp":int(time.perf_counter()*1000),"location":"ximc_stage.py","message":msg,"data":data})
            _pl.Path("debug-a34608.log").open("a").write(e+"\n")
        _dbg("move_constant_velocity ENTER", "H1", {"travel": travel, "speed": speed, "direction": direction})
        # #endregion

        # Read initial position (integer steps + microsteps / 256)
        pos_before = self.get_position()
        _dbg("get_position done", "H1", {"pos_before": pos_before})
        speed_reg_commanded_raw: int | None = None
        speed_reg_readback_raw: int | None = None
        pre_motion_flags: int | None = None
        pre_motion_gpio_flags: int | None = None
        pre_motion_mv_cmd_sts: int | None = None
        pre_motion_alarm_nonfatal_allowed: bool | None = None

        # Set speed profile
        if _BACKEND == "libximc":
            mvst = _ll.move_settings_t()
            r = _ll.lib.get_move_settings(self._device_id, byref(mvst))
            if r != _ll.Result.Ok:
                raise RuntimeError(f"XIMC get_move_settings failed: {r}")
            # #region agent log H-A,H-B — before/after move settings
            _dbg("move_settings BEFORE set", "H-B", {
                "pos_before": pos_before,
                "Speed": int(mvst.Speed), "uSpeed": int(mvst.uSpeed),
                "Accel": int(mvst.Accel), "Decel": int(mvst.Decel),
                "AntiplaySpeed": int(mvst.AntiplaySpeed), "MoveFlags": int(mvst.MoveFlags),
            })
            # #endregion
            # Speed is passed DIRECTLY as the XIMC firmware Speed register (1:1 mapping).
            # The XIMC Speed register does NOT map linearly to physical counts/sec —
            # the relationship depends on Accel, travel, motor physics, and MicrostepMode.
            # The K-formula approach (K/Speed_reg) was found empirically incorrect across
            # the useful operating range; predicted vs. actual speed diverged by 8×+.
            #
            # Practical reference (empirical, this motor + 256-microstep config):
            #   Speed=1,   Accel=20  → ~75 c/s  → Travel=1500 takes ~20s  (slow drag mode)
            #   Speed=175, Accel=100 → ~392 c/s → Travel=200  takes ~0.5s (fast mode)
            #
            # Speed=1 matches XILab's SPEED_UNITS_S=1 "default slow drag mode" script.
            # Type safety: ctypes.c_ulong (uint32, max ~4.3e9); Speed=1 is safe.
            _speed_reg = max(1, int(round(abs(speed))))
            speed_reg_commanded_raw = int(_speed_reg)
            mvst.Speed = _speed_reg
            mvst.Accel = max(1, int(round(abs(accel))))
            mvst.Decel = max(1, int(round(abs(decel))))
            r = _ll.lib.set_move_settings(self._device_id, byref(mvst))
            if r != _ll.Result.Ok:
                raise RuntimeError(f"XIMC set_move_settings failed: {r}")
            # read back to verify the controller accepted the values
            mvst_rb = _ll.move_settings_t()
            _ll.lib.get_move_settings(self._device_id, byref(mvst_rb))
            speed_reg_readback_raw = int(mvst_rb.Speed)
            # #region agent log H-A — read-back after set
            _dbg("move_settings AFTER set (readback)", "H-A", {
                "speed_reg_commanded": _speed_reg,
                "speed_reg_readback": int(mvst_rb.Speed),
                "Accel": int(mvst_rb.Accel), "Decel": int(mvst_rb.Decel),
                "set_result": int(r),
            })
            # #endregion
            # #region agent log H-E — engine settings (NomSpeed, MicrostepMode, StepsPerRev)
            eng = _ll.engine_settings_t()
            _ll.lib.get_engine_settings(self._device_id, byref(eng))
            _dbg("engine_settings", "H-E", {
                "NomSpeed": int(eng.NomSpeed), "uNomSpeed": int(eng.uNomSpeed),
                "MicrostepMode": int(eng.MicrostepMode),
                "StepsPerRev": int(eng.StepsPerRev),
                "NomVoltage": int(eng.NomVoltage), "NomCurrent": int(eng.NomCurrent),
                "EngineFlags": int(eng.EngineFlags),
            })
            # #endregion
        else:  # pragma: no cover
            mvst = pyximc.move_settings_t()
            r = _lib.get_move_settings(self._device_id, mvst)
            if r != pyximc.Result.Ok:
                raise RuntimeError(f"XIMC get_move_settings failed: {r}")
            mvst.Speed = max(1, int(round(abs(speed))))
            speed_reg_commanded_raw = int(mvst.Speed)
            mvst.Accel = max(1, int(round(abs(accel))))
            mvst.Decel = max(1, int(round(abs(decel))))
            r = _lib.set_move_settings(self._device_id, mvst)
            if r != pyximc.Result.Ok:
                raise RuntimeError(f"XIMC set_move_settings failed: {r}")
            speed_reg_readback_raw = int(mvst.Speed)

        # ------------------------------------------------------------------
        # Pre-flight: check XIMC status for alarm / limit flags.
        # If controller is in alarm state, abort cleanly (avoid DLL hard fault).
        # ------------------------------------------------------------------
        if _BACKEND == "libximc":
            _pre_status = _ll.status_t()
            _ps_r = _ll.lib.get_status(self._device_id, byref(_pre_status))
            # Flags byte: bit 5 = ALARM, bit 6 = CTP_ERROR, bit 7 = POWER_OVERHEAT
            # GPIOFlags: bit 0/1 = left/right limit switches (controller-dependent)
            _flags = int(getattr(_pre_status, "Flags", 0))
            _gpio = int(getattr(_pre_status, "GPIOFlags", 0))
            pre_motion_flags = _flags
            pre_motion_gpio_flags = _gpio
            pre_motion_mv_cmd_sts = int(getattr(_pre_status, "MvCmdSts", 0))
            _dbg("pre_motion status check", "H1", {
                "get_status_result": int(_ps_r),
                "Flags": _flags,
                "GPIOFlags": _gpio,
                "MvCmdSts": int(getattr(_pre_status, "MvCmdSts", -1)),
                "CurPosition": int(getattr(_pre_status, "CurPosition", -1)),
            })
            # ALARM handling:
            # - keep fail-loud for dangerous ALARM states
            # - allow known nonfatal ErrV(+HOMD) combinations seen in XILab-valid motion
            if _flags & 0x20:
                if _is_nonfatal_alarm_combo(_flags):
                    pre_motion_alarm_nonfatal_allowed = True
                    _dbg(
                        "pre_motion nonfatal alarm combo allowed",
                        "H1",
                        {
                            "Flags": _flags,
                            "note": "ALARM+ErrV(+HOMD) treated as nonfatal for this setup",
                        },
                    )
                else:
                    pre_motion_alarm_nonfatal_allowed = False
                    raise RuntimeError(
                        f"XIMC controller is in ALARM state (Flags=0x{_flags:02X}). "
                        "Home the stage in XILab and reset the controller before moving."
                    )
            else:
                pre_motion_alarm_nonfatal_allowed = False
            # If controller already reports RUNNING from a previous command, stop it first.
            if int(getattr(_pre_status, "MvCmdSts", 0)) & 0x01:
                _ll.lib.command_stop(self._device_id)
                time.sleep(0.15)  # let stop propagate before issuing new move

        # Issue the move command (asynchronous — motor starts after latency)
        signed_travel = int(round(abs(travel) * direction))
        target = int(pos_before) + signed_travel
        # #region agent log — command_move target
        _dbg("command_move", "H-SPEED", {"pos_before": pos_before, "target": target, "signed_travel": signed_travel, "commanded_speed": speed})
        # #endregion
        t_command_issued = time.perf_counter()
        motion_profile_samples: list[MotionTraceSample] = []
        if _BACKEND == "libximc":
            r = _ll.lib.command_move(self._device_id, target, 0)
            if r != _ll.Result.Ok:
                raise RuntimeError(f"XIMC command_move failed: {r}")
            status = _ll.status_t()
            _running_flag = _ll.MvcmdStatus.MVCMD_RUNNING
            _result_ok = _ll.Result.Ok


            def _get_status() -> int:
                return _ll.lib.get_status(self._device_id, byref(status))

        else:  # pragma: no cover
            r = _lib.command_move(self._device_id, target, 0)
            if r != pyximc.Result.Ok:
                raise RuntimeError(f"XIMC command_move failed: {r}")
            status = pyximc.status_t()
            _running_flag = pyximc.MvcmdStatus.MVCMD_RUNNING
            _result_ok = pyximc.Result.Ok

            def _get_status() -> int:  # type: ignore[misc]
                return _lib.get_status(self._device_id, status)

        # ------------------------------------------------------------------
        # Phase 1: wait for MVCMD_RUNNING to be set (motor has started).
        # command_move is asynchronous; over a COM port the controller may
        # need 20–100 ms before it reflects the new state in get_status.
        # Without this phase the loop below would exit immediately.
        # ------------------------------------------------------------------
        _PHASE1_TIMEOUT_S = 2.0
        _phase1_deadline = time.perf_counter() + _PHASE1_TIMEOUT_S
        while True:
            r = _get_status()
            if r != _result_ok:
                raise RuntimeError(f"XIMC get_status (phase1) failed: {r}")
            if status.MvCmdSts & _running_flag:
                break
            if time.perf_counter() > _phase1_deadline:
                raise RuntimeError(
                    "XIMC: motor did not start within "
                    f"{_PHASE1_TIMEOUT_S:.1f} s of command_move. "
                    "Check speed/accel settings and hardware."
                )
            time.sleep(0.010)

        # t_start is captured once MVCMD_RUNNING is confirmed set
        t_start = time.perf_counter()
        running_confirmed_delay_s = max(0.0, t_start - t_command_issued)
        motion_profile_samples.append(
            MotionTraceSample(
                t_offset_s=running_confirmed_delay_s,
                position_user=float(getattr(status, "CurPosition", 0))
                + (float(getattr(status, "uCurPosition", 0)) / 256.0),
                velocity_user_s=float(getattr(status, "CurSpeed", 0))
                + (float(getattr(status, "uCurSpeed", 0)) / 256.0),
                state="moving_confirmed",
            )
        )

        # ------------------------------------------------------------------
        # Phase 2: wait for MVCMD_RUNNING to clear (move finished).
        # Speed is now a raw XIMC register (not c/s), so travel/speed is not a reliable
        # time estimate. Use a generous fixed timeout: max(60s, travel×0.1 + 30s).
        # For Speed=1/Travel=1500 this gives 180s — the actual motion is ~20s.
        # ------------------------------------------------------------------
        _phase2_timeout_s = max(60.0, abs(travel) * 0.1 + 30.0)
        _phase2_deadline = t_start + _phase2_timeout_s

        _p2_n = 0
        while True:
            if stop_event is not None and stop_event.is_set():
                self.stop()
                break
            r = _get_status()
            if r != _result_ok:
                raise RuntimeError(f"XIMC get_status (phase2) failed: {r}")
            # #region agent log H-C — log CurSpeed during motion (first 3 polls)
            if _p2_n < 3:
                _dbg("phase2 poll", "H-C", {
                    "n": _p2_n,
                    "CurSpeed": int(getattr(status, "CurSpeed", -1)),
                    "uCurSpeed": int(getattr(status, "uCurSpeed", -1)),
                    "CurPosition": int(getattr(status, "CurPosition", -1)),
                    "MvCmdSts": int(status.MvCmdSts),
                })
            _p2_n += 1
            t_now = time.perf_counter()
            motion_profile_samples.append(
                MotionTraceSample(
                    t_offset_s=max(0.0, t_now - t_command_issued),
                    position_user=float(getattr(status, "CurPosition", 0))
                    + (float(getattr(status, "uCurPosition", 0)) / 256.0),
                    velocity_user_s=float(getattr(status, "CurSpeed", 0))
                    + (float(getattr(status, "uCurSpeed", 0)) / 256.0),
                    state="moving",
                )
            )
            # #endregion
            if not (status.MvCmdSts & _running_flag):
                break
            if time.perf_counter() > _phase2_deadline:
                self.stop()
                raise RuntimeError(
                    f"XIMC: move timeout after {_phase2_timeout_s:.1f} s "
                    f"(travel={travel}, speed={speed})"
                )
            # Polling interval intentionally kept small but not overly aggressive:
            # tight 200Hz polling can starve the Qt main thread enough that the
            # acquisition live preview appears stalled during Record+Motion.
            # This does NOT change the motion physics; it only bounds how quickly
            # we observe MVCMD_RUNNING clearing (<= ~10ms detection granularity).
            time.sleep(0.010)

        t_stop = time.perf_counter()

        # Read final position from the last status response
        # (status_t has CurPosition + uCurPosition; saves a COM round-trip)
        pos_after = (
            float(status.CurPosition) + float(status.uCurPosition) / 256.0
        )
        actual_travel = abs(pos_after - pos_before)
        actual_duration = t_stop - t_start
        actual_speed = actual_travel / actual_duration if actual_duration > 0 else 0.0
        # #region agent log H-SPEED — move result
        _dbg("move_result", "H-SPEED", {
            "pos_before": pos_before, "pos_after": pos_after,
            "actual_travel": actual_travel, "actual_duration_s": actual_duration,
            "actual_speed": actual_speed, "commanded_speed": speed,
            "phase2_polls": _p2_n,
        })
        # #endregion

        return MotionResult(
            actual_travel_user=actual_travel,
            actual_duration_s=actual_duration,
            actual_speed_user_s=actual_speed,
            controller=self.CONTROLLER_NAME,
            stage_um_per_unit=self.stage_um_per_unit,
            running_confirmed_delay_s=running_confirmed_delay_s,
            commanded_speed_raw=float(speed_reg_commanded_raw) if speed_reg_commanded_raw is not None else None,
            speed_reg_readback_raw=float(speed_reg_readback_raw) if speed_reg_readback_raw is not None else None,
            pre_motion_flags=pre_motion_flags,
            pre_motion_gpio_flags=pre_motion_gpio_flags,
            pre_motion_mv_cmd_sts=pre_motion_mv_cmd_sts,
            pre_motion_alarm_nonfatal_allowed=pre_motion_alarm_nonfatal_allowed,
            motion_profile_samples=tuple(motion_profile_samples),
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
