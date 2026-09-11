from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest

# Module-scope stub: the barakuda.shell.batch_controller import below needs
# *something* importable at PyQt6, so we use pytest.MonkeyPatch directly (its
# public, fixture-free API — the per-test monkeypatch fixture isn't available
# yet at collection time) and undo it right after the import, before pytest
# collects the next test file, so the fake never leaks past this module.
_mp = pytest.MonkeyPatch()
if "PyQt6" not in sys.modules:
    _qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    _qtwidgets.QApplication = object
    _pyqt6 = types.ModuleType("PyQt6")
    _pyqt6.QtWidgets = _qtwidgets
    _mp.setitem(sys.modules, "PyQt6", _pyqt6)
    _mp.setitem(sys.modules, "PyQt6.QtWidgets", _qtwidgets)

from barakuda.shell import batch_controller as bc_module
from barakuda.shell.batch_controller import BatchController, PreviewResult

_mp.undo()


class _MetaFull:
    frame_count = 120
    t_first_s = 1.0
    t_last_s = 3.0
    elapsed_time_s = 2.0
    effective_fps = 59.5
    timing_source = "timestamps"
    timing_source_detail = "validated_timestamps_csv:run_timestamps.csv"
    timestamp_validation_pass = True
    timestamp_validation_message = "timestamps validated"
    frame_to_time_s = {0: 1.0, 1: 1.02}


class _MetaLegacy:
    frame_count = 120
    fps = 60.0


class _FakePanel:
    def __init__(self) -> None:
        self._current_path = ""

    def set_current_path(self, path: str) -> None:
        self._current_path = path

    def get_tracking_params(self) -> dict:
        return {"method": "RADIAL_SYMMETRY", "fps_override": 0.0}

    def get_postprocess_params(self) -> dict:
        return {
            "enabled": True,
            "qc_enabled": True,
            "q_min": 0.0,
            "jump_max_px": 50.0,
            "drift_enabled": True,
            "drift_window_s": 1.0,
            "physics_mode": "BROWNIAN",
            "stage_speed_um_s": 0.0,
            "drag_axis": "x",
            "viscosity_pa_s": 1.0e-3,
            "bead_radius_um": 0.5,
            "bead_diameter_um": 1.0,
            "temperature_c": 25.0,
        }

    def get_scale_params(self) -> dict:
        return {
            "use_dataset_scale": False,
            "um_per_px": 0.06042,
            "use_dataset_stage_scale": False,
            "stage_um_per_unit": 1.25,
        }

    def get_frame_range(self) -> tuple[int, int]:
        return (0, 0)

    def get_run_output_root(self) -> str:
        return ""


def test_resolve_timing_truth_from_complete_meta_uses_meta_values(tmp_path: Path) -> None:
    video = tmp_path / "run.raw"
    video.write_bytes(b"\x00")
    truth = BatchController._resolve_timing_truth_from_meta(
        video_path=video,
        meta_obj=_MetaFull(),
        frame_count=120,
        fps_hint=60.0,
    )
    assert truth.frame_count == 120
    assert truth.effective_fps == 59.5
    assert truth.timing_source == "timestamps"
    assert truth.timestamp_validation_pass is True


def test_resolve_timing_truth_from_legacy_meta_falls_back(tmp_path: Path) -> None:
    video = tmp_path / "run.raw"
    video.write_bytes(b"\x00")
    truth = BatchController._resolve_timing_truth_from_meta(
        video_path=video,
        meta_obj=_MetaLegacy(),
        frame_count=120,
        fps_hint=60.0,
    )
    assert truth.timing_source == "estimated"
    assert truth.effective_fps == 60.0
    assert truth.timestamp_validation_pass is False


def test_run_batch_primary_failure_is_not_masked_by_exception_handler(
    tmp_path: Path,
    monkeypatch,
) -> None:
    logs: list[str] = []
    statuses: list[tuple[Path, str]] = []
    progress_calls: list[tuple[int, int, str, int]] = []

    video = tmp_path / "input.raw"
    video.write_bytes(b"\x00")

    controller = BatchController(runs_folder=tmp_path / "runs", log_fn=logs.append)
    controller._preview_done = True
    controller._last_preview_results = [
        PreviewResult(
            path=str(video),
            ok=True,
            status="PASS",
            message="ok",
            details={"resolved_video_path": str(video)},
        )
    ]

    class _BoomReader:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("primary boom")

    monkeypatch.setattr(bc_module, "VideoReader", _BoomReader)

    def _summary_boom(**_kwargs):
        raise RuntimeError("summary boom")

    monkeypatch.setattr(bc_module, "build_ot_item_summary", _summary_boom)
    monkeypatch.setattr(bc_module, "export_ot_batch_pdf", lambda *_a, **_k: None)

    def _set_status(path: Path, status: str) -> None:
        statuses.append((Path(path), status))

    def _progress(done: int, total: int, name: str, percent: int) -> None:
        progress_calls.append((done, total, name, percent))

    controller.run_batch(
        device_id="optical_tweezers",
        device_panel=_FakePanel(),
        roi_rect=(0, 0, 64, 64),
        dataset_set_status_fn=_set_status,
        progress_fn=_progress,
    )

    assert (video, "running") in statuses
    assert (video, "failed") in statuses
    assert any("primary boom" in line for line in logs)
    assert any("summary boom" in line for line in logs)
    assert progress_calls, "progress callback should be called even on failure"
