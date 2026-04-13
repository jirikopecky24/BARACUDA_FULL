"""Stage scale audit helpers (acquisition).

BARAKUDA treats ``stage_um_per_unit`` as micrometers per XIMC position unit
(``get_position()`` float). Metric fields in ``*_stage.json`` are::

    actual_travel_um ≈ actual_travel_user * stage_um_per_unit
    actual_speed_um_s ≈ actual_speed_user_s * stage_um_per_unit

The codebase does not measure physical µm independently. To **validate** the
scale factor:

1. Run Record+Motion (or inspect ``*_stage.json`` after a run).
2. Read **raw** ``actual_travel_user`` (encoder-based user units).
3. Measure the **same** displacement in µm with an independent method
   (interferometer, micrometer head, calibrated reference object, etc.).
4. Compute ``inferred_um_per_unit = measured_um / actual_travel_user`` and
   compare to the configured ``stage_um_per_unit``.

If inferred and configured values disagree systematically, the configured
scale is wrong for this hardware; do not change it blindly to match a
viscosity target—use independent length metrology.
"""

from __future__ import annotations

from typing import Any

# Standa 8MT167-25LS-MEn1 documentation gives 1.25 µm per full motor step
# for a 0.25 mm lead screw with 200 full steps/rev.
STANDA_8MT167_FULL_STEP_UM = 1.25
# BARAKUDA acquisition chain consumes XIMC position units from the runtime path;
# physical validation with calibration grid indicates this path corresponds to
# 1/20 of the full-step value for the currently used hardware chain.
XIMC_POSITION_UNITS_PER_FULL_STEP = 20.0
ACQUISITION_DEFAULT_STAGE_UM_PER_UNIT = (
    STANDA_8MT167_FULL_STEP_UM / XIMC_POSITION_UNITS_PER_FULL_STEP
)


def build_stage_motion_audit_dict(stage_meta: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable audit blob from acquisition ``*_stage.json`` content.

    Pulls raw encoder-based motion fields next to commanded travel for sanity
    checks (e.g. measured/commanded ratio in user units). Does not interpret
    physics or modify analysis pipelines.
    """
    actual_tu = stage_meta.get("actual_travel_user")
    cmd_tu = stage_meta.get("travel_user_commanded_raw")
    if cmd_tu is None:
        cmd_tu = stage_meta.get("travel_user_commanded")

    actual_su = stage_meta.get("actual_speed_user_s")
    supu = stage_meta.get("stage_um_per_unit")

    ratio: float | None = None
    try:
        if actual_tu is not None and cmd_tu is not None:
            a = float(actual_tu)
            c = float(cmd_tu)
            if abs(c) > 1e-15:
                ratio = a / c
    except (TypeError, ValueError):
        ratio = None

    am = stage_meta.get("actual_metric")
    actual_metric = am if isinstance(am, dict) else {}

    return {
        "actual_travel_user": float(actual_tu) if actual_tu is not None else None,
        "travel_user_commanded": float(cmd_tu) if cmd_tu is not None else None,
        "actual_travel_user_over_commanded": ratio,
        "actual_speed_user_s": float(actual_su) if actual_su is not None else None,
        "stage_um_per_unit_configured": float(supu) if supu is not None else None,
        "actual_travel_um": (
            float(actual_metric["actual_travel_um"])
            if actual_metric.get("actual_travel_um") is not None
            else None
        ),
        "actual_speed_um_s": (
            float(actual_metric["actual_speed_um_s"])
            if actual_metric.get("actual_speed_um_s") is not None
            else None
        ),
        "validation_hint": (
            "Independent check: measured_um_physical / actual_travel_user "
            "should match stage_um_per_unit_configured."
        ),
    }


def inferred_um_per_unit(
    *,
    actual_travel_user: float,
    measured_travel_um: float,
) -> float:
    """Infer µm per user unit from an independent physical length measurement.

    Raises:
        ValueError: if ``actual_travel_user`` is zero or non-finite inputs.
    """
    if not float(actual_travel_user) or abs(float(actual_travel_user)) < 1e-15:
        raise ValueError("actual_travel_user must be non-zero")
    return float(measured_travel_um) / float(actual_travel_user)
