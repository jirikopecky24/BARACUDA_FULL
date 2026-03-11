from __future__ import annotations
import traceback
from PyQt6.QtCore import QObject, pyqtSignal

class MockPanel:
    """Mock device panel to pass parameter dicts safely across thread boundaries."""
    def __init__(
        self,
        dataset_params: dict,
        fallback_tp: dict,
        fallback_pp: dict,
        fallback_sp: dict,
        fallback_fr: tuple,
        fallback_output_root: str,
    ):
        self._dataset_params = dataset_params
        self.fallback_tp = fallback_tp
        self.fallback_pp = fallback_pp
        self.fallback_sp = fallback_sp
        self.fallback_fr = fallback_fr
        self.fallback_output_root = fallback_output_root
        
        self._current_path = ""
        
    def set_current_path(self, path: str):
        self._current_path = path
        
    def _get_params_for_path(self):
        pms = self._dataset_params.get(self._current_path)
        if pms is not None:
            return pms
        return {}

    def get_tracking_params(self): 
        p = self._get_params_for_path()
        return p.get("tracking") if p.get("tracking") is not None else self.fallback_tp
        
    def get_postprocess_params(self): 
        p = self._get_params_for_path()
        return p.get("postprocess") if p.get("postprocess") is not None else self.fallback_pp
        
    def get_scale_params(self): 
        p = self._get_params_for_path()
        return p.get("scale") if p.get("scale") is not None else self.fallback_sp
        
    def get_frame_range(self): 
        p = self._get_params_for_path()
        return p.get("frame_range") if p.get("frame_range") is not None else self.fallback_fr

    def get_run_output_root(self):
        return self.fallback_output_root

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
        checked_paths: list,
        roi_rect: tuple[int, int, int, int],
        panel_data: dict,
        dataset_params: dict,
        dataset_set_status_fn=None,  # accepted but bypassed since we use signal
    ):
        super().__init__()
        self._batch = batch_controller
        self._checked_paths = checked_paths
        self._roi_rect = roi_rect
        self._panel_data = panel_data
        self._dataset_params = dataset_params
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
                self._dataset_params,
                self._panel_data.get("tracking", {}),
                self._panel_data.get("postprocess", {}),
                self._panel_data.get("scale", {}),
                self._panel_data.get("frame_range", (0, -1)),
                str(self._panel_data.get("run_output_root", "")),
            )

            self._batch.run_batch(
                device_id="optical_tweezers",
                device_panel=mock_panel,
                roi_rect=self._roi_rect,
                dataset_set_status_fn=_status_fn,
                progress_fn=_progress_fn,
                checked_paths=self._checked_paths,
            )

            if not self._is_cancelled:
                self.progress_pct.emit(100, "RUN: Done")
                self.finished.emit()

        except Exception:
            if not self._is_cancelled:
                self.error.emit(traceback.format_exc())
        finally:
            self._batch._log = old_log
