from __future__ import annotations

from typing import List

from barakuda.devices.base import DeviceSpec
from barakuda.devices.optical_tweezers.device import get_device_spec as get_ot_spec
from barakuda.devices.afm.device import get_device_spec as get_afm_spec

try:
    from barakuda.devices.acquisition.device import get_device_spec as get_acq_spec
except Exception:
    get_acq_spec = None

def list_devices() -> List[DeviceSpec]:
    # Add new devices here.
    devices = [
        get_ot_spec(),
        get_afm_spec(),
    ]
    if get_acq_spec is not None:
        devices.append(get_acq_spec())
    return devices
