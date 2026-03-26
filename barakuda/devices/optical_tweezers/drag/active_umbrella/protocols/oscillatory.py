from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path
import json
import csv

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

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
    number_of_cycles_detected: int
    number_of_cycles_used: int

    # Alignment context (from DRAG v1 foundation)
    motion_start_stage_s: float
    motion_start_video_s_detected: float
    alignment_offset_s: float

    # Provenance/auditability (copied from DRAG v1 foundation).
    stage_axis: Axis
    um_per_px_source: str | None
    stage_um_per_unit_source: str | None
    kappa_source: str | None
    selected_calibration_path: str | None
    selected_stage_meta_path: str | None
    selected_stage_trace_path: str | None
    selected_timestamps_path: str | None
    used_fallbacks: dict[str, str] = field(default_factory=dict)
    timing_source: str | None = None

    # Per-cycle results (kept with defaults for backward compatibility)
    cycle_phases_rad: list[float] = field(default_factory=list)
    cycle_amplitudes_um: list[float] = field(default_factory=list)
    cycle_start_times_s: list[float] = field(default_factory=list)
    cycle_end_times_s: list[float] = field(default_factory=list)

    # Rheology target placeholder (for future G' / G'')
    # Here we only package complex response from amplitude ratio and phase lag.
    rheology_target: dict[str, float] = field(default_factory=dict)

    analysis_status: str = "ok"
    physics_status: str = "response_only_not_full_rheology"
    averaging_summary: dict[str, float | int] = field(default_factory=dict)
    qc_flags: dict[str, bool] = field(default_factory=dict)
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
    provenance_warns = [w for w in drag_result.warnings if w.startswith("PROVENANCE_WARNING:")]

    # 2) Reload trajectory and authoritative time axis for oscillatory cycle analysis.
    loaded: DragRunLoaded = load_drag_run(run_dir, trajectory_path=trajectory_path)
    assert loaded.paths.trajectory_path is not None  # enforced by load_drag_run

    axis = drag_result.axis
    um_per_px = drag_config.um_per_px

    # Provenance copied from DRAG v1 foundation.
    stage_axis = drag_result.stage_axis
    um_per_px_source = drag_result.um_per_px_source
    stage_um_per_unit_source = drag_result.stage_um_per_unit_source
    kappa_source = drag_result.kappa_source
    selected_calibration_path = drag_result.selected_calibration_path
    selected_stage_meta_path = drag_result.selected_stage_meta_path
    selected_stage_trace_path = drag_result.selected_stage_trace_path
    selected_timestamps_path = drag_result.selected_timestamps_path
    used_fallbacks = dict(drag_result.used_fallbacks)
    timing_source = drag_result.timing_source

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
            number_of_cycles_detected=0,
            number_of_cycles_used=0,
            motion_start_stage_s=drag_result.motion_start_stage_s,
            motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
            alignment_offset_s=drag_result.alignment_offset_s,
            stage_axis=stage_axis,
            um_per_px_source=um_per_px_source,
            stage_um_per_unit_source=stage_um_per_unit_source,
            kappa_source=kappa_source,
            selected_calibration_path=selected_calibration_path,
            selected_stage_meta_path=selected_stage_meta_path,
            selected_stage_trace_path=selected_stage_trace_path,
            selected_timestamps_path=selected_timestamps_path,
            used_fallbacks=used_fallbacks,
            timing_source=timing_source,
            rheology_target={},
            analysis_status="warning",
            averaging_summary={},
            qc_flags={"cycle_detection_ok": False, "phase_estimation_stable": False},
            warnings=provenance_warns + ["Not enough time span for oscillatory analysis."],
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
    cycle_start_times: list[float] = []
    cycle_end_times: list[float] = []

    used_warns: list[str] = []
    used_warns.extend(provenance_warns)
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
        cycle_start_times.append(float(start))
        cycle_end_times.append(float(end))

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
            number_of_cycles_detected=n_cycles_total,
            number_of_cycles_used=0,
            motion_start_stage_s=drag_result.motion_start_stage_s,
            motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
            alignment_offset_s=drag_result.alignment_offset_s,
            stage_axis=stage_axis,
            um_per_px_source=um_per_px_source,
            stage_um_per_unit_source=stage_um_per_unit_source,
            kappa_source=kappa_source,
            selected_calibration_path=selected_calibration_path,
            selected_stage_meta_path=selected_stage_meta_path,
            selected_stage_trace_path=selected_stage_trace_path,
            selected_timestamps_path=selected_timestamps_path,
            used_fallbacks=used_fallbacks,
            timing_source=timing_source,
            rheology_target={},
            analysis_status="warning",
            averaging_summary={},
            qc_flags={"cycle_detection_ok": False, "phase_estimation_stable": False},
            warnings=provenance_warns + ["No usable cycles for oscillatory fitting."],
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
    phase_stable = abs(float(np.angle(phasor_mean))) <= math.pi and abs(complex(phasor_mean).real) + abs(complex(phasor_mean).imag) > 0

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
    avg_summary = {
        "mean_response_amplitude_um": float(resp_amp),
        "std_response_amplitude_um": float(np.std(np.asarray(cycle_amplitudes, dtype=np.float64))),
        "phase_lag_rad": float(phi_lag),
        "phase_lag_deg": float(phi_lag_deg),
        "n_cycles_used": int(n_used),
    }
    qc_flags = {
        "cycle_detection_ok": n_used >= int(osc_config.require_min_cycles_used),
        "phase_estimation_stable": bool(phase_stable),
        "drive_amplitude_available": drive_amp_um is not None,
    }
    notes = [
        "Response-level oscillatory metrics only; full rheology inversion is not yet validated."
    ]
    used_warns.extend(notes)
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
        number_of_cycles_detected=n_cycles_total,
        number_of_cycles_used=n_used,
        cycle_phases_rad=cycle_phases,
        cycle_amplitudes_um=cycle_amplitudes,
        cycle_start_times_s=cycle_start_times,
        cycle_end_times_s=cycle_end_times,
        motion_start_stage_s=drag_result.motion_start_stage_s,
        motion_start_video_s_detected=drag_result.motion_start_video_s_detected,
        alignment_offset_s=drag_result.alignment_offset_s,
        stage_axis=stage_axis,
        um_per_px_source=um_per_px_source,
        stage_um_per_unit_source=stage_um_per_unit_source,
        kappa_source=kappa_source,
        selected_calibration_path=selected_calibration_path,
        selected_stage_meta_path=selected_stage_meta_path,
        selected_stage_trace_path=selected_stage_trace_path,
        selected_timestamps_path=selected_timestamps_path,
        used_fallbacks=used_fallbacks,
        timing_source=timing_source,
        rheology_target=rheology_target,
        analysis_status=status,
        averaging_summary=avg_summary,
        qc_flags=qc_flags,
        warnings=used_warns,
    )


def oscillatory_result_to_dict(result: OscillatoryAnalysisResult) -> dict:
    return {
        "basename": result.basename,
        "protocol_type": "oscillatory",
        "analysis_axis": result.axis,
        "stage_axis": result.stage_axis,
        "frequency_hz": result.frequency_hz,
        "omega_rad_s": result.omega_rad_s,
        "motion_start_stage_s": result.motion_start_stage_s,
        "motion_start_video_s_detected": result.motion_start_video_s_detected,
        "alignment_offset_s": result.alignment_offset_s,
        "drive_amplitude_um": result.drive_amplitude_um,
        "response_amplitude_um": result.response_amplitude_um,
        "amplitude_ratio": result.amplitude_ratio,
        "phase_lag_rad": result.phase_lag_rad,
        "phase_lag_deg": result.phase_lag_deg,
        "number_of_cycles_detected": result.number_of_cycles_detected,
        "number_of_cycles_used": result.number_of_cycles_used,
        # Provenance / auditability
        "um_per_px_source": result.um_per_px_source,
        "stage_um_per_unit_source": result.stage_um_per_unit_source,
        "kappa_source": result.kappa_source,
        "selected_calibration_path": result.selected_calibration_path,
        "selected_stage_meta_path": result.selected_stage_meta_path,
        "selected_stage_trace_path": result.selected_stage_trace_path,
        "selected_timestamps_path": result.selected_timestamps_path,
        "used_fallbacks": result.used_fallbacks,
        "timing_source": result.timing_source,
        "analysis_status": result.analysis_status,
        "physics_status": result.physics_status,
        "averaging_summary": result.averaging_summary,
        "qc_flags": result.qc_flags,
        "warnings": list(result.warnings),
    }


def export_oscillatory_summary_json(
    result: OscillatoryAnalysisResult,
    output_dir: Path,
    *,
    protocol_path: str | None = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.basename}_oscillatory_summary.json"
    payload = oscillatory_result_to_dict(result)
    payload["protocol_present"] = bool(protocol_path)
    payload["protocol_path"] = protocol_path
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def export_oscillatory_summary_csv(
    result: OscillatoryAnalysisResult,
    output_dir: Path,
    *,
    protocol_path: str | None = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.basename}_oscillatory_summary.csv"
    payload = oscillatory_result_to_dict(result)
    payload["protocol_present"] = bool(protocol_path)
    payload["protocol_path"] = protocol_path
    flat = {
        k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
        for k, v in payload.items()
    }
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(flat.keys()))
        w.writeheader()
        w.writerow(flat)
    return path


def plot_oscillatory_diagnostic(
    *,
    t_video_s: np.ndarray,
    response_um: np.ndarray,
    result: OscillatoryAnalysisResult,
    output_dir: Path,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{result.basename}_oscillatory_diagnostic.png"
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(t_video_s, response_um, color="#1F6AA5", alpha=0.8, label="response")
    for i, (t0, t1) in enumerate(zip(result.cycle_start_times_s, result.cycle_end_times_s)):
        ax.axvspan(t0, t1, color="#A5D6A7", alpha=0.15, label="used cycles" if i == 0 else None)
    ax.axvline(result.motion_start_video_s_detected, color="#000", linestyle="--", label="motion start")
    ax.set_title("Oscillatory active drag diagnostic")
    ax.set_xlabel("time [s]")
    ax.set_ylabel("response [um or px-equivalent]")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path

