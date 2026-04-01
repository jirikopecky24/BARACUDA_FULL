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
from barakuda.core.truth_resolvers import resolve_bead_parameters_for_run
from barakuda.devices.optical_tweezers.pipeline.derived_newtonian import (
    compute_newtonian_derived,
    compute_mean_derived
)
from barakuda.devices.optical_tweezers.strategies.base import CalibrationStrategy
from barakuda.devices.optical_tweezers.strategies.time_resampling import resample_to_uniform_timebase


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
        t_s = np.asarray(traj.get("t_s", []), dtype=np.float64)
        if t_s.size != x_um.size:
            return {"status": "SKIPPED", "reason": "Missing/invalid t_s for timestamp-based PSD."}, {}

        try:
            rs = resample_to_uniform_timebase(t_s=t_s, x=x_um, y=y_um)
        except Exception as e:  # noqa: BLE001
            return {"status": "SKIPPED", "reason": f"Timestamp resampling failed: {e}"}, {}
        x_val = np.asarray(rs["x_uniform"], dtype=np.float64)
        y_val = np.asarray(rs["y_uniform"], dtype=np.float64)

        if x_val.size < 256:
            return {"status": "SKIPPED", "reason": "Not enough valid points (<256)", "n_valid": x_val.size}, {}

        nperseg = 1024 if x_val.size >= 1024 else x_val.size
        noverlap = nperseg // 2
        fs_uniform = float(rs["fs_uniform_hz"])

        # 2. Compute PSD
        psd_p = PsdParams(fs_hz=fs_uniform, nperseg=nperseg, noverlap=noverlap, detrend=True, window="hann")
        fx, pxx = compute_psd_welch(x_val, psd_p)
        fy, pyy = compute_psd_welch(y_val, psd_p)

        # 3. Fit Lorentzian
        fit_x = fit_lorentzian_psd(fx, pxx, fmin_hz=1.0)
        fit_y = fit_lorentzian_psd(fy, pyy, fmin_hz=1.0)

        # 4. Calibration (equipartition + fc)
        temp_c = float(params.get("temperature_c", 25.0))
        bead_res = resolve_bead_parameters_for_run(
            bead_diameter_um=params.get("bead_diameter_um"),
            bead_radius_um=params.get("bead_radius_um"),
            bead_source=str(params.get("bead_source") or "strategy_params"),
            allow_fallback=False,
        )
        bead_d = float(bead_res.bead_diameter_um)
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

        # 5. Derived Newtonian physics
        um_per_px = float(camera_meta.get("um_per_px", 0.0))
        derived_dict = {}
        qc_warnings = []
        if um_per_px <= 0:
            derived_dict = {"status": "SKIPPED", "reason": "um_per_px missing or <= 0"}
            qc_warnings.append("um_per_px missing or valid scale not set -> derived outputs skipped")
        else:
            try:
                derived_x = compute_newtonian_derived(fit_x["fc_hz"], x_val, temp_c, bead_d)
                derived_y = compute_newtonian_derived(fit_y["fc_hz"], y_val, temp_c, bead_d)
                derived_mean = compute_mean_derived(derived_x, derived_y, method="median")
                derived_dict = {
                    "status": "OK",
                    "x": derived_x,
                    "y": derived_y,
                    "mean": derived_mean
                }
            except Exception as e:
                derived_dict = {"status": "SKIPPED", "reason": f"Derived calculation failed: {e}"}
                qc_warnings.append(f"Derived calculation failed: {e}")

        # 6. Prepare Results Dict (Audit)
        result_dict = {
            "status": "COMPLETED",
            "welch_params": {
                "nperseg": nperseg,
                "noverlap": noverlap,
                "window": "hann",
                "detrend": True
            },
            "time_processing": {
                "input_time_axis_source": str(camera_meta.get("time_axis", {}).get("time_axis_source", "unknown")),
                "resampling": {
                    "enabled": True,
                    "fs_uniform_hz": fs_uniform,
                    "n_in": int(rs["n_in"]),
                    "n_valid": int(rs["n_valid"]),
                    "n_out": int(rs["n_out"]),
                    "dt_stats": rs["dt_stats"],
                },
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
            },
            "derived": derived_dict,
        }
        if qc_warnings:
            result_dict["qc_warnings"] = qc_warnings

        # 7. Prepare Artifacts Dict
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
