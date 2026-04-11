from barakuda.devices.acquisition.motion.stage_scale_audit import (
    build_stage_motion_audit_dict,
    inferred_um_per_unit,
)


def test_build_stage_motion_audit_dict_ratio() -> None:
    sm = {
        "actual_travel_user": 100.0,
        "travel_user_commanded_raw": 100.0,
        "actual_speed_user_s": 5.0,
        "stage_um_per_unit": 1.25,
        "actual_metric": {"actual_travel_um": 125.0, "actual_speed_um_s": 6.25},
    }
    d = build_stage_motion_audit_dict(sm)
    assert d["actual_travel_user_over_commanded"] == 1.0
    assert d["actual_travel_um"] == 125.0
    assert "validation_hint" in d


def test_inferred_um_per_unit() -> None:
    assert inferred_um_per_unit(actual_travel_user=100.0, measured_travel_um=125.0) == 1.25
