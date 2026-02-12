from __future__ import annotations
from datetime import datetime
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit


class LogPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._text = QTextEdit()
        self._text.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._text)

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._text.append(f"[{ts}] {message}")
