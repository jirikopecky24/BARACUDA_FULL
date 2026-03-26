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
class XimcMetricCalibration:
    """Validated mapping profile for metric->XIMC register conversion.

    The coefficients must come from explicit lab validation for the specific
    hardware configuration (controller/motor/microstep settings).
    """

    speed_reg_per_um_s: float
    accel_reg_per_um_s2: float
    decel_reg_per_um_s2: float
    validation_id: str


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

    conversion_mode: str = "legacy_raw_registers"
    mapping_validation_id: Optional[str] = None

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
    ximc_metric_calibration: Optional[XimcMetricCalibration] = None,
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

    speed_source = "legacy_speed_reg"
    accel_source = "legacy_accel_reg"
    decel_source = "legacy_decel_reg"
    conversion_mode = "legacy_raw_registers"
    mapping_validation_id: Optional[str] = None

    speed_reg = float(legacy_speed_reg)
    accel_reg = float(legacy_accel_reg)
    decel_reg = float(legacy_decel_reg)

    metric_speed_present = metric_command.speed_um_s is not None
    metric_accel_present = metric_command.accel_um_s2 is not None
    metric_decel_present = metric_command.decel_um_s2 is not None

    if metric_speed_present or metric_accel_present or metric_decel_present:
        # Fail loud on partial metric kinematics intent to avoid mixed semantics.
        if not (metric_speed_present and metric_accel_present and metric_decel_present):
            raise ValueError(
                "Metric kinematics intent is partial. "
                "speed_um_s, accel_um_s2, and decel_um_s2 must all be provided together."
            )
        if metric_command.speed_um_s is None or metric_command.accel_um_s2 is None or metric_command.decel_um_s2 is None:
            raise ValueError("Metric kinematics intent is missing required fields.")
        if metric_command.speed_um_s <= 0 or metric_command.accel_um_s2 <= 0 or metric_command.decel_um_s2 <= 0:
            raise ValueError("Metric kinematics values must be > 0.")
        if ximc_metric_calibration is None:
            raise ValueError(
                "Validated metric->XIMC mapping profile is required for speed/accel/decel conversion."
            )
        if (
            ximc_metric_calibration.speed_reg_per_um_s <= 0
            or ximc_metric_calibration.accel_reg_per_um_s2 <= 0
            or ximc_metric_calibration.decel_reg_per_um_s2 <= 0
        ):
            raise ValueError("Invalid metric mapping profile coefficients (must be > 0).")

        speed_reg = max(
            1.0,
            float(round(float(metric_command.speed_um_s) * float(ximc_metric_calibration.speed_reg_per_um_s))),
        )
        accel_reg = max(
            1.0,
            float(round(float(metric_command.accel_um_s2) * float(ximc_metric_calibration.accel_reg_per_um_s2))),
        )
        decel_reg = max(
            1.0,
            float(round(float(metric_command.decel_um_s2) * float(ximc_metric_calibration.decel_reg_per_um_s2))),
        )

        speed_source = "metric_speed_um_s_via_validated_profile"
        accel_source = "metric_accel_um_s2_via_validated_profile"
        decel_source = "metric_decel_um_s2_via_validated_profile"
        conversion_mode = "metric_validated_profile"
        mapping_validation_id = ximc_metric_calibration.validation_id

    return BackendMotionCommand(
        travel_user=travel_user,
        speed_reg=speed_reg,
        accel_reg=accel_reg,
        decel_reg=decel_reg,
        direction=direction,
        travel_source=travel_source,
        speed_source=speed_source,
        accel_source=accel_source,
        decel_source=decel_source,
        conversion_mode=conversion_mode,
        mapping_validation_id=mapping_validation_id,
        warnings=tuple(warnings),
    )

