from __future__ import annotations

from typing import Any

from barakuda.devices.optical_tweezers.strategies.base import CalibrationStrategy


class PiezoOscillationStrategy(CalibrationStrategy):
    """
    Piezo oscillation calibration strategy (stub for future implementation).
    """

    name = "Piezo_Oscillation"
    export_prefix = "piezo_"

    def compute(
        self,
        traj: dict[str, Any],
        camera_meta: dict[str, Any],
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raise NotImplementedError("Piezo oscillation calibration coming soon")
