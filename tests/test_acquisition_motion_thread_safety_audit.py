from __future__ import annotations

from pathlib import Path


def _read_panel_source() -> str:
    return Path("barakuda/devices/acquisition/ui/panel.py").read_text(encoding="utf-8")


def test_worker_logging_path_uses_signal_handoff_not_direct_gui_callback():
    src = _read_panel_source()
    assert "log_msg = pyqtSignal(str)" in src
    assert "log_fn=self._emit_log" in src
    assert "log_fn=self._log" not in src
    assert "_motion_worker.log_msg.connect(" in src


def test_done_error_paths_have_panel_closing_guard():
    src = _read_panel_source()
    done_idx = src.find("def _on_record_motion_done(")
    err_idx = src.find("def _on_record_motion_error(")
    assert done_idx >= 0
    assert err_idx >= 0
    done_block = src[done_idx:err_idx]
    err_block = src[err_idx: src.find("def _on_motion_elapsed_tick(", err_idx)]
    assert "if self._panel_closing:" in done_block
    assert "if self._panel_closing:" in err_block
