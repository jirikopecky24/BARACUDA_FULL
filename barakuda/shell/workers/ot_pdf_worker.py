from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal


class OTPdfWorker(QObject):
    """Background worker that generates the OT batch summary PDF.

    Runs in a dedicated QThread so that matplotlib's C-extension rendering
    (which holds the Python GIL for many seconds) never starves the Qt
    main-thread event loop and causes a "Not Responding" freeze.
    """

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, summary: dict) -> None:
        super().__init__()
        self._summary = dict(summary)

    def run(self) -> None:
        try:
            from barakuda.core.ot_report import export_ot_batch_pdf

            pdf_path = Path(self._summary["_pdf_path"])
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            report_summary = {k: v for k, v in self._summary.items() if k != "_pdf_path"}
            export_ot_batch_pdf(pdf_path, report_summary)
            self.finished.emit()
        except Exception:
            self.error.emit(traceback.format_exc())
