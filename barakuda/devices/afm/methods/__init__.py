from __future__ import annotations

from barakuda.devices.afm.methods.base import AfmMethodBase
from barakuda.devices.afm.methods.hydrogel_porosity import HydrogelPorosityMethod
from barakuda.devices.afm.methods.rod_bacteria import RodBacteriaMethod


_METHODS: dict[str, AfmMethodBase] = {
    RodBacteriaMethod.METHOD_ID: RodBacteriaMethod(),
    HydrogelPorosityMethod.METHOD_ID: HydrogelPorosityMethod(),
}


def get_afm_method(method_id: str | None) -> AfmMethodBase:
    key = str(method_id or RodBacteriaMethod.METHOD_ID).strip().lower()
    return _METHODS.get(key, _METHODS[RodBacteriaMethod.METHOD_ID])


def list_afm_methods() -> list[AfmMethodBase]:
    return list(_METHODS.values())
