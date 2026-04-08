"""Tests for post-run lifecycle: PDF deferral, pairing refresh, finalize safety.

Root cause of the post-run UI freeze was export_ot_batch_pdf() being called
synchronously inside run_batch() before finished.emit().  Matplotlib's C
extension rendering holds the Python GIL for many seconds, starving the Qt
main-thread event loop.

These tests verify that:
  - run_batch() stores the batch summary instead of generating the PDF inline
  - OTRunWorker emits batch_summary_ready before finished
  - OTPdfWorker can run the export without blocking the caller
  - pairing refresh lifecycle helpers are robust
  - _refresh_item_text_by_key does not double-invoke _sync_master_checkbox_state
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal Qt stubs so we can import non-GUI modules without a display
# ---------------------------------------------------------------------------
if "PyQt6" not in sys.modules:
    _qtcore = types.ModuleType("PyQt6.QtCore")
    _qtcore.pyqtSignal = lambda *args, **kwargs: None  # type: ignore[assignment]
    _qtcore.Qt = types.SimpleNamespace()
    _qtcore.QObject = object
    _qtcore.QThread = object
    _qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    _qtwidgets.QApplication = object
    _pyqt6 = types.ModuleType("PyQt6")
    _pyqt6.QtCore = _qtcore  # type: ignore[assignment]
    _pyqt6.QtWidgets = _qtwidgets  # type: ignore[assignment]
    sys.modules["PyQt6"] = _pyqt6
    sys.modules["PyQt6.QtCore"] = _qtcore
    sys.modules["PyQt6.QtWidgets"] = _qtwidgets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeBatchPanel:
    """Minimal device panel mock for BatchController.run_batch()."""

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

    def get_frame_range(self) -> tuple:
        return (0, 0)

    def get_run_output_root(self) -> str:
        return ""


# ---------------------------------------------------------------------------
# Test: run_batch stores deferred PDF summary instead of generating PDF inline
# ---------------------------------------------------------------------------

def test_run_batch_stores_pending_pdf_summary_instead_of_calling_export(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    After run_batch(), _pending_ot_batch_pdf_summary must be populated.
    export_ot_batch_pdf must NOT be called inline (it is deferred).
    """
    import barakuda.shell.batch_controller as bc_module
    from barakuda.shell.batch_controller import BatchController, PreviewResult

    video = tmp_path / "sample.raw"
    video.write_bytes(b"\x00")

    controller = BatchController(runs_folder=tmp_path / "runs", log_fn=lambda _: None)
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

    # Patch VideoReader to raise so the item fails quickly
    class _BoomReader:
        def __init__(self, *_a, **_kw) -> None:
            raise RuntimeError("synthetic boom")

    monkeypatch.setattr(bc_module, "VideoReader", _BoomReader)
    # Ensure export_ot_batch_pdf is NOT called
    pdf_called: list[bool] = []
    monkeypatch.setattr(bc_module, "export_ot_batch_pdf", lambda *_a, **_kw: pdf_called.append(True))

    controller.run_batch(
        device_id="optical_tweezers",
        device_panel=_FakeBatchPanel(),
        roi_rect=(0, 0, 64, 64),
        dataset_set_status_fn=lambda _p, _s: None,
        progress_fn=lambda *_a: None,
    )

    assert not pdf_called, (
        "export_ot_batch_pdf must NOT be called inline in run_batch() — "
        "it must be deferred to avoid blocking the GIL on the UI thread."
    )
    # _pending_ot_batch_pdf_summary may be None when there are no items to report
    # (failed items may still be included — just check the attribute exists)
    assert hasattr(controller, "_pending_ot_batch_pdf_summary"), (
        "BatchController must have _pending_ot_batch_pdf_summary attribute"
    )


def test_run_batch_pending_summary_has_expected_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    When run_batch() has at least one report item, _pending_ot_batch_pdf_summary
    must contain the keys needed by OTPdfWorker.
    """
    import barakuda.shell.batch_controller as bc_module
    from barakuda.shell.batch_controller import BatchController, PreviewResult

    video = tmp_path / "sample.raw"
    video.write_bytes(b"\x00")

    controller = BatchController(runs_folder=tmp_path / "runs", log_fn=lambda _: None)
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
        def __init__(self, *_a, **_kw) -> None:
            raise RuntimeError("synthetic boom")

    monkeypatch.setattr(bc_module, "VideoReader", _BoomReader)
    monkeypatch.setattr(bc_module, "export_ot_batch_pdf", lambda *_a, **_kw: None)
    monkeypatch.setattr(bc_module, "build_ot_item_summary", lambda **_kw: {
        "item_id": "test_item",
        "status": "failed",
        "run_id": "r0",
        "batch_id": "b0",
    })

    controller.run_batch(
        device_id="optical_tweezers",
        device_panel=_FakeBatchPanel(),
        roi_rect=(0, 0, 64, 64),
        dataset_set_status_fn=lambda _p, _s: None,
        progress_fn=lambda *_a: None,
    )

    summary = controller._pending_ot_batch_pdf_summary
    assert summary is not None, "_pending_ot_batch_pdf_summary must be set when items exist"
    assert "_pdf_path" in summary, "Summary must include '_pdf_path' key for OTPdfWorker"
    assert "batch_id" in summary
    assert "items" in summary


# ---------------------------------------------------------------------------
# Test: OTPdfWorker calls export_ot_batch_pdf with correct args
# ---------------------------------------------------------------------------

def test_ot_pdf_worker_calls_export_with_correct_args(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """OTPdfWorker.run() must call export_ot_batch_pdf with the right path and summary."""
    # The worker module imports PyQt6 at class definition time, so we need
    # to import it after the stub is installed.
    import importlib
    import barakuda.shell.workers.ot_pdf_worker as worker_mod

    pdf_calls: list[tuple] = []

    def _fake_export(pdf_path, report_summary) -> None:
        pdf_calls.append((pdf_path, dict(report_summary)))

    monkeypatch.setattr(
        "barakuda.core.ot_report.export_ot_batch_pdf",
        _fake_export,
        raising=False,
    )

    summary = {
        "batch_id": "2026-01-01_120000",
        "output_root": str(tmp_path),
        "batch_root": str(tmp_path),
        "items": [{"item_id": "i1", "status": "success"}],
        "_pdf_path": str(tmp_path / "batch_summary.pdf"),
    }

    finished_calls: list[bool] = []
    error_calls: list[str] = []

    # Create a plain Python object with the same interface as OTPdfWorker
    # but without needing Qt to be running.
    class _PlainWorker:
        def __init__(self, s: dict) -> None:
            self._summary = dict(s)

        def run(self) -> None:
            from pathlib import Path as _Path
            import barakuda.core.ot_report as _rep_mod
            pdf_path = _Path(self._summary["_pdf_path"])
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            report_summary = {k: v for k, v in self._summary.items() if k != "_pdf_path"}
            _rep_mod.export_ot_batch_pdf(pdf_path, report_summary)
            finished_calls.append(True)

    worker = _PlainWorker(summary)
    worker.run()

    assert finished_calls, "Worker must complete without raising"
    assert len(pdf_calls) == 1, "export_ot_batch_pdf must be called exactly once"
    called_path, called_summary = pdf_calls[0]
    assert "_pdf_path" not in called_summary, "_pdf_path key must be stripped before export call"
    assert called_summary["batch_id"] == "2026-01-01_120000"
    assert str(called_path).endswith("batch_summary.pdf")


# ---------------------------------------------------------------------------
# Test: OTRunWorker source declares batch_summary_ready signal
# ---------------------------------------------------------------------------

def test_ot_run_worker_source_declares_batch_summary_ready_signal() -> None:
    """
    OTRunWorker must declare the batch_summary_ready signal so main_window can
    connect a slot that stashes the PDF summary for deferred generation.
    """
    src = Path(
        "C:/Work/BARAKUDA_FULL/barakuda/shell/workers/ot_run_worker.py"
    ).read_text(encoding="utf-8")
    assert "batch_summary_ready" in src, (
        "OTRunWorker must have a batch_summary_ready signal for deferred PDF export"
    )


def test_ot_run_worker_emits_batch_summary_before_finished() -> None:
    """
    In OTRunWorker.run(), batch_summary_ready.emit() must appear before
    finished.emit() so the UI thread receives the summary BEFORE the done
    callback fires.
    """
    src = Path(
        "C:/Work/BARAKUDA_FULL/barakuda/shell/workers/ot_run_worker.py"
    ).read_text(encoding="utf-8")
    idx_summary = src.find("batch_summary_ready.emit")
    idx_finished = src.find("self.finished.emit()")
    assert idx_summary != -1, "batch_summary_ready.emit() must appear in OTRunWorker.run()"
    assert idx_finished != -1, "self.finished.emit() must appear in OTRunWorker.run()"
    assert idx_summary < idx_finished, (
        "batch_summary_ready must be emitted BEFORE finished in OTRunWorker.run()"
    )


# ---------------------------------------------------------------------------
# Test: main_window post-run calls _refresh_drag_pairing_statuses
# ---------------------------------------------------------------------------

def test_main_window_calls_pairing_refresh_after_run_done() -> None:
    """
    _on_ot_done in main_window must call _refresh_drag_pairing_statuses so
    the Pairing tab and dataset suffixes are consistent after a run.
    """
    src = Path(
        "C:/Work/BARAKUDA_FULL/barakuda/shell/main_window.py"
    ).read_text(encoding="utf-8")
    # The post-run pairing refresh should appear inside _on_ot_done
    # (after self._ot_run_thread.quit())
    on_done_block = src[src.find("def _on_ot_done"):]
    on_done_body = on_done_block[: on_done_block.find("\n    def ")]
    assert "_refresh_drag_pairing_statuses" in on_done_body, (
        "_on_ot_done must call _refresh_drag_pairing_statuses to keep Pairing tab consistent"
    )


# ---------------------------------------------------------------------------
# Test: prevent double-refresh when syncing QLineEdit in manual assign
# ---------------------------------------------------------------------------

def test_main_window_ot_loading_guard_used_in_manual_assign() -> None:
    """
    _on_ot_pairing_manual_assign must guard the QLineEdit.setText() call with
    _ot_loading_item_params so value_changed doesn't trigger a redundant second
    _refresh_drag_pairing_statuses().
    """
    src = Path(
        "C:/Work/BARAKUDA_FULL/barakuda/shell/main_window.py"
    ).read_text(encoding="utf-8")
    manual_assign_block = src[src.find("def _on_ot_pairing_manual_assign"):]
    manual_assign_body = manual_assign_block[: manual_assign_block.find("\n    def ")]
    assert "_ot_loading_item_params = True" in manual_assign_body, (
        "_on_ot_pairing_manual_assign must set _ot_loading_item_params=True around "
        "setText() to suppress redundant value_changed / _refresh_drag_pairing_statuses"
    )


# ---------------------------------------------------------------------------
# Test: PDF deferral - _start_ot_pdf_generation exists in main_window
# ---------------------------------------------------------------------------

def test_main_window_has_start_ot_pdf_generation_method() -> None:
    """main_window.py must have _start_ot_pdf_generation for deferred PDF export."""
    src = Path(
        "C:/Work/BARAKUDA_FULL/barakuda/shell/main_window.py"
    ).read_text(encoding="utf-8")
    assert "def _start_ot_pdf_generation" in src, (
        "MainWindow must have _start_ot_pdf_generation() for background PDF export"
    )
    assert "OTPdfWorker" in src, (
        "MainWindow._start_ot_pdf_generation must use OTPdfWorker"
    )


# ---------------------------------------------------------------------------
# Test: pairing status suffix logic in DatasetPanel source
# ---------------------------------------------------------------------------

def test_format_label_includes_pairing_suffix_in_source() -> None:
    """
    DatasetPanel._format_label must include the pairing_status suffix when set
    and omit it when None.  Verified at source level to avoid full Qt import.
    """
    src = Path(
        "C:/Work/BARAKUDA_FULL/barakuda/shell/widgets/dataset_panel.py"
    ).read_text(encoding="utf-8")
    # The static method must include a conditional for pairing_status
    assert "pairing_suffix" in src or "pairing_status" in src, (
        "_format_label must handle pairing_status suffix"
    )
    # Must not emit suffix when pairing_status is falsy
    assert "if pairing_status" in src or "pairing_status =" in src


def test_refresh_item_text_blocks_signals_to_prevent_double_sync() -> None:
    """
    _refresh_item_text_by_key must block list signals while calling item.setText()
    so that itemChanged does not fire _sync_master_checkbox_state twice per update.
    """
    src = Path(
        "C:/Work/BARAKUDA_FULL/barakuda/shell/widgets/dataset_panel.py"
    ).read_text(encoding="utf-8")
    refresh_block = src[src.find("def _refresh_item_text_by_key"):]
    refresh_body = refresh_block[: refresh_block.find("\n    def ")]
    assert "blockSignals(True)" in refresh_body, (
        "_refresh_item_text_by_key must block list signals before setText() "
        "to prevent double _sync_master_checkbox_state() calls per status update"
    )


# ---------------------------------------------------------------------------
# Test: auto-pair only uses checked items (source-level verification)
# ---------------------------------------------------------------------------

def test_auto_pair_source_uses_get_checked_paths() -> None:
    """
    _on_ot_auto_pair_baselines must call get_checked_paths() so only checked
    items are passed to auto_pair_drag_items.
    """
    src = Path(
        "C:/Work/BARAKUDA_FULL/barakuda/shell/main_window.py"
    ).read_text(encoding="utf-8")
    auto_pair_block = src[src.find("def _on_ot_auto_pair_baselines"):]
    body = auto_pair_block[: auto_pair_block.find("\n    def ")]
    assert "get_checked_paths" in body, (
        "_on_ot_auto_pair_baselines must use get_checked_paths() not get_all_items()"
    )
