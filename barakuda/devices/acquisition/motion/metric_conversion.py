from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MetricMotionCommand:
    """Metric-oriented motion intent (user-facing schema).

    Phase2 scope: backend-side conversion only for fields we can map safely
    and audibly without faking unsupported mappings.
    """

    # axis is currently informational for the acquisition layer; backend move is direction/travel based.
    axis: str  # "x" | "y"
    direction: int  # +1 | -1

    # Travel intent (µm) - can be mapped if stage_um_per_unit is known.
    travel_um: Optional[float] = None

    # Speed/accel/decel intent (µm/s, µm/s^2) - mapping to XIMC registers is not reliable yet.
    speed_um_s: Optional[float] = None
    accel_um_s2: Optional[float] = None
    decel_um_s2: Optional[float] = None

    pre_delay_s: float = 0.0
    post_delay_s: float = 0.0

    # Oscillatory extensions: kept optional for future phases.
    frequency_hz: Optional[float] = None


@dataclass(frozen=True)
class BackendMotionCommand:
    """Backend-specific motion command (what stage.move_constant_velocity consumes)."""

    # Travel is in stage user units (controller counts / user units).
    travel_user: float

    # XIMC register values (firmware values), currently taken from legacy recipe.
    speed_reg: float
    accel_reg: float
    decel_reg: float

    direction: int

    # Audit: where each field came from.
    travel_source: str
    speed_source: str
    accel_source: str
    decel_source: str

    # Any unsupported metric fields were ignored explicitly.
    warnings: tuple[str, ...] = ()


def convert_metric_intent_to_backend_command(
    *,
    legacy_travel_user: float,
    legacy_direction: int,
    legacy_speed_reg: float,
    legacy_accel_reg: float,
    legacy_decel_reg: float,
    metric_command: MetricMotionCommand,
    stage_um_per_unit: Optional[float],
) -> BackendMotionCommand:
    """Convert metric intent to backend command with explicit provenance.

    Safety rule:
    - Only map metric fields we can convert robustly (Phase2: travel_um only).
    - If metric_command specifies speed/accel/decel but mapping to registers is not implemented,
      do not use them; keep legacy register values.
    """

    warnings: list[str] = []

    direction = int(legacy_direction)
    if int(metric_command.direction) != int(legacy_direction):
        warnings.append(
            "metric_direction provided but backend direction kept as legacy_direction to preserve compatibility."
        )

    travel_user: float
    travel_source: str

    if metric_command.travel_um is not None and stage_um_per_unit is not None and stage_um_per_unit > 0:
        travel_user = float(metric_command.travel_um) / float(stage_um_per_unit)
        travel_source = "metric_travel_um_via_stage_um_per_unit"
    else:
        travel_user = float(legacy_travel_user)
        if metric_command.travel_um is not None and stage_um_per_unit is None:
            warnings.append("metric travel_um present but stage_um_per_unit unknown; using legacy travel.")
        else:
            warnings.append("metric travel_um not provided; using legacy travel.")
        travel_source = "legacy_travel_user"

    # Speed/accel/decel mapping to XIMC registers is intentionally not implemented in Phase2.
    # Keep legacy register values and record that metric speed intent is ignored.
    speed_source = "legacy_speed_reg"
    accel_source = "legacy_accel_reg"
    decel_source = "legacy_decel_reg"

    if metric_command.speed_um_s is not None or metric_command.accel_um_s2 is not None or metric_command.decel_um_s2 is not None:
        warnings.append(
            "metric speed/accel/decel intent provided, but mapping to XIMC registers is not reliable yet; "
            "keeping legacy register values."
        )

    return BackendMotionCommand(
        travel_user=travel_user,
        speed_reg=float(legacy_speed_reg),
        accel_reg=float(legacy_accel_reg),
        decel_reg=float(legacy_decel_reg),
        direction=direction,
        travel_source=travel_source,
        speed_source=speed_source,
        accel_source=accel_source,
        decel_source=decel_source,
        warnings=tuple(warnings),
    )

