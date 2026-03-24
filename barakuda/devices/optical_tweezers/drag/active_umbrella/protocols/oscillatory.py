from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from ...analysis import analyze_drag_run
from ...io import load_drag_run
from ...schema import Axis, DragAnalysisConfig, DragRunLoaded
from ..trajectory_helpers import _extract_axis_series, _interp_time_for_frames


@dataclass(frozen=True)
class OscillatoryProtocolConfig:
    """Protocol definition for a single-frequency oscillatory active drag.

    NOW: scaffold designed to be offline-testable with synthetic runs.
    FUTURE: real stage/protocol metadata can be added by parsing stage_meta.protocol_params.
    """

    # Frequency of drive (Hz). If None, try stage_meta.protocol_params.
    frequency_hz: float | None = None

    # Drive amplitude in µm (image-axis). If None, try stage_meta.protocol_params.
    drive_amplitude_um: float | None = None

    # If stage JSON stores user amplitude (instead of µm), set this key expectation.
    # Synthetic harness will use `oscillation_amplitude_user`.
    drive_amplitude_user_key: str = "oscillation_amplitude_user"

    # If stage JSON stores direct µm amplitude, key expectation.
    drive_amplitude_um_key: str = "oscillation_amplitude_um"

    # If stage JSON stores frequency, key expectation.
    frequency_key: str = "oscillation_frequency_hz"

    # Cycle segmentation & averaging
    steady_start_cycles: int = 5
    max_cycles_to_use: int | None = None
    min_samples_per_cycle: int = 30

    baseline_subtract: Literal["baseline_median", "steady_median", "none"] = "baseline_median"

    # QC
    require_min_cycles_used: int = 3


@dataclass(frozen=True)
class OscillatoryAnalysisResult:
    basename: str
    axis: Axis

    frequency_hz: float
    omega_rad_s: float

    drive_amplitude_um: float | None
    response_amplitude_um: float | None
    amplitude_ratio: float | None

    # Phase lag of response relative to drive reference sin(omega*(t-t0)).
    phase_lag_rad: float | None
    phase_lag_deg: float | None

    # Cycle stats
    n_cycles_total_available: int
    n_cycles_used: int

    # Alignment context (from DRAG v1 foundation)
    motion_start_stage_s: float
    motion_start_video_s_detected: float
    alignment_offset_s: float

    # Per-cycle results (kept with defaults for backward compatibility)
    cycle_phases_rad: list[float] = field(default_factory=list)
    cycle_amplitudes_um: list[float] = field(default_factory=list)

    # Rheology target placeholder (for future G' / G'')
    # Here we only package complex response from amplitude ratio and phase lag.
    rheology_target: dict[str, float] = field(default_factory=dict)

    analysis_status: str = "ok"
    warnings: list[str] = field(default_factory=list)


def _wrap_phase_to_pi(phi: float) -> float:
    """Normalize phase to (-pi, pi]."""
    # Using atan2 gives a stable normalization without manual modulo issues.
    return float(math.atan2(math.sin(phi), math.cos(phi)))


def analyze_oscillatory_drag_run(
    run_dir,
    drag_config: DragAnalysisConfig,
    osc_config: OscillatoryProtocolConfig,
    trajectory_path=None,
) -> OscillatoryAnalysisResult:
    # 1) Use DRAG v1 stage-aware alignment and baseline statistics as shared foundation.
    drag_result = analyze_drag_run(run_dir, drag_config, trajectory_path=trajectory_path)

    # 2) Reload trajectory and authoritative time axis for oscillatory cycle analysis.
    loaded: DragRunLoaded = load_drag_run(run_dir, trajectory_path=trajectory_path)
    assert loaded.paths.trajectory_path is not None  # enforced by load_drag_run

    axis = drag_result.axis
    um_per_px = drag_config.um_per_px

    traj_frames, traj_px, traj_um = _extract_axis_series(
        loaded.paths.trajectory_path, axis=axis, um_per_px=um_per_px
    )
    t_video = _interp_time_for_frames(loaded.frame_indices, loaded.frame_timestamps_s, traj_frames)

    y_um: np.ndarray
    if traj_um is not None:
        y_um = np.asarray(traj_um, dtype=np.float64)
    else:
        # If µm scaling isn't available, we can still extract phase/amplitude ratio
        # in px units; downstream viscoelastic backend can convert later.
        y_um = np.asarray(traj_px, dtype=np.float64)

    y_um = y_um[np.isfinite(y_um)]
    # Note: y_um must match t_video length; simplest is to avoid dropping samples.
    # For robustness with synthetic harness we keep all samples and only handle NaN by filtering later.
    # (Here we assume inputs are finite in typical offline tests.)
    if len(y_um) != len(t_video):
        # Re-derive y_um without dropping; keep NaN filtering consistent.
        mask = np.isfinite(np.asarray(traj_um if traj_um is not None else traj_px, dtype=np.float64))
        y_um = np.asarray(traj_um if traj_um is not None else traj_px, dtype=np.float64)[mask]
        t_video = np.asarray(t_video, dtype=np.float64)[mask]
    else:
        t_video = np.asarray(t_video, dtype=np.float64)

    # 3) Read protocol parameters (frequency and amplitude) from stage metadata (preferred).
    protocol_params = loaded.stage_meta.protocol_params or {}
    freq_hz: float | None = None
    if osc_config.frequency_hz is not None:
        freq_hz = float(osc_config.frequency_hz)
    else:
        if osc_config.frequency_key in protocol_params:
            freq_hz = float(protocol_params[osc_config.frequency_key])

    if freq_hz is None or not math.isfinite(freq_hz) or freq_hz <= 0:
        raise ValueError("oscillatory frequency_hz must be provided (or present in stage_meta.protocol_params)")

    T = 1.0 / freq_hz
    omega = 2.0 * math.pi * freq_hz

    stage_um_per_unit = drag_config.stage_um_per_unit or loaded.stage_meta.stage_um_per_unit
    drive_amp_um: float | None = None
    if osc_config.drive_amplitude_um is not None:
        drive_amp_um = float(osc_config.drive_amplitude_um)
    elif osc_config.drive_amplitude_um_key in protocol_params:
        drive_amp_um = float(protocol_params[osc_config.drive_amplitude_um_key])
    else:
        amp_user_key = osc_config.drive_amplitude_user_key
        if amp_user_key in protocol_params and stage_um_per_unit is not None:
            drive_amp_um = float(protocol_params[amp_user_key]) * float(stage_um_per_unit)

    # Apply stage sign convention to phase lag (drive reference assumes sin(...) with positive amplitude).
    sign_img = loaded.stage_meta.sign_stage_to_image_x if axis == "x" else loaded.stage_meta.sign_stage_to_image_y
    phase_sign_adjust = 0.0 if sign_img >= 0 else math.pi

    # 4) Choose time origin and perform per-cycle sine/cos fit.
    t0 = float(drag_result.motion_start_video_s_detected)
    t_end = float(max(t_video) if len(t_video) else t0)
    if t_end <= t0:
        return OscillatoryAnalysisResult(
            basename=drag_result.basename,
            axis=axis,
            frequency_hz=freq_hz,
            omega_rad_s=omega,
            drive_amplitude_um=drive_amp_um,
            response_amplitude_um=None,
            amplitude_ratio=None,
            phase_lag_rad=None,
            phase_lag_deg=None,
            n_cycles_total_available=0,
            n_cycles_used=0,
            motion_start_stage_s=drag_result.motion_start_stage_s,
            motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
            alignment_offset_s=drag_result.alignment_offset_s,
            rheology_target={},
            analysis_status="warning",
            warnings=["Not enough time span for oscillatory analysis."],
        )

    n_cycles_total = int(math.floor((t_end - t0) / T)) if T > 0 else 0
    steady_start_k = int(osc_config.steady_start_cycles)
    k_first = max(0, steady_start_k)
    k_last_exclusive = n_cycles_total
    if osc_config.max_cycles_to_use is not None:
        k_last_exclusive = min(k_last_exclusive, k_first + int(osc_config.max_cycles_to_use))

    baseline_sub = 0.0
    if osc_config.baseline_subtract == "baseline_median":
        baseline_sub = float(drag_result.baseline_position_um) if drag_result.baseline_position_um is not None else 0.0
    elif osc_config.baseline_subtract == "steady_median":
        baseline_sub = float(drag_result.steady_position_um) if drag_result.steady_position_um is not None else 0.0

    y = y_um - baseline_sub

    cycle_phases: list[float] = []
    cycle_amplitudes: list[float] = []

    used_warns: list[str] = []
    for k in range(k_first, k_last_exclusive):
        start = t0 + k * T
        end = start + T
        mask = (t_video >= start) & (t_video < end)
        if not np.any(mask):
            continue
        t_seg = t_video[mask]
        y_seg = y[mask]
        if t_seg.size < osc_config.min_samples_per_cycle:
            continue

        # Fit y(t) = b*sin(omega*(t-t0)) + c*cos(omega*(t-t0)) + d
        x_shift = t_seg - t0
        s = np.sin(omega * x_shift)
        c = np.cos(omega * x_shift)
        ones = np.ones_like(s)
        A = np.column_stack([s, c, ones])
        coeffs, *_ = np.linalg.lstsq(A, y_seg, rcond=None)
        b, ccoef, _d = coeffs

        amp = float(math.hypot(float(b), float(ccoef)))
        phi = float(math.atan2(float(ccoef), float(b)))  # phase in y = A*sin(omega*t + phi)

        cycle_amplitudes.append(amp)
        cycle_phases.append(phi)

    if not cycle_amplitudes or not cycle_phases:
        return OscillatoryAnalysisResult(
            basename=drag_result.basename,
            axis=axis,
            frequency_hz=freq_hz,
            omega_rad_s=omega,
            drive_amplitude_um=drive_amp_um,
            response_amplitude_um=None,
            amplitude_ratio=None,
            phase_lag_rad=None,
            phase_lag_deg=None,
            n_cycles_total_available=n_cycles_total,
            n_cycles_used=0,
            motion_start_stage_s=drag_result.motion_start_stage_s,
            motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
            alignment_offset_s=drag_result.alignment_offset_s,
            rheology_target={},
            analysis_status="warning",
            warnings=["No usable cycles for oscillatory fitting."],
        )

    n_used = len(cycle_amplitudes)
    if n_used < osc_config.require_min_cycles_used:
        used_warns.append(
            f"Only {n_used} cycles used; require_min_cycles_used={osc_config.require_min_cycles_used}."
        )

    resp_amp = float(np.mean(cycle_amplitudes))

    # Average phase via phasor mean to avoid wrapping artifacts.
    phasor_mean = np.mean(np.exp(1j * np.asarray(cycle_phases, dtype=np.float64)))
    phi_avg = float(np.angle(phasor_mean))

    # Convert fitted phase to phase lag relative to signed drive reference.
    phi_lag = _wrap_phase_to_pi(phi_avg - phase_sign_adjust)
    phi_lag_deg = float(phi_lag * 180.0 / math.pi)

    amp_ratio: float | None = None
    if drive_amp_um is not None and math.isfinite(drive_amp_um) and abs(drive_amp_um) > 0:
        amp_ratio = float(resp_amp / abs(drive_amp_um))

    rheology_target: dict[str, float] = {
        "omega_rad_s": float(omega),
    }
    if amp_ratio is not None and phi_lag is not None:
        # Complex response placeholder; future mapping can convert to compliance/modulus.
        complex_resp = amp_ratio * complex(math.cos(phi_lag), math.sin(phi_lag))
        rheology_target.update(
            {
                "complex_response_real": float(complex_resp.real),
                "complex_response_imag": float(complex_resp.imag),
                "amplitude_ratio": float(amp_ratio),
                "phase_lag_rad": float(phi_lag),
            }
        )

    status = "ok" if not used_warns else "warning"
    return OscillatoryAnalysisResult(
        basename=drag_result.basename,
        axis=axis,
        frequency_hz=float(freq_hz),
        omega_rad_s=float(omega),
        drive_amplitude_um=drive_amp_um,
        response_amplitude_um=resp_amp,
        amplitude_ratio=amp_ratio,
        phase_lag_rad=phi_lag,
        phase_lag_deg=phi_lag_deg,
        n_cycles_total_available=n_cycles_total,
        n_cycles_used=n_used,
        cycle_phases_rad=cycle_phases,
        cycle_amplitudes_um=cycle_amplitudes,
        motion_start_stage_s=drag_result.motion_start_stage_s,
        motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
        alignment_offset_s=drag_result.alignment_offset_s,
        rheology_target=rheology_target,
        analysis_status=status,
        warnings=used_warns,
    )

