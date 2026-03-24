from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from ..analysis import analyze_drag_run
from ..schema import Axis, DragAnalysisConfig, DragWindowParams
from ..active_umbrella.runner import ActiveUmbrellaConfig, ActiveUmbrellaProtocolType, analyze_active_umbrella_run
from ..active_umbrella.protocols.oscillatory import OscillatoryProtocolConfig


@dataclass(frozen=True)
class SyntheticTiming:
    fps: float = 50.0
    t_start_s: float = 0.0
    baseline_end_s: float = 2.0
    motion_start_s: float = 2.5
    motion_duration_s: float = 10.0


def _write_dummy_raw(run_dir: Path, basename: str) -> None:
    path = run_dir / f"{basename}.raw"
    path.write_bytes(b"")


def _write_video_meta(run_dir: Path, basename: str, fps: float, frame_count: int) -> None:
    meta_path = run_dir / f"{basename}_meta.json"
    payload = {
        "fps": float(fps),
        "frame_count": int(frame_count),
        "width": 640,
        "height": 480,
    }
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_timestamps_csv(run_dir: Path, basename: str, frames: np.ndarray, t_s: np.ndarray) -> None:
    path = run_dir / f"{basename}_timestamps.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "timestamp_s"])
        for fr, ts in zip(frames, t_s):
            w.writerow([int(fr), f"{float(ts):.9f}"])


def _write_stage_trace_csv(
    run_dir: Path,
    basename: str,
    motion_start_stage_s: float,
    motion_stop_stage_s: float,
) -> None:
    path = run_dir / f"{basename}_stage_trace.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "event"])
        w.writerow([0.0, "script_start"])
        w.writerow([motion_start_stage_s, "motion_start"])
        w.writerow([motion_stop_stage_s, "motion_stop"])
        w.writerow([motion_stop_stage_s, "script_end"])


def _write_stage_meta_json(
    run_dir: Path,
    basename: str,
    axis: Axis,
    direction: str,
    actual_travel_user: float,
    actual_motion_duration_s: float,
    actual_speed_user_s: float,
    sign_stage_to_image_x: int,
    sign_stage_to_image_y: int,
    pre_delay_s: float,
    post_delay_s: float,
    stage_um_per_unit: float | None,
    protocol_params: dict[str, object] | None = None,
) -> None:
    path = run_dir / f"{basename}_stage.json"
    payload = {
        "axis": axis,
        "direction": direction,
        "actual_travel_user": float(actual_travel_user),
        "actual_motion_duration_s": float(actual_motion_duration_s),
        "actual_speed_user_s": float(actual_speed_user_s),
        "sign_stage_to_image_x": int(sign_stage_to_image_x),
        "sign_stage_to_image_y": int(sign_stage_to_image_y),
        "pre_delay_s": float(pre_delay_s),
        "post_delay_s": float(post_delay_s),
    }
    if stage_um_per_unit is not None:
        payload["stage_um_per_unit"] = float(stage_um_per_unit)
    if protocol_params:
        payload.update(protocol_params)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_trajectory_csv(
    run_dir: Path,
    basename: str,
    axis: Axis,
    frames: np.ndarray,
    signal_px: np.ndarray,
) -> None:
    path = run_dir / f"{basename}_trajectory.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        # analysis only requires: 'frame' + '<axis>_px'. We also include both x_px/y_px
        # so shared code paths remain robust.
        w.writerow(["frame", "t_s", "x_px", "y_px", "quality"])
        for fr, x_px in zip(frames, signal_px):
            # Keep columns simple: we duplicate x_px/y_px in case other code expects them.
            t_s = 0.0  # unused by analysis; time comes from *_timestamps.csv
            x_px_val = float(x_px) if axis == "x" else 0.0
            y_px_val = float(x_px) if axis == "y" else 0.0
            w.writerow([int(fr), f"{t_s:.9f}", f"{x_px_val:.9f}", f"{y_px_val:.9f}", f"{1.0:.9f}"])


def create_synthetic_constant_velocity_run(
    run_dir: Path,
    basename: str = "synthetic_cv_drag",
    axis: Axis = "x",
    timing: SyntheticTiming = SyntheticTiming(),
    offset_um: float = 2.0,
    noise_px: float = 0.05,
    drift_px_per_s: float = 0.0,
    timing_offset_s: float = 0.0,
    stage_um_per_unit: float = 1.0,
    stage_speed_user_s: float = 1.0,
    actual_travel_user: float | None = None,
    sign: int = 1,
) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    duration_total = timing.baseline_end_s + timing.motion_duration_s + 1.0
    n_frames = int(math.ceil(duration_total * timing.fps))
    t_s = np.linspace(timing.t_start_s, timing.t_start_s + duration_total, n_frames, dtype=np.float64)
    frames = np.arange(n_frames, dtype=np.int64)

    motion_start_stage_s = timing.motion_start_s
    motion_start_video_s = motion_start_stage_s + timing_offset_s
    motion_stop_stage_s = motion_start_stage_s + timing.motion_duration_s

    # Response: baseline ~0 then a step to offset.
    offset_px = float(offset_um) / float(stage_um_per_unit)  # um_per_px==stage_um_per_unit in this synthetic
    y = np.zeros_like(t_s, dtype=np.float64)
    step_mask = t_s >= motion_start_video_s
    y[step_mask] = offset_px

    drift = float(drift_px_per_s) * (t_s - timing.t_start_s)
    y = y + drift
    if noise_px > 0:
        y = y + np.random.normal(0.0, float(noise_px), size=y.shape)

    # Physics inputs bookkeeping
    actual_speed_user_s = float(stage_speed_user_s)
    if actual_travel_user is None:
        actual_travel_user = actual_speed_user_s * float(timing.motion_duration_s)

    _write_dummy_raw(run_dir, basename)
    _write_video_meta(run_dir, basename, fps=float(timing.fps), frame_count=int(n_frames))
    _write_timestamps_csv(run_dir, basename, frames, t_s)

    _write_stage_trace_csv(run_dir, basename, motion_start_stage_s=motion_start_stage_s, motion_stop_stage_s=motion_stop_stage_s)

    _write_stage_meta_json(
        run_dir,
        basename,
        axis=axis,
        direction="positive",
        actual_travel_user=float(actual_travel_user),
        actual_motion_duration_s=float(timing.motion_duration_s),
        actual_speed_user_s=actual_speed_user_s,
        sign_stage_to_image_x=int(sign) if axis == "x" else 1,
        sign_stage_to_image_y=int(sign) if axis == "y" else 1,
        pre_delay_s=float(timing.baseline_end_s),
        post_delay_s=0.0,
        stage_um_per_unit=float(stage_um_per_unit),
        protocol_params=None,
    )

    # um_per_px in this synthetic is stage_um_per_unit by convention.
    # trajectory stores px domain; analysis config provides um_per_px.
    _write_trajectory_csv(run_dir, basename, axis=axis, frames=frames, signal_px=y)
    return run_dir


def create_synthetic_step_response_run(
    run_dir: Path,
    basename: str = "synthetic_step_drag",
    axis: Axis = "x",
    timing: SyntheticTiming = SyntheticTiming(motion_duration_s=8.0),
    step_amplitude_um: float = 2.0,
    tau_s: float = 0.7,
    noise_px: float = 0.03,
    drift_px_per_s: float = 0.0,
    timing_offset_s: float = 0.0,
    stage_um_per_unit: float = 1.0,
    stage_speed_user_s: float = 1.0,
    sign: int = 1,
) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    duration_total = timing.baseline_end_s + timing.motion_duration_s + 1.0
    n_frames = int(math.ceil(duration_total * timing.fps))
    t_s = np.linspace(timing.t_start_s, timing.t_start_s + duration_total, n_frames, dtype=np.float64)
    frames = np.arange(n_frames, dtype=np.int64)

    motion_start_stage_s = timing.motion_start_s
    motion_start_video_s = motion_start_stage_s + timing_offset_s
    motion_stop_stage_s = motion_start_stage_s + timing.motion_duration_s

    amp_px = float(step_amplitude_um) / float(stage_um_per_unit)
    y = np.zeros_like(t_s, dtype=np.float64)
    after = t_s >= motion_start_video_s
    dt = t_s[after] - motion_start_video_s
    y[after] = amp_px * (1.0 - np.exp(-dt / float(tau_s)))

    y = y + float(drift_px_per_s) * (t_s - timing.t_start_s)
    if noise_px > 0:
        y = y + np.random.normal(0.0, float(noise_px), size=y.shape)

    actual_speed_user_s = float(stage_speed_user_s)
    actual_travel_user = actual_speed_user_s * float(timing.motion_duration_s)

    _write_dummy_raw(run_dir, basename)
    _write_video_meta(run_dir, basename, fps=float(timing.fps), frame_count=int(n_frames))
    _write_timestamps_csv(run_dir, basename, frames, t_s)
    _write_stage_trace_csv(run_dir, basename, motion_start_stage_s=motion_start_stage_s, motion_stop_stage_s=motion_stop_stage_s)
    _write_stage_meta_json(
        run_dir,
        basename,
        axis=axis,
        direction="positive",
        actual_travel_user=actual_travel_user,
        actual_motion_duration_s=float(timing.motion_duration_s),
        actual_speed_user_s=actual_speed_user_s,
        sign_stage_to_image_x=int(sign) if axis == "x" else 1,
        sign_stage_to_image_y=int(sign) if axis == "y" else 1,
        pre_delay_s=float(timing.baseline_end_s),
        post_delay_s=0.0,
        stage_um_per_unit=float(stage_um_per_unit),
    )

    _write_trajectory_csv(run_dir, basename, axis=axis, frames=frames, signal_px=y)
    return run_dir


def create_synthetic_oscillatory_run(
    run_dir: Path,
    basename: str = "synthetic_osc_drag",
    axis: Axis = "x",
    timing: SyntheticTiming = SyntheticTiming(motion_duration_s=12.0),
    frequency_hz: float = 0.8,
    drive_amplitude_user: float = 2.0,
    response_amplitude_ratio: float = 0.6,
    phase_lag_rad: float = 0.9,
    noise_px: float = 0.02,
    drift_px_per_s: float = 0.0,
    timing_offset_s: float = 0.0,
    stage_um_per_unit: float = 1.0,
    stage_speed_user_s: float = 1.0,
    sign: int = 1,
) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    duration_total = timing.baseline_end_s + timing.motion_duration_s + 1.0
    n_frames = int(math.ceil(duration_total * timing.fps))
    t_s = np.linspace(timing.t_start_s, timing.t_start_s + duration_total, n_frames, dtype=np.float64)
    frames = np.arange(n_frames, dtype=np.int64)

    motion_start_stage_s = timing.motion_start_s
    motion_start_video_s = motion_start_stage_s + timing_offset_s
    motion_stop_stage_s = motion_start_stage_s + timing.motion_duration_s

    omega = 2.0 * math.pi * float(frequency_hz)
    drive_amp_um = float(drive_amplitude_user) * float(stage_um_per_unit)
    resp_amp_um = drive_amp_um * float(response_amplitude_ratio)

    # bead response: baseline + A*sin(omega*(t-t0)+phase)
    after = t_s >= motion_start_video_s
    y = np.zeros_like(t_s, dtype=np.float64)
    x_shift = t_s[after] - motion_start_video_s
    y[after] = (resp_amp_um / float(stage_um_per_unit)) * np.sin(omega * x_shift + float(phase_lag_rad))

    y = y + float(drift_px_per_s) * (t_s - timing.t_start_s)
    if noise_px > 0:
        y = y + np.random.normal(0.0, float(noise_px), size=y.shape)

    actual_speed_user_s = float(stage_speed_user_s)
    actual_travel_user = actual_speed_user_s * float(timing.motion_duration_s)

    protocol_params = {
        "oscillation_frequency_hz": float(frequency_hz),
        "oscillation_amplitude_user": float(drive_amplitude_user),
    }

    _write_dummy_raw(run_dir, basename)
    _write_video_meta(run_dir, basename, fps=float(timing.fps), frame_count=int(n_frames))
    _write_timestamps_csv(run_dir, basename, frames, t_s)
    _write_stage_trace_csv(run_dir, basename, motion_start_stage_s=motion_start_stage_s, motion_stop_stage_s=motion_stop_stage_s)
    _write_stage_meta_json(
        run_dir,
        basename,
        axis=axis,
        direction="positive",
        actual_travel_user=actual_travel_user,
        actual_motion_duration_s=float(timing.motion_duration_s),
        actual_speed_user_s=actual_speed_user_s,
        sign_stage_to_image_x=int(sign) if axis == "x" else 1,
        sign_stage_to_image_y=int(sign) if axis == "y" else 1,
        pre_delay_s=float(timing.baseline_end_s),
        post_delay_s=0.0,
        stage_um_per_unit=float(stage_um_per_unit),
        protocol_params=protocol_params,
    )

    _write_trajectory_csv(run_dir, basename, axis=axis, frames=frames, signal_px=y)
    return run_dir


def run_offline_drag_self_tests(output_dir: Path | None = None) -> None:
    """Run quick offline tests (no lab data) for constant_velocity + oscillatory scaffolds."""
    if output_dir is None:
        output_dir = Path.cwd() / "offline_drag_self_tests"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(0)
    np.random.seed(0)

    # --- 1) constant_velocity stage-aware DRAG physics path ---
    const_dir = output_dir / "cv"
    const_dir.mkdir(parents=True, exist_ok=True)

    timing = SyntheticTiming(fps=40.0, baseline_end_s=1.0, motion_start_s=1.4, motion_duration_s=6.0)
    stage_um_per_unit = 1.0  # also used as um_per_px convention in synthetic trajectory writer
    offset_um = 1.5

    create_synthetic_constant_velocity_run(
        const_dir,
        basename="synthetic_cv_drag",
        axis="x",
        timing=timing,
        offset_um=offset_um,
        noise_px=0.02,
        drift_px_per_s=0.001,
        timing_offset_s=0.15,
        stage_um_per_unit=stage_um_per_unit,
        stage_speed_user_s=2.0,
        sign=1,
    )

    bead_radius_um = 0.75
    kappa_n_per_m = 0.08  # pick a value that yields reasonable eta
    cfg = DragAnalysisConfig(
        analysis_axis="x",
        um_per_px=stage_um_per_unit,
        bead_radius_um=bead_radius_um,
        kappa_n_per_m=kappa_n_per_m,
        stage_um_per_unit=stage_um_per_unit,
        onset_threshold_sigma=4.0,
        onset_min_hold_s=0.2,
        manual_offset_s=None,
        strict_steady=False,
        window_params=DragWindowParams(
            baseline_duration_s=0.8,
            baseline_guard_s=0.1,
            steady_start_delay_s=0.4,
            steady_end_guard_s=0.2,
            min_steady_duration_s=1.5,
        ),
        export_alignment_debug_plot=False,
        export_alignment_diagnostics_json=True,
    )

    const_result = analyze_drag_run(const_dir, cfg)
    expected_eta = None
    # Expected eta from formula eta = kappa*offset/(6*pi*R*v)
    # actual speed in analysis is actual_speed_user_s * stage_um_per_unit
    v_um_s = 2.0 * stage_um_per_unit
    R_m = bead_radius_um * 1e-6
    off_m = offset_um * 1e-6
    expected_eta = (kappa_n_per_m * off_m) / (6.0 * math.pi * R_m * (v_um_s * 1e-6))

    assert const_result.physics_status == "ready", f"Expected physics ready, got {const_result.physics_status}"
    assert const_result.eta_pa_s is not None
    assert abs(const_result.eta_pa_s - expected_eta) / abs(expected_eta) < 0.15, "eta mismatch too large"

    # --- 2) oscillatory scaffolding ---
    osc_dir = output_dir / "osc"
    osc_dir.mkdir(parents=True, exist_ok=True)

    freq_hz = 0.9
    drive_amp_user = 2.5
    resp_amp_ratio = 0.55
    phi_lag = 0.8

    create_synthetic_oscillatory_run(
        osc_dir,
        basename="synthetic_osc_drag",
        axis="x",
        timing=SyntheticTiming(fps=60.0, baseline_end_s=1.0, motion_start_s=1.4, motion_duration_s=10.0),
        frequency_hz=freq_hz,
        drive_amplitude_user=drive_amp_user,
        response_amplitude_ratio=resp_amp_ratio,
        phase_lag_rad=phi_lag,
        noise_px=0.01,
        drift_px_per_s=0.0,
        timing_offset_s=0.0,
        stage_um_per_unit=stage_um_per_unit,
        sign=1,
    )

    drag_cfg_osc = DragAnalysisConfig(
        analysis_axis="x",
        um_per_px=stage_um_per_unit,
        bead_radius_um=None,
        kappa_n_per_m=None,
        eta_pa_s=None,
        stage_um_per_unit=stage_um_per_unit,
        onset_threshold_sigma=3.5,
        onset_min_hold_s=0.15,
        window_params=DragWindowParams(
            baseline_duration_s=0.8,
            baseline_guard_s=0.1,
            steady_start_delay_s=0.3,
            steady_end_guard_s=0.2,
            min_steady_duration_s=1.0,
        ),
        export_alignment_diagnostics_json=False,
    )

    umbrella_cfg = ActiveUmbrellaConfig(
        protocol_type="oscillatory",
        drag_config=drag_cfg_osc,
        oscillatory=OscillatoryProtocolConfig(
            frequency_hz=freq_hz,
            drive_amplitude_um=drive_amp_user * stage_um_per_unit,
            steady_start_cycles=5,
            max_cycles_to_use=6,
            baseline_subtract="baseline_median",
            require_min_cycles_used=3,
        ),
    )

    osc_result = analyze_active_umbrella_run(osc_dir, umbrella_cfg)
    assert isinstance(osc_result, object)
    assert osc_result.phase_lag_rad is not None
    assert osc_result.amplitude_ratio is not None

    # Allow some tolerance due to onset timing thresholding.
    assert abs(osc_result.phase_lag_rad - phi_lag) < 0.35, f"phase mismatch: got {osc_result.phase_lag_rad}, expected {phi_lag}"
    assert abs(osc_result.amplitude_ratio - resp_amp_ratio) < 0.12, f"amplitude_ratio mismatch: got {osc_result.amplitude_ratio}, expected {resp_amp_ratio}"


if __name__ == "__main__":  # pragma: no cover
    run_offline_drag_self_tests()

