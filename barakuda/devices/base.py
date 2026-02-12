from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from PyQt6.QtWidgets import QWidget


class DevicePanel(Protocol):
    """UI panel for a device/modality.

    The shell treats the panel as an opaque QWidget, but expects the panel to expose
    a minimal set of signals/methods used by the currently implemented device.
    """
    def as_widget(self) -> QWidget: ...


@dataclass(frozen=True)
class DeviceSpec:
    device_id: str
    display_name: str
    create_panel: Callable[[], QWidget]
