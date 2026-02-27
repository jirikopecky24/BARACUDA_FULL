from __future__ import annotations

import numpy as np
from typing import Any

from barakuda.core.ot_physics import (
    PsdParams,
    compute_psd_welch,
    fit_lorentzian_psd,
    CalibrationParams,
    compute_calibration_from_equipartition_and_fc,
)
from barakuda.devices.optical_tweezers.strategies.base import CalibrationStrategy


class PsdWelchStrategy(CalibrationStrategy):
    """
    Brownian motion calibration using Welch PSD + Lorentzian fit.
    
    Fixed deterministic Welch parameters: Hann window, nperseg=1024 (min 256), noverlap=nperseg//2.
    """

    name = "PSD_Welch"
    export_prefix = "welch_"

    def compute(
        self,
        traj: dict[str, Any],
        camera_meta: dict[str, Any],
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        # 1. Check inputs
        for k in ["x_corr_um", "y_corr_um"]:
            if k not in traj:
                return {"status": "SKIPPED", "reason": f"Missing '{k}' (no scale)"}, {}
        
        x_um = np.asarray(traj["x_corr_um"], dtype=np.float64)
        y_um = np.asarray(traj["y_corr_um"], dtype=np.float64)
        
        # Valid data
        valid = np.isfinite(x_um) & np.isfinite(y_um)
        x_val = x_um[valid]
        y_val = y_um[valid]

        if x_val.size < 256:
            return {"status": "SKIPPED", "reason": "Not enough valid points (<256)", "n_valid": x_val.size}, {}

        nperseg = 1024 if x_val.size >= 1024 else x_val.size
        noverlap = nperseg // 2
        fps = float(camera_meta.get("fps", 1.0))

        # 2. Compute PSD
        psd_p = PsdParams(fs_hz=fps, nperseg=nperseg, noverlap=noverlap, detrend=True, window="hann")
        fx, pxx = compute_psd_welch(x_val, psd_p)
        fy, pyy = compute_psd_welch(y_val, psd_p)

        # 3. Fit Lorentzian
        fit_x = fit_lorentzian_psd(fx, pxx, fmin_hz=1.0)
        fit_y = fit_lorentzian_psd(fy, pyy, fmin_hz=1.0)

        # 4. Calibration (equipartition + fc)
        temp_c = float(params.get("temperature_c", 25.0))
        bead_d = float(params.get("bead_diameter_um", 1.0))
        visc = float(params.get("viscosity_pa_s", 0.001))

        cal_p = CalibrationParams(
            temperature_c=temp_c,
            bead_diameter_um=bead_d,
            viscosity_pa_s_override=visc
        )
        
        x_centered = x_val - np.mean(x_val)
        y_centered = y_val - np.mean(y_val)

        cal_res = compute_calibration_from_equipartition_and_fc(
            x_centered,
            y_centered,
            fit_x["fc_hz"],
            fit_y["fc_hz"],
            cal_p
        )

        # 5. Prepare Results Dict (Audit)
        result_dict = {
            "status": "COMPLETED",
            "welch_params": {
                "nperseg": nperseg,
                "noverlap": noverlap,
                "window": "hann",
                "detrend": True
            },
            "fit_model": "lorentzian",
            "fit_domain": "linear",
            "fc_x_hz": fit_x["fc_hz"],
            "fc_y_hz": fit_y["fc_hz"],
            "rmse_x": fit_x["rmse"],
            "rmse_y": fit_y["rmse"],
            "calibration": {
                "kappa_x_pN_nm": cal_res.kappa_x_pn_per_um * 1e-3,
                "kappa_x_pN_um": cal_res.kappa_x_pn_per_um,
                "kappa_y_pN_um": cal_res.kappa_y_pn_per_um,
                "eta_mean_pa_s": cal_res.eta_mean_pa_s,
                "temperature_k": cal_res.temperature_k,
                "bead_radius_um": cal_res.bead_radius_um,
                "var_x_um2": cal_res.var_x_um2,
                "var_y_um2": cal_res.var_y_um2,
            }
        }

        # 6. Prepare Artifacts Dict
        def lorentzian_curve(f, fc, a, b):
            return a / (fc**2 + f**2) + b

        curve_x = lorentzian_curve(fx, fit_x["fc_hz"], fit_x["A"], fit_x["B"])
        curve_y = lorentzian_curve(fy, fit_y["fc_hz"], fit_y["A"], fit_y["B"])

        artifacts_dict = {
            "psd_x": {
                "freq_hz": fx,
                "psd": pxx,
                "fit_curve": curve_x,
                "fit_params": fit_x
            },
            "psd_y": {
                "freq_hz": fy,
                "psd": pyy,
                "fit_curve": curve_y,
                "fit_params": fit_y
            }
        }

        return result_dict, artifacts_dict
