from __future__ import annotations

from barakuda.devices.base import DeviceSpec
from barakuda.devices.afm.ui.panel import AfmPipelinePanel


def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="afm",
        display_name="AFM",
        create_panel=lambda: AfmPipelinePanel(),
    )
