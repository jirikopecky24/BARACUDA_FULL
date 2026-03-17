from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal


Axis = Literal["x", "y"]


@dataclass(frozen=True)
class DragRunPaths:
    """Resolved file paths for a single DRAG run folder.

    Expected layout (all in the same directory):
      <basename>.raw
      <basename>_meta.json
      <basename>_timestamps.csv
      <basename>_stage.json
      <basename>_stage_trace.csv
    """

    run_dir: Path
    basename: str
    raw_path: Path
    meta_path: Path
    timestamps_path: Path
    stage_meta_path: Path
    stage_trace_path: Path
    trajectory_path: Path | None = None


@dataclass(frozen=True)
class DragStageMeta:
    """Minimal stage metadata required for DRAG analysis."""

    axis: Axis
    direction: str
    actual_travel_user: float
    actual_motion_duration_s: float
    actual_speed_user_s: float
    sign_stage_to_image_x: int
    sign_stage_to_image_y: int
    pre_delay_s: float
    post_delay_s: float
    # Optional conversion from stage user units to micrometers.
    stage_um_per_unit: float | None = None


@dataclass(frozen=True)
class DragStageTraceEvent:
    """Single event entry from the stage trace."""

    t_s: float
    event: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DragStageTiming:
    """Key timing markers extracted from the stage trace."""

    script_start_s: float | None = None
    pre_hold_start_s: float | None = None
    pre_hold_end_s: float | None = None
    motion_start_stage_s: float | None = None
    motion_stop_stage_s: float | None = None
    post_hold_start_s: float | None = None
    post_hold_end_s: float | None = None
    script_end_s: float | None = None


@dataclass(frozen=True)
class DragWindowParams:
    """Configuration of baseline / steady-state windows."""

    baseline_duration_s: float = 3.0
    baseline_guard_s: float = 0.5
    steady_start_delay_s: float = 2.0
    steady_end_guard_s: float = 1.0
    min_steady_duration_s: float = 5.0


@dataclass(frozen=True)
class DragWindows:
    """Resolved time windows on the video time axis."""

    baseline_start_s: float
    baseline_end_s: float
    steady_start_s: float
    steady_end_s: float


@dataclass(frozen=True)
class DragRunLoaded:
    """All inputs loaded from a DRAG run folder."""

    paths: DragRunPaths
    stage_meta: DragStageMeta
    stage_events: list[DragStageTraceEvent]
    stage_timing: DragStageTiming
    # Authoritative video time axis (frame index -> timestamp_s)
    frame_indices: list[int]
    frame_timestamps_s: list[float]


@dataclass(frozen=True)
class DragAlignmentResult:
    """Alignment between stage time and video time."""

    alignment_offset_s: float
    motion_start_stage_s: float
    motion_stop_stage_s: float | None
    motion_start_video_s_detected: float
    motion_stop_video_s_stage_aligned: float | None
    method: Literal["detected", "manual_offset"]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AlignmentDiagnostics:
    """Diagnostics from motion onset detection (for debugging alignment failures)."""

    baseline_end_s: float
    baseline_median: float
    baseline_mad: float
    baseline_sigma: float
    onset_threshold_sigma: float
    onset_threshold_abs: float
    onset_min_hold_s: float
    n_baseline_samples: int
    n_total_samples: int
    n_frames_outside_baseline: int
    candidate_onset_times_s: tuple[float, ...]
    candidate_durations_s: tuple[float, ...]
    failure_reason: str
    message: str


@dataclass(frozen=True)
class DragAnalysisConfig:
    """User/configurable parameters for DRAG analysis."""

    analysis_axis: Axis
    um_per_px: float | None = None
    bead_radius_um: float | None = None
    bead_diameter_um: float | None = None
    eta_pa_s: float | None = None
    kappa_n_per_m: float | None = None
    onset_threshold_sigma: float = 5.0
    onset_min_hold_s: float = 0.3
    window_params: DragWindowParams = field(default_factory=DragWindowParams)
    manual_offset_s: float | None = None
    stage_um_per_unit: float | None = None
    strict_steady: bool = False


@dataclass
class DragQCFlags:
    """Basic quality-control flags for DRAG analysis."""

    baseline_window_ok: bool = True
    steady_window_ok: bool = True
    sufficient_steady_duration: bool = True
    alignment_confident: bool = True
    stage_speed_available: bool = True
    physics_ready: bool = False
    offset_detected: bool = True


@dataclass(frozen=True)
class DragAnalysisResult:
    """Final structured result of DRAG analysis for a single run."""

    basename: str
    axis: Axis

    # Alignment and timing
    alignment_offset_s: float
    motion_start_stage_s: float
    motion_stop_stage_s: float | None
    motion_start_video_s_detected: float
    motion_stop_video_s_stage_aligned: float | None

    # Windows
    windows: DragWindows

    # Baseline / steady statistics (image coordinates)
    baseline_position_px: float
    steady_position_px: float

    # Same in micrometers, if scale known
    baseline_position_um: float | None
    steady_position_um: float | None

    # Offsets
    offset_px_raw: float
    offset_um_raw: float | None
    offset_px_stage_signed: float
    offset_um_stage_signed: float | None
    abs_offset_um: float | None

    # Stage kinematics (user units and µm if available)
    actual_travel_user: float
    actual_motion_duration_s: float
    actual_speed_user_s: float
    actual_travel_um: float | None
    actual_speed_um_s: float | None

    # Physics-level metrics (optional)
    drag_force_n: float | None = None
    kappa_n_per_m: float | None = None
    kappa_pn_per_um: float | None = None
    eta_pa_s: float | None = None

    # Status and QC
    analysis_status: str = "ok"
    alignment_status: str = "detected"
    physics_status: str = "incomplete_inputs"
    qc_flags: DragQCFlags = field(default_factory=DragQCFlags)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def iter_qc_flags(flags: DragQCFlags) -> Iterable[tuple[str, bool]]:
    """Utility to iterate QC flags as (name, value) pairs."""
    return (
        (field_name, getattr(flags, field_name))
        for field_name in vars(flags).keys()
    )

