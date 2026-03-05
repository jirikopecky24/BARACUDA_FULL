from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CalibrationStrategy(ABC):
    """
    Base class for Optical Tweezers calibration strategies.
    
    All strategies must be pure functions of their inputs, with no shared state
    and no side effects (like writing to the filesystem). Plot data should be
    returned in the artifacts dictionary for the exporter to render.
    """

    # Strategy name used in UI and ot_summary.json (e.g., "PSD_Lorentzian")
    name: str = ""

    # Prefix prepended to all artifact filenames (e.g., "psd_")
    export_prefix: str = ""

    @abstractmethod
    def compute(
        self,
        traj: dict[str, Any],
        camera_meta: dict[str, Any],
        params: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Args:
            traj: Dictionary containing 1D arrays of trajectory data, e.g.:
                  {"t_s": [...], "x_corr_px": [...], "y_corr_px": [...], ...}
            camera_meta: Dictionary of camera metadata (fps, expected_f0, etc).
            params: Dictionary of strategy-specific parameters from the UI.

        Returns:
            (result_dict, artifacts_dict)
            - result_dict: scalar values and metrics to embed in ot_summary.json
            - artifacts_dict: plot-ready arrays/data to be rendered by exporter
        """
        pass
