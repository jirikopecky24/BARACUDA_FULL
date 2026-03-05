from __future__ import annotations
import traceback

from PyQt6.QtCore import QObject, pyqtSignal


class AfmRunWorker(QObject):
    """Worker thread for AFM RUN batch.

    Wraps BatchController.run_afm_batch() so the heavy compute
    runs off the UI thread.  Emits the same signal interface as
    AfmPreviewWorker (progress_pct, finished, error).
    """

    progress_pct = pyqtSignal(int, str)   # (percent, message)
    finished = pyqtSignal()               # batch completed OK
    error = pyqtSignal(str)               # traceback string

    def __init__(
        self,
        batch_controller,
        file_paths: list,
        roi_rect: tuple[int, int, int, int],
        afm_params: dict,
        dataset_set_status_fn,
    ):
        super().__init__()
        self._batch = batch_controller
        self._file_paths = file_paths
        self._roi_rect = roi_rect
        self._afm_params = afm_params
        self._dataset_set_status_fn = dataset_set_status_fn
        self._is_cancelled = False

    def cancel(self):
        """Soft cancel (cooperative)."""
        self._is_cancelled = True

    # ------------------------------------------------------------------ #
    def run(self):
        if self._is_cancelled:
            return

        try:
            self.progress_pct.emit(0, "RUN: Loading...")
            self.progress_pct.emit(5, "RUN: Preprocessing...")
            self.progress_pct.emit(15, "RUN: Initializing Cellpose...")
            self.progress_pct.emit(20, "RUN: Inference starting...")

            # Track highest emitted value so we never emit backward
            self._last_pct = 20

            def _progress_fn(done: int, total_count: int, filename: str = "", pct: int = 0):
                """Translate batch per-file progress into the 20-95 range.

                The 0-20 range is covered by the phased emissions above.
                The 95-100 range is reserved for the final "Done" emission.
                The QTimer in the UI thread fills the 20-79 gap with smooth
                increments while the worker is silent during inference.
                """
                if self._is_cancelled:
                    return

                if total_count <= 0:
                    total_count = 1

                # Compute overall batch fraction (0.0 – 1.0)
                if done > 0 and pct >= 100:
                    batch_frac = done / total_count
                elif done > 0:
                    batch_frac = ((done - 1) + pct / 100.0) / total_count
                else:
                    batch_frac = 0.0

                # Map to 20-95 range
                overall = 20 + int(75 * batch_frac)
                overall = max(self._last_pct, min(95, overall))
                self._last_pct = overall

                label = f"RUN: [{done}/{total_count}]"
                if filename:
                    label += f" {filename}"
                self.progress_pct.emit(overall, label)

            self._batch.run_afm_batch(
                file_paths=self._file_paths,
                roi_rect=self._roi_rect,
                afm_params=self._afm_params,
                dataset_set_status_fn=self._dataset_set_status_fn,
                progress_fn=_progress_fn,
            )

            if not self._is_cancelled:
                self.progress_pct.emit(100, "RUN: Done")
                self.finished.emit()

        except Exception:
            if not self._is_cancelled:
                self.error.emit(traceback.format_exc())
