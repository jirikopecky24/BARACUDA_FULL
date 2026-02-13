from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QCheckBox, QLabel
)

from barakuda.shell.batch_controller import PreviewResult


def _fmt(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float):
        return f"{x:.6g}"
    return str(x)


class PreviewGateReportDialog(QDialog):
    def __init__(self, results: list[PreviewResult], report_path: Path | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview Gate Report")
        self.resize(980, 520)

        self._all_results = list(results)
        self._report_path = report_path

        self.only_fail = QCheckBox("Only failures")
        self.only_fail.stateChanged.connect(self._rebuild)

        self.lbl = QLabel("")
        self.lbl.setStyleSheet("color: #666;")

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "File", "PASS", "Status", "Message",
            "Frame", "x", "y", "Quality", "Peak", "Method"
        ])
        self.table.setSortingEnabled(True)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)

        self.btn_copy_json = QPushButton("Copy selected row as JSON")
        self.btn_copy_json.clicked.connect(self._copy_selected_json)

        self.btn_show_path = QPushButton("Show preview_report.json path")
        self.btn_show_path.clicked.connect(self._show_path)

        top = QHBoxLayout()
        top.addWidget(self.only_fail)
        top.addStretch(1)
        top.addWidget(self.lbl)

        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_show_path)
        bottom.addWidget(self.btn_copy_json)
        bottom.addStretch(1)
        bottom.addWidget(btn_close)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addLayout(bottom)

        self._rebuild()

    def _filtered(self) -> list[PreviewResult]:
        if self.only_fail.isChecked():
            return [r for r in self._all_results if not r.ok]
        return list(self._all_results)

    def _rebuild(self) -> None:
        rows = self._filtered()
        n_all = len(self._all_results)
        n_fail = sum(1 for r in self._all_results if not r.ok)
        self.lbl.setText(f"Items: {n_all} | Fail: {n_fail}")

        self.table.setRowCount(0)
        self.table.setSortingEnabled(False)

        for r in rows:
            d = dict(r.details or {})
            p = Path(r.path)
            row = self.table.rowCount()
            self.table.insertRow(row)

            def item(text: str) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                return it

            pass_txt = "PASS" if r.ok else "FAIL"

            self.table.setItem(row, 0, item(p.name))
            self.table.setItem(row, 1, item(pass_txt))
            self.table.setItem(row, 2, item(_fmt(r.status)))
            self.table.setItem(row, 3, item(_fmt(r.message)))

            self.table.setItem(row, 4, item(_fmt(d.get("preview_frame_index"))))
            self.table.setItem(row, 5, item(_fmt(d.get("x_px"))))
            self.table.setItem(row, 6, item(_fmt(d.get("y_px"))))
            self.table.setItem(row, 7, item(_fmt(d.get("quality"))))
            self.table.setItem(row, 8, item(_fmt(d.get("peak"))))
            self.table.setItem(row, 9, item(_fmt(d.get("method"))))

            # red-ish highlight for FAIL
            if not r.ok:
                for c in range(self.table.columnCount()):
                    it = self.table.item(row, c)
                    if it is not None:
                        it.setBackground(Qt.GlobalColor.lightGray)

            # store full JSON in UserRole for clipboard copy
            payload = {
                "path": r.path,
                "ok": r.ok,
                "status": r.status,
                "message": r.message,
                "details": r.details,
            }
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, payload)

        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

    def _copy_selected_json(self) -> None:
        sel = self.table.selectedItems()
        if not sel:
            return
        # row of the first selected item
        row = sel[0].row()
        it = self.table.item(row, 0)
        if it is None:
            return
        payload = it.data(Qt.ItemDataRole.UserRole)
        if payload is None:
            return

        import json
        txt = json.dumps(payload, indent=2, ensure_ascii=False)
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(txt)

    def _show_path(self) -> None:
        if self._report_path is None:
            self.lbl.setText("preview_report.json: not available")
            return
        self.lbl.setText(str(self._report_path))
