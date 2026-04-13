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


def test_grid_validation_run_20260413_093635_infers_about_0p06_um_per_unit() -> None:
    # Physical validation run:
    # ~4 fields × 2.5 µm = ~10 µm for actual_travel_user=160
    inferred = inferred_um_per_unit(actual_travel_user=160.0, measured_travel_um=10.0)
    assert inferred == 0.0625
    # The historical 1.25 µm/unit assumption is incompatible with this run.
    assert abs(inferred - 1.25) > 1.0


def test_grid_validation_run_20260413_100641_infers_about_0p06_um_per_unit() -> None:
    # Physical validation run:
    # ~7.5 fields × 2.5 µm = ~18.75 µm for actual_travel_user=320
    inferred = inferred_um_per_unit(actual_travel_user=320.0, measured_travel_um=18.75)
    assert inferred == 0.05859375
    assert 0.055 <= inferred <= 0.065
    # The historical 1.25 µm/unit assumption is incompatible with this run.
    assert abs(inferred - 1.25) > 1.0
