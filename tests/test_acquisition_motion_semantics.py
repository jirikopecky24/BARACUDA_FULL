from __future__ import annotations

import json
from pathlib import Path

from barakuda.devices.acquisition.camera import RecordResult
from barakuda.devices.acquisition.motion.metric_conversion import (
    MetricMotionCommand,
    convert_metric_intent_to_backend_command,
)
from barakuda.devices.acquisition.motion.stage_scale_audit import (
    ACQUISITION_DEFAULT_STAGE_UM_PER_UNIT,
)
from barakuda.devices.acquisition.motion.motion_run import (
    format_record_motion_start_log,
    resolve_unique_run_target,
    run_record_and_motion,
)
from barakuda.devices.acquisition.motion.recipes import ConstantVelocityDragRecipe
from barakuda.devices.acquisition.motion.stage_base import AbstractStage, MotionResult


class _FakeCamera:
    def __init__(self, output_dir: Path, basename: str):
        self._output_dir = output_dir
        self._basename = basename
        self.stop_calls = 0

    def record_raw(self, **_kwargs):
        video = self._output_dir / f"{self._basename}.raw"
        meta = self._output_dir / f"{self._basename}_meta.json"
        video.write_bytes(b"raw")
        meta.write_text("{}", encoding="utf-8")
        return RecordResult(
            video_path=str(video),
            meta_path=str(meta),
            frames_written=10,
            fps_effective=100.0,
            dropped=0,
            meta={"timing_source": "timestamps"},
        )

    def stop_record(self):
        self.stop_calls += 1


class _FakeStage(AbstractStage):
    CONTROLLER_NAME = "ximc"

    def __init__(self, stage_um_per_unit: float):
        self._connected = True
        self._scale = stage_um_per_unit
        self.last_move = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, device_id: str) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def get_position(self) -> float:
        return 0.0

    def move_constant_velocity(
        self,
        direction: int,
        travel: float,
        speed: float,
        accel: float,
        decel: float,
        stop_event=None,
    ) -> MotionResult:
        self.last_move = {
            "direction": direction,
            "travel": travel,
            "speed": speed,
            "accel": accel,
            "decel": decel,
        }
        return MotionResult(
            actual_travel_user=travel,
            actual_duration_s=2.0,
            actual_speed_user_s=travel / 2.0,
            controller=self.CONTROLLER_NAME,
            stage_um_per_unit=self._scale,
        )

    def stop(self) -> None:
        return None

    def get_stage_um_per_unit(self):
        return self._scale


class _FakeStageWithDiag(_FakeStage):
    def move_constant_velocity(
        self,
        direction: int,
        travel: float,
        speed: float,
        accel: float,
        decel: float,
        stop_event=None,
    ) -> MotionResult:
        base = super().move_constant_velocity(direction, travel, speed, accel, decel, stop_event)
        return MotionResult(
            actual_travel_user=base.actual_travel_user,
            actual_duration_s=base.actual_duration_s,
            actual_speed_user_s=base.actual_speed_user_s,
            controller=base.controller,
            stage_um_per_unit=base.stage_um_per_unit,
            commanded_speed_raw=float(speed),
            speed_reg_readback_raw=float(speed),
            pre_motion_flags=48,
            pre_motion_gpio_flags=16,
            pre_motion_mv_cmd_sts=1,
            pre_motion_alarm_nonfatal_allowed=True,
        )


def test_travel_conversion_uses_metric_travel_and_keeps_raw_register_kinematics():
    backend = convert_metric_intent_to_backend_command(
        legacy_travel_user=9999.0,
        legacy_direction=1,
        legacy_speed_reg=60.0,
        legacy_accel_reg=120.0,
        legacy_decel_reg=140.0,
        metric_command=MetricMotionCommand(
            axis="x",
            direction=1,
            travel_um=2500.0,
            speed_um_s=None,
            accel_um_s2=None,
            decel_um_s2=None,
        ),
        stage_um_per_unit=1.25,
        ximc_metric_calibration=None,
    )
    assert backend.travel_user == 2000.0
    assert backend.speed_reg == 60.0
    assert backend.accel_reg == 120.0
    assert backend.decel_reg == 140.0
    assert backend.conversion_mode == "legacy_raw_registers"


def test_start_log_reflects_current_metric_travel_and_raw_register_values():
    recipe = ConstantVelocityDragRecipe(
        axis="x",
        direction=1,
        travel=2000.0,
        speed=30000.0,
        accel=10000.0,
        decel=10000.0,
        pre_delay_s=2.0,
        post_delay_s=2.0,
    )
    line = format_record_motion_start_log(
        recipe=recipe,
        metric_command=MetricMotionCommand(axis="x", direction=1, travel_um=2500.0),
        metric_mapping_profile=None,
        stage_um_per_unit=1.25,
    )
    assert "travel_metric=2500.000 µm" in line
    assert "travel_user=2000.000" in line
    assert "speed_reg=30000" in line
    assert "accel_reg=10000" in line
    assert "decel_reg=10000" in line
    assert "speed=30.0" not in line


def test_resolve_unique_run_target_prevents_silent_overwrite(tmp_path: Path):
    root = tmp_path / "video"
    root.mkdir(parents=True, exist_ok=True)
    first_name, first_dir = resolve_unique_run_target(root, "Basler_manual")
    assert first_name == "Basler_manual"
    assert first_dir.exists()
    # Next run with same basename must not reuse same directory.
    second_name, second_dir = resolve_unique_run_target(root, "Basler_manual")
    assert second_name != first_name
    assert second_name.startswith("Basler_manual_r")
    assert second_dir.exists()
    assert second_dir != first_dir


def test_run_record_and_motion_keeps_raw_speed_register_path_without_mapping(tmp_path: Path):
    output_dir = tmp_path / "run"
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = "acq"
    camera = _FakeCamera(output_dir, basename)
    stage = _FakeStage(stage_um_per_unit=1.25)
    recipe = ConstantVelocityDragRecipe(
        axis="x",
        direction=1,
        travel=2000.0,
        speed=60.0,
        accel=120.0,
        decel=140.0,
        pre_delay_s=0.0,
        post_delay_s=0.0,
    )
    result = run_record_and_motion(
        camera=camera,
        stage=stage,
        recipe=recipe,
        output_dir=str(output_dir),
        basename=basename,
        duration_s=0.0,
        roi=(0, 0, 100, 100),
        exposure_us=1000.0,
        gain=None,
        fps_hint=100.0,
        pixel_format="Mono8",
        metric_command=MetricMotionCommand(
            axis="x",
            direction=1,
            travel_um=2500.0,
            speed_um_s=None,
            accel_um_s2=None,
            decel_um_s2=None,
        ),
        metric_mapping_profile=None,
    )

    assert stage.last_move is not None
    assert stage.last_move["travel"] == 2000.0
    assert stage.last_move["speed"] == 60.0
    assert stage.last_move["accel"] == 120.0
    assert stage.last_move["decel"] == 140.0

    stage_meta = json.loads(Path(result.stage_json_path).read_text(encoding="utf-8"))
    assert stage_meta["speed_reg_commanded_raw"] == 60.0
    assert stage_meta["accel_reg_commanded_raw"] == 120.0
    assert stage_meta["decel_reg_commanded_raw"] == 140.0
    assert stage_meta["speed_user_s_commanded"] == 60.0  # legacy-compatible
    assert stage_meta["commanded_metric"]["speed_um_s"] is None
    assert stage_meta["actual_metric"]["actual_speed_um_s"] is not None
    assert stage_meta["speed_control_validation_status"] in {"pass", "suspect"}


def test_no_stale_cached_recipe_between_runs(tmp_path: Path):
    output_dir = tmp_path / "run_stale"
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = _FakeStage(stage_um_per_unit=1.25)
    camera1 = _FakeCamera(output_dir, "r1")
    camera2 = _FakeCamera(output_dir, "r2")
    logs1: list[str] = []
    logs2: list[str] = []

    recipe1 = ConstantVelocityDragRecipe(
        axis="x",
        direction=1,
        travel=2000.0,
        speed=30000.0,
        accel=10000.0,
        decel=10000.0,
        pre_delay_s=0.0,
        post_delay_s=0.0,
    )
    recipe2 = ConstantVelocityDragRecipe(
        axis="x",
        direction=1,
        travel=1200.0,
        speed=15000.0,
        accel=9000.0,
        decel=9000.0,
        pre_delay_s=0.0,
        post_delay_s=0.0,
    )

    run_record_and_motion(
        camera=camera1,
        stage=stage,
        recipe=recipe1,
        output_dir=str(output_dir),
        basename="r1",
        duration_s=0.0,
        roi=(0, 0, 100, 100),
        exposure_us=1000.0,
        gain=None,
        fps_hint=100.0,
        pixel_format="Mono8",
        metric_command=MetricMotionCommand(axis="x", direction=1, travel_um=2500.0),
        metric_mapping_profile=None,
        log_fn=logs1.append,
    )
    run_record_and_motion(
        camera=camera2,
        stage=stage,
        recipe=recipe2,
        output_dir=str(output_dir),
        basename="r2",
        duration_s=0.0,
        roi=(0, 0, 100, 100),
        exposure_us=1000.0,
        gain=None,
        fps_hint=100.0,
        pixel_format="Mono8",
        metric_command=MetricMotionCommand(axis="x", direction=1, travel_um=1500.0),
        metric_mapping_profile=None,
        log_fn=logs2.append,
    )

    log1 = " | ".join(logs1)
    log2 = " | ".join(logs2)
    assert "speed_reg=30000" in log1
    assert "speed_reg=15000" in log2
    assert "travel_user=2000.000" in log1
    assert "travel_user=1200.000" in log2
    assert "speed_reg=30000" not in log2


def test_speed_effect_suspect_flag_when_actual_speed_is_invariant_vs_recent_run(tmp_path: Path):
    root = tmp_path / "video"
    run_prev = root / "run_prev"
    run_prev.mkdir(parents=True, exist_ok=True)
    (run_prev / "run_prev_stage.json").write_text(
        json.dumps(
            {
                "speed_reg_commanded_raw": 15.0,
                "actual_speed_user_s": 400.0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    run_cur = root / "run_cur"
    run_cur.mkdir(parents=True, exist_ok=True)
    camera = _FakeCamera(run_cur, "run_cur")
    stage = _FakeStage(stage_um_per_unit=1.0)
    recipe = ConstantVelocityDragRecipe(
        axis="x",
        direction=1,
        travel=800.0,
        speed=35.0,
        accel=10000.0,
        decel=10000.0,
        pre_delay_s=0.0,
        post_delay_s=0.0,
    )
    result = run_record_and_motion(
        camera=camera,
        stage=stage,
        recipe=recipe,
        output_dir=str(run_cur),
        basename="run_cur",
        duration_s=0.0,
        roi=(0, 0, 100, 100),
        exposure_us=1000.0,
        gain=None,
        fps_hint=100.0,
        pixel_format="Mono8",
        metric_command=MetricMotionCommand(axis="x", direction=1, travel_um=800.0),
        metric_mapping_profile=None,
    )
    stage_meta = json.loads(Path(result.stage_json_path).read_text(encoding="utf-8"))
    assert stage_meta["speed_effect_suspect"] is True
    assert stage_meta["speed_control_validation_status"] == "suspect"
    assert any(
        "speed_effect_invariant_vs_recent_run" in r
        for r in stage_meta["speed_control_validation_reasons"]
    )


def test_stage_meta_keeps_commanded_raw_and_measured_metric_separate(tmp_path: Path):
    output_dir = tmp_path / "run2"
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = "acq2"
    camera = _FakeCamera(output_dir, basename)
    stage = _FakeStage(stage_um_per_unit=1.25)
    recipe = ConstantVelocityDragRecipe(
        axis="x",
        direction=1,
        travel=1600.0,
        speed=10000.0,
        accel=10000.0,
        decel=10000.0,
        pre_delay_s=0.0,
        post_delay_s=0.0,
    )
    result = run_record_and_motion(
        camera=camera,
        stage=stage,
        recipe=recipe,
        output_dir=str(output_dir),
        basename=basename,
        duration_s=0.0,
        roi=(0, 0, 100, 100),
        exposure_us=1000.0,
        gain=None,
        fps_hint=100.0,
        pixel_format="Mono8",
        metric_command=MetricMotionCommand(axis="x", direction=1, travel_um=2000.0),
        metric_mapping_profile=None,
    )
    stage_meta = json.loads(Path(result.stage_json_path).read_text(encoding="utf-8"))
    assert stage_meta["speed_reg_commanded_raw"] == 10000.0
    assert stage_meta["accel_reg_commanded_raw"] == 10000.0
    assert stage_meta["decel_reg_commanded_raw"] == 10000.0
    assert stage_meta["actual_metric"]["actual_travel_um"] is not None
    assert stage_meta["actual_metric"]["actual_speed_um_s"] is not None
    assert stage_meta["actual_metric"]["actual_motion_duration_s"] is not None


def test_speed_audit_fields_are_persisted(tmp_path: Path):
    output_dir = tmp_path / "run_diag"
    output_dir.mkdir(parents=True, exist_ok=True)
    camera = _FakeCamera(output_dir, "diag")
    stage = _FakeStageWithDiag(stage_um_per_unit=1.25)
    recipe = ConstantVelocityDragRecipe(
        axis="x",
        direction=1,
        travel=1000.0,
        speed=35.0,
        accel=20.0,
        decel=20.0,
        pre_delay_s=0.0,
        post_delay_s=0.0,
    )
    result = run_record_and_motion(
        camera=camera,
        stage=stage,
        recipe=recipe,
        output_dir=str(output_dir),
        basename="diag",
        duration_s=0.0,
        roi=(0, 0, 100, 100),
        exposure_us=1000.0,
        gain=None,
        fps_hint=100.0,
        pixel_format="Mono8",
        metric_command=MetricMotionCommand(axis="x", direction=1, travel_um=1250.0),
        metric_mapping_profile=None,
    )
    stage_meta = json.loads(Path(result.stage_json_path).read_text(encoding="utf-8"))
    assert stage_meta["speed_reg_commanded_raw"] == 35.0
    assert stage_meta["speed_reg_readback_raw"] == 35.0
    assert stage_meta["actual_speed_user_s"] is not None
    assert stage_meta["actual_metric"]["actual_speed_um_s"] is not None
    assert stage_meta["pre_motion_status_flags"] == 48
    assert stage_meta["speed_effect_suspect"] is True
    assert stage_meta["speed_control_validation_status"] == "suspect"


def test_metric_travel_conversion_matches_calibration_grid_scale_chain() -> None:
    backend = convert_metric_intent_to_backend_command(
        legacy_travel_user=9999.0,
        legacy_direction=1,
        legacy_speed_reg=60.0,
        legacy_accel_reg=120.0,
        legacy_decel_reg=120.0,
        metric_command=MetricMotionCommand(axis="x", direction=1, travel_um=10.0),
        stage_um_per_unit=ACQUISITION_DEFAULT_STAGE_UM_PER_UNIT,
        ximc_metric_calibration=None,
    )
    # 10 µm at 0.0625 µm/unit -> 160 user units (matches validation run shape).
    assert backend.travel_user == 160.0
    assert backend.travel_source == "metric_travel_um_via_stage_um_per_unit"


def test_stage_json_actual_metric_uses_chain_default_scale_consistently(tmp_path: Path):
    output_dir = tmp_path / "run_chain_scale"
    output_dir.mkdir(parents=True, exist_ok=True)
    camera = _FakeCamera(output_dir, "chain")
    stage = _FakeStage(stage_um_per_unit=ACQUISITION_DEFAULT_STAGE_UM_PER_UNIT)
    recipe = ConstantVelocityDragRecipe(
        axis="x",
        direction=1,
        travel=160.0,
        speed=60.0,
        accel=120.0,
        decel=120.0,
        pre_delay_s=0.0,
        post_delay_s=0.0,
    )
    result = run_record_and_motion(
        camera=camera,
        stage=stage,
        recipe=recipe,
        output_dir=str(output_dir),
        basename="chain",
        duration_s=0.0,
        roi=(0, 0, 100, 100),
        exposure_us=1000.0,
        gain=None,
        fps_hint=100.0,
        pixel_format="Mono8",
        metric_command=MetricMotionCommand(axis="x", direction=1, travel_um=10.0),
        metric_mapping_profile=None,
    )
    stage_meta = json.loads(Path(result.stage_json_path).read_text(encoding="utf-8"))
    assert stage_meta["stage_um_per_unit"] == ACQUISITION_DEFAULT_STAGE_UM_PER_UNIT
    assert stage_meta["actual_metric"]["actual_travel_um"] == 10.0
    assert stage_meta["actual_metric"]["actual_speed_um_s"] == 5.0


def test_finalization_breadcrumbs_are_emitted_in_order(tmp_path: Path):
    output_dir = tmp_path / "run_lifecycle"
    output_dir.mkdir(parents=True, exist_ok=True)
    camera = _FakeCamera(output_dir, "lifecycle")
    stage = _FakeStage(stage_um_per_unit=1.0)
    logs: list[str] = []
    recipe = ConstantVelocityDragRecipe(
        axis="x",
        direction=1,
        travel=1000.0,
        speed=5000.0,
        accel=5000.0,
        decel=5000.0,
        pre_delay_s=0.0,
        post_delay_s=0.0,
    )
    run_record_and_motion(
        camera=camera,
        stage=stage,
        recipe=recipe,
        output_dir=str(output_dir),
        basename="lifecycle",
        duration_s=0.0,
        roi=(0, 0, 100, 100),
        exposure_us=1000.0,
        gain=None,
        fps_hint=100.0,
        pixel_format="Mono8",
        metric_command=MetricMotionCommand(axis="x", direction=1, travel_um=1000.0),
        metric_mapping_profile=None,
        log_fn=logs.append,
    )
    merged = " | ".join(logs)
    order = [
        "finalize_recording: stop_record begin",
        "finalize_recording: stop_record done",
        "finalize_recording: join begin",
        "finalize_recording: join done",
        "artifact_write: stage_trace begin",
        "artifact_write: stage_trace done",
        "artifact_write: stage_json begin",
        "artifact_write: stage_json done",
    ]
    positions = [merged.find(token) for token in order]
    assert all(pos >= 0 for pos in positions)
    assert positions == sorted(positions)
