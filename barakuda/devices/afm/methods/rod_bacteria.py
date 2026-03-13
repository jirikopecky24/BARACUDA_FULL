"""Rod Bacteria method — wraps existing Cellpose + Rod Fit pipeline."""
from __future__ import annotations

from typing import Any

import numpy as np

from barakuda.devices.afm.methods.base import AfmMethodBase


class RodBacteriaMethod(AfmMethodBase):
    """AFM method: Rod Bacteria (Cellpose + Rod Fit).

    This is the default and currently only production method.
    It wraps ``run_afm_v2`` from ``afm_v2_pipeline`` without any
    behavioral changes.
    """

    METHOD_ID = "rod_bacteria"
    DISPLAY_NAME = "Rod Bacteria (Cellpose + Rod Fit)"

    def build_runtime_params(self, raw_params: dict[str, Any]) -> Any:
        """Convert raw AFM panel params into ``AfmV2Params``."""
        from barakuda.devices.afm.core.afm_v2_pipeline import AfmV2Params

        def _f(key: str, default: float) -> float:
            return float(raw_params.get(key, default))

        def _i(key: str, default: int) -> int:
            return int(raw_params.get(key, default))

        def _b(key: str, default: bool) -> bool:
            return bool(raw_params.get(key, default))

        def _s(key: str, default: str) -> str:
            return str(raw_params.get(key, default))

        cp_diameter_px = raw_params.get("cp_diameter_px")
        return AfmV2Params(
            compute_profile=_s("compute_profile", "auto"),
            preview_fast_mode=_b("preview_fast_mode", False),
            preview_downscale=_f("preview_downscale", 0.5),
            invert=_b("invert", False),
            clip_p_low=_f("clip_p_low", 1.0),
            clip_p_high=_f("clip_p_high", 99.0),
            cp_model=_s("cp_model", "cyto3"),
            cp_diameter_mode=_s("cp_diameter_mode", "auto"),
            cp_diameter_px=(int(cp_diameter_px) if cp_diameter_px is not None else None),
            cp_flow_threshold=_f("cp_flow_threshold", 0.4),
            cp_cellprob_threshold=_f("cp_cellprob_threshold", -0.5),
            rods_only=_b("rods_only", True),
            rods_min_major_axis_px=_f("rods_min_major_axis_px", 12.0),
            rods_min_aspect_ratio=_f("rods_min_aspect_ratio", 1.8),
            rods_min_eccentricity=_f("rods_min_eccentricity", 0.65),
            rods_min_area_px=_i("rods_min_area_px", 8),
            ellipse_thickness_px=_i("ellipse_thickness_px", 2),
            ellipse_alpha=_f("ellipse_alpha", 0.6),
        )

    def compute(
        self,
        image: np.ndarray,
        params: Any,
        *,
        um_per_px: float = 0.0,
    ) -> dict:
        """Run the Cellpose V2 rod-fit pipeline.

        Delegates to ``run_afm_v2`` which returns labels, rod_table,
        and an audit dict.
        """
        from barakuda.devices.afm.core.afm_v2_pipeline import (
            AfmV2Params,
            run_afm_v2,
        )

        # params is expected to be an AfmV2Params instance
        if not isinstance(params, AfmV2Params):
            raise TypeError(
                f"Expected AfmV2Params, got {type(params).__name__}"
            )

        return run_afm_v2(image, params, um_per_px=um_per_px)

    def get_default_params(self) -> dict:
        """Return default UI parameter values for Rod Bacteria."""
        return {
            "compute_profile": "auto",
            "preview_fast_mode": False,
            "preview_downscale": 1.0,
            "invert": False,
            "clip_p_low": 1.0,
            "clip_p_high": 99.0,
            "cp_model": "cyto3",
            "cp_diameter_mode": "fixed",
            "cp_diameter_px": 18,
            "cp_flow_threshold": 0.4,
            "cp_cellprob_threshold": 0.3,
            "rods_only": False,
            "rods_min_major_axis_px": 12.0,
            "rods_min_aspect_ratio": 1.8,
            "rods_min_eccentricity": 0.65,
            "rods_min_area_px": 8,
            "ellipse_thickness_px": 1,
            "ellipse_alpha": 0.6,
        }
