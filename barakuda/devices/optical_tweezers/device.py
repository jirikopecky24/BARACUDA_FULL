from __future__ import annotations

from barakuda.devices.base import DeviceSpec
from barakuda.devices.optical_tweezers.ui.panel import PipelinePanel


def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="optical_tweezers",
        display_name="Optical Tweezers",
        create_panel=lambda: PipelinePanel(),
    )
