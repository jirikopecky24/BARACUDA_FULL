from __future__ import annotations

import numpy as np
from typing import Any

from barakuda.devices.optical_tweezers.strategies.base import CalibrationStrategy


class DragConstantVelocityStrategy(CalibrationStrategy):
    """
    LEGACY drag calibration strategy (NOT stage-aware).

    This implementation historically used a time-only heuristic:
    - steady-state taken as the median of the second half of the trajectory
    - assumes trap center at 0

    Current (NOW) stage-aware DRAG analysis lives in `drag/` and uses:
    - stage trace timing + onset detection
    - baseline / steady windows on video time axis
    - measured stage speed via stage metadata

    Keep this strategy for backwards compatibility and OT shadow/preview workflows.
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

        # 3. Compute stiffness or viscosity
        stage_speed_m_s = abs(stage_speed_um_s) * 1e-6
        r_m = bead_radius_um * 1e-6
        offset_m = abs(float(offset_um)) * 1e-6
        
        qc_warnings = []
        if stage_speed_m_s < 1e-12:
            qc_warnings.append("Stage speed is ~0, poor drag calibration")
        if offset_m < 1e-12:
            qc_warnings.append("Offset is ~0, unreliable drag calibration")
            
        temp_c = float(params.get("temperature_c", 25.0))
        T_k = temp_c + 273.15
        K_B = 1.380649e-23
        kbt = K_B * T_k
        
        provided_k_pn_um = params.get("kappa_pN_um", None)
        if provided_k_pn_um is not None and float(provided_k_pn_um) > 0:
            k_n_m = float(provided_k_pn_um) * 1e-6
            drag_force_n = k_n_m * offset_m
            
            if stage_speed_m_s > 0 and r_m > 0:
                viscosity_pa_s_calc = drag_force_n / (6.0 * np.pi * r_m * stage_speed_m_s)
            else:
                viscosity_pa_s_calc = 0.0
                qc_warnings.append("Cannot compute eta (v or r is 0)")
            kappa_pn_um = float(provided_k_pn_um)
        else:
            viscosity_pa_s_calc = viscosity_pa_s
            gamma_ns_m = 6.0 * np.pi * viscosity_pa_s_calc * r_m
            drag_force_n = gamma_ns_m * stage_speed_m_s
            
            if offset_m > 0:
                k_n_m = drag_force_n / offset_m
            else:
                k_n_m = 0.0
                qc_warnings.append("Cannot compute kappa (offset is 0)")
            kappa_pn_um = k_n_m * 1e6
            
        gamma_ns_m = 6.0 * np.pi * viscosity_pa_s_calc * r_m
        D_m2_s = kbt / gamma_ns_m if gamma_ns_m > 0 else 0.0
        
        derived_data = {
            "fc_hz": float("nan"),
            "k_pN_um": float(kappa_pn_um),
            "eta_Pa_s": float(viscosity_pa_s_calc),
            "gamma_Ns_m": float(gamma_ns_m),
            "D_um2_s": float(D_m2_s * 1e12),
            "temperature_c": float(temp_c),
            "bead_diameter_um": float(bead_radius_um * 2.0)
        }

        derived_dict = {
            "status": "OK",
            axis: derived_data,
            "mean": derived_data
        }

        # 4. Results Dict
        result_dict = {
            "axis": axis,
            "stage_speed_um_s": stage_speed_um_s,
            "viscosity_pa_s": viscosity_pa_s_calc,
            "bead_radius_um": bead_radius_um,
            "gamma_n_s_per_m": gamma_ns_m,
            "offset_um": float(offset_um),
            "drag_force_pn": drag_force_n * 1e12,
            "calibration": {
                f"kappa_{axis}_pN_um": kappa_pn_um,
                f"kappa_{axis}_pN_nm": kappa_pn_um * 1e-3,
            },
            "derived": derived_dict
        }
        if qc_warnings:
            result_dict["qc_warnings"] = qc_warnings

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
