from __future__ import annotations

from barakuda.devices.base import DeviceSpec
from barakuda.devices.acquisition.ui.panel import AcquisitionPanel


def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="acquisition",
        display_name="Acquisition (Basler)",
        create_panel=lambda: AcquisitionPanel(),
    )
