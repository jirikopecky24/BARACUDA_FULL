from __future__ import annotations

from typing import List

from barakuda.devices.base import DeviceSpec
from barakuda.devices.optical_tweezers.device import get_device_spec as get_ot_spec
from barakuda.devices.afm.device import get_device_spec as get_afm_spec
from barakuda.devices.acquisition.device import get_device_spec as get_acq_spec


def list_devices() -> List[DeviceSpec]:
    # Add new devices here.
    return [
        get_ot_spec(),
        get_afm_spec(),
        get_acq_spec(),
    ]
