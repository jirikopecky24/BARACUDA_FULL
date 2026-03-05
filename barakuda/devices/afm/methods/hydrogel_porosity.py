"""Hydrogel Porosity method — placeholder stub."""
from __future__ import annotations

from typing import Any

import numpy as np

from barakuda.devices.afm.methods.base import AfmMethodBase


class HydrogelPorosityMethod(AfmMethodBase):
    """AFM method: Hydrogel Porosity (coming soon).

    This is a placeholder for a future method that will analyse
    pore size distribution in hydrogel AFM images.
    """

    METHOD_ID = "hydrogel_porosity"
    DISPLAY_NAME = "Hydrogel Porosity (coming soon)"

    def compute(
        self,
        image: np.ndarray,
        params: Any,
    ) -> dict:
        raise NotImplementedError(
            "Hydrogel Porosity method is not yet implemented."
        )

    def get_default_params(self) -> dict:
        return {}
