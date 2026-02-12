from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from barakuda.devices.base import DeviceSpec


class AfmPlaceholderPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("AFM (placeholder)")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "AFM modul zatím není implementovaný.\n\n"
            "Architektura už ho podporuje: sem přijde AFM panel + pipeline kroky."
        ))
        layout.addStretch(1)


def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="afm",
        display_name="AFM",
        create_panel=lambda: AfmPlaceholderPanel(),
    )
