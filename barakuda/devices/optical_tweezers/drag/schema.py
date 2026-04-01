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
    # Provenance hint for later export: which sidecars were resolved via a fallback
    # instead of the preferred canonical filename.
    # Keys: meta_path, timestamps_path, stage_meta_path, stage_trace_path, trajectory_path
    used_fallbacks: dict[str, str] = field(default_factory=dict)
    # Per-artifact selection provenance.
    # Shape:
    # {
    #   "<artifact_key>": {
    #       "selected_artifact_path": "...",
    #       "artifact_selection_mode": "...",
    #       "artifact_selection_warning": "...|None",
    #       "candidate_files": [...],
    #       "searched_directories": [...],
    #   }
    # }
    artifact_selection: dict[str, dict[str, Any]] = field(default_factory=dict)


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
    # Optional metric kinematics (preferred when present and valid).
    actual_travel_um: float | None = None
    actual_speed_um_s: float | None = None
    kinematics_source: str | None = None
    # Protocol-specific parameters (future step/oscillatory/active rheology).
    # Kept generic so stage JSON can evolve without breaking the loader.
    protocol_params: dict[str, Any] = field(default_factory=dict)


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
    motion_command_issued_s: float | None = None
    motion_running_confirmed_s: float | None = None
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
    timestamp_validation_pass: bool = True
    timestamp_validation_message: str = "timestamps validated"


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
    onset_relaxed_used: bool = False
    onset_competing_durable_candidates: int = 0
    onset_ambiguity_score: float = 0.0
    onset_confidence_class: str = "robust"


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
    # Debug/export knobs. Keep plots opt-in to avoid overhead.
    export_alignment_diagnostics_json: bool = True
    export_alignment_debug_plot: bool = False
    # Provenance/auditability (filled by pipeline; do not affect calculations).
    um_per_px_source: str | None = None
    stage_um_per_unit_source: str | None = None
    kappa_source: str | None = None
    selected_calibration_path: str | None = None
    current_drag_input_path: str | None = None
    current_drag_item_root: str | None = None
    brownian_baseline_folder: str | None = None
    baseline_selection_mode: str | None = None
    drag_preflight_status: str | None = None
    drag_preflight_message: str | None = None
    current_drag_output_root: str | None = None


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
    alignment_diagnostics: AlignmentDiagnostics | None = None

    # Provenance/auditability fields for exported summaries.
    protocol_type: str = "constant_velocity"
    analysis_axis: Axis = "x"
    stage_axis: Axis = "x"
    um_per_px_source: str | None = None
    stage_um_per_unit_source: str | None = None
    kappa_source: str | None = None
    selected_calibration_path: str | None = None
    selected_stage_meta_path: str | None = None
    selected_stage_trace_path: str | None = None
    selected_timestamps_path: str | None = None
    selected_trajectory_path: str | None = None
    current_drag_input_path: str | None = None
    current_drag_item_root: str | None = None
    brownian_baseline_folder: str | None = None
    baseline_selection_mode: str | None = None
    drag_preflight_status: str | None = None
    drag_preflight_message: str | None = None
    current_drag_output_root: str | None = None
    current_drag_report_path: str | None = None
    current_drag_summary_json_path: str | None = None
    current_drag_summary_csv_path: str | None = None
    current_drag_diagnostic_png_path: str | None = None
    current_drag_alignment_json_path: str | None = None
    used_fallbacks: dict[str, str] = field(default_factory=dict)
    artifact_selection: dict[str, dict[str, Any]] = field(default_factory=dict)
    timing_source: str | None = None
    motion_kinematics_source: str | None = None
    timestamp_validation_pass: bool = True
    timestamp_validation_message: str = "timestamps validated"
    report_source_kind: str | None = None
    report_source_path: str | None = None
    alignment_message: str | None = None
    commanded_travel_user_ref: float | None = None
    commanded_speed_user_s_ref: float | None = None
    # Physics hardening audit layer
    offset_current_windows_um: float | None = None
    offset_alt_baseline_um: float | None = None
    eta_current_windows: float | None = None
    eta_alt_baseline: float | None = None
    baseline_reference_median_px: float | None = None
    baseline_reference_window_start_s: float | None = None
    baseline_reference_window_end_s: float | None = None
    baseline_median_delta_px: float | None = None
    baseline_median_delta_um: float | None = None
    stage_speed_from_trace_um_s: float | None = None
    stage_speed_relative_diff: float | None = None
    stage_speed_consistent: bool | None = None
    drag_physics_confidence: str | None = None
    drag_physics_warning: str | None = None
    baseline_robustness_flag: str | None = None
    onset_robustness_flag: str | None = None
    kinematics_robustness_flag: str | None = None


def iter_qc_flags(flags: DragQCFlags) -> Iterable[tuple[str, bool]]:
    """Utility to iterate QC flags as (name, value) pairs."""
    return (
        (field_name, getattr(flags, field_name))
        for field_name in vars(flags).keys()
    )

