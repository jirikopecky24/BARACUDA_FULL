from __future__ import annotations
import traceback
from PyQt6.QtCore import QObject, pyqtSignal

class MockPanel:
    """Mock device panel to pass parameter dicts safely across thread boundaries."""
    def __init__(self, tp, pp, sp, fr):
        self.tp = tp
        self.pp = pp
        self.sp = sp
        self.fr = fr
    def get_tracking_params(self): return self.tp
    def get_postprocess_params(self): return self.pp
    def get_scale_params(self): return self.sp
    def get_frame_range(self): return self.fr

class OTRunWorker(QObject):
    """Worker thread for Optical Tweezers RUN batch."""

    progress_pct = pyqtSignal(int, str)
    log_msg = pyqtSignal(str)
    status_update = pyqtSignal(object, str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        batch_controller,
        device_id: str,
        roi_rect: tuple[int, int, int, int],
        panel_data: dict,
    ):
        super().__init__()
        self._batch = batch_controller
        self._device_id = device_id
        self._roi_rect = roi_rect
        self._panel_data = panel_data
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        self._batch.stop()

    def run(self):
        if self._is_cancelled:
            return

        # Redirect BatchController logs temporarily
        old_log = self._batch._log
        self._batch._log = lambda msg: self.log_msg.emit(msg)

        try:
            self.progress_pct.emit(0, "RUN: Starting...")

            def _progress_fn(done: int, total_count: int, filename: str = "", pct: int = 0):
                if self._is_cancelled:
                    return
                if total_count <= 0:
                    total_count = 1
                
                if done > 0 and pct >= 100:
                    batch_frac = done / total_count
                elif done > 0:
                    batch_frac = ((done - 1) + pct / 100.0) / total_count
                else:
                    batch_frac = pct / 100.0 / total_count

                overall = int(100 * batch_frac)
                overall = max(0, min(100, overall))

                label = f"RUN: [{done}/{total_count}]"
                if filename:
                    label += f" {filename} ({pct}%)"
                self.progress_pct.emit(overall, label)

            def _status_fn(path, status):
                self.status_update.emit(path, status)

            mock_panel = MockPanel(
                self._panel_data.get("tracking", {}),
                self._panel_data.get("postprocess", {}),
                self._panel_data.get("scale", {}),
                self._panel_data.get("frame_range", (0, -1))
            )

            self._batch.run_batch(
                device_id=self._device_id,
                device_panel=mock_panel,
                roi_rect=self._roi_rect,
                dataset_set_status_fn=_status_fn,
                progress_fn=_progress_fn,
            )

            if not self._is_cancelled:
                self.progress_pct.emit(100, "RUN: Done")
                self.finished.emit()

        except Exception:
            if not self._is_cancelled:
                self.error.emit(traceback.format_exc())
        finally:
            self._batch._log = old_log
