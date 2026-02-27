from __future__ import annotations

import numpy as np
from typing import Any

from barakuda.core.ot_physics import (
    DragParams,
    compute_dragging_from_offset,
    stokes_gamma_n_s_per_m,
)
from barakuda.devices.optical_tweezers.strategies.base import CalibrationStrategy


class DragConstantVelocityStrategy(CalibrationStrategy):
    """
    Drag force calibration using constant-velocity stage pulling.
    
    Detects the steady-state segment by taking the median displacement 
    of the second half of the trajectory. Assumes the trap center is at 0.
    """

    name = "Drag_ConstantVelocity"
    export_prefix = "drag_"

    def compute(
        self,
        traj: dict[str, Any],
        camera_meta: dict[str, Any],
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        # 1. Inputs
        try:
            axis = str(params.get("drag_axis", "x")).lower()
            stage_speed_um_s = float(params["stage_speed_um_s"])
            viscosity_pa_s = float(params.get("viscosity_pa_s", 1e-3))
            bead_radius_um = float(params.get("bead_diameter_um", 1.0)) / 2.0
        except KeyError as e:
            raise KeyError(f"Drag strategy missing required parameter: {e}")

        col = f"{axis}_corr_um"
        if col not in traj:
            raise ValueError(f"Drag strategy requires '{col}' (scale must be set).")
        
        t_s = np.asarray(traj["t_s"], dtype=np.float64)
        pos_um = np.asarray(traj[col], dtype=np.float64)
        
        valid = np.isfinite(t_s) & np.isfinite(pos_um)
        t_val = t_s[valid]
        pos_val = pos_um[valid]

        if pos_val.size < 10:
            raise ValueError("Not enough valid points for drag calibration.")

        # 2. Detect steady-state segment
        # Use the latter half of the trajectory, assuming it has reached steady state
        half_idx = pos_val.size // 2
        steady_segment = pos_val[half_idx:]
        t_steady = t_val[half_idx:]
        
        # Offset is the median of the steady state segment
        offset_um = np.median(steady_segment)

        # 3. Compute stiffness
        drag_p = DragParams(
            stage_speed_um_s=stage_speed_um_s,
            axis=axis,
            viscosity_pa_s=viscosity_pa_s,
            bead_radius_um=bead_radius_um
        )
        res = compute_dragging_from_offset(offset_um, drag_p)

        # 4. Results Dict
        result_dict = {
            "axis": axis,
            "stage_speed_um_s": stage_speed_um_s,
            "viscosity_pa_s": viscosity_pa_s,
            "bead_radius_um": bead_radius_um,
            "gamma_n_s_per_m": stokes_gamma_n_s_per_m(viscosity_pa_s, bead_radius_um),
            "offset_um": float(offset_um),
            "drag_force_pn": res.drag_force_n * 1e12,
            "calibration": {
                f"kappa_{axis}_pN_um": res.kappa_pn_per_um,
                f"kappa_{axis}_pN_nm": res.kappa_pn_per_um * 1e-3,
            }
        }

        # 5. Artifacts Dict
        # We return the raw data and the steady-state highlight for rendering
        artifacts_dict = {
            f"drag_response_{axis}": {
                "t_s": t_val,
                "pos_um": pos_val,
                "steady_t_start": float(t_steady[0]),
                "steady_t_end": float(t_steady[-1]),
                "steady_offset_um": float(offset_um)
            },
            "k_drag_summary": result_dict # Exporter can dump this to a specific JSON if requested, or just rely on ot_summary
        }

        return result_dict, artifacts_dict
