from __future__ import annotations

import numpy as np
from typing import Any

from barakuda.core.ot_physics import (
    fit_lorentzian_psd,
    CalibrationParams,
    compute_calibration_from_equipartition_and_fc,
)
from barakuda.devices.optical_tweezers.pipeline.derived_newtonian import (
    compute_newtonian_derived,
    compute_mean_derived
)
from barakuda.devices.optical_tweezers.strategies.base import CalibrationStrategy


def compute_psd_procfft(x: np.ndarray, fs_hz: float, segments: int) -> tuple[np.ndarray, np.ndarray]:
    """
    MATLAB-like PSD estimator: splits trace into `segments`, computes periodogram
    for each, and averages them.
    """
    N = x.size
    lenps = N // segments
    if lenps == 0:
        return np.array([]), np.array([])
        
    P_accum = np.zeros(lenps // 2 + 1)
    
    for i in range(segments):
        xseg = x[i*lenps : (i+1)*lenps]
        xseg = xseg - np.mean(xseg)
        X = np.fft.rfft(xseg)
        P = np.abs(X)**2
        P_accum += P
        
    P_avg = P_accum / segments
    
    psd = P_avg / (fs_hz * lenps)
    # double interior bins for 1-sided PSD
    psd[1:-1] *= 2.0
    if lenps % 2 != 0:
        psd[-1] *= 2.0
        
    f = np.fft.rfftfreq(lenps, d=1.0/fs_hz)
    return f, psd


class PsdProcFftStrategy(CalibrationStrategy):
    """
    Brownian motion calibration using a MATLAB-equivalent periodogram averaging (procfft)
    and Lorentzian fit.
    """

    name = "PSD_ProcFFT"
    export_prefix = "procfft_"

    def compute(
        self,
        traj: dict[str, Any],
        camera_meta: dict[str, Any],
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        for k in ["x_corr_um", "y_corr_um"]:
            if k not in traj:
                return {"status": "SKIPPED", "reason": f"Missing '{k}' (no scale)"}, {}
        
        x_um = np.asarray(traj["x_corr_um"], dtype=np.float64)
        y_um = np.asarray(traj["y_corr_um"], dtype=np.float64)
        
        valid = np.isfinite(x_um) & np.isfinite(y_um)
        x_val = x_um[valid]
        y_val = y_um[valid]

        segments = int(params.get("segments", 50))
        if x_val.size < segments * 2:  # extremely short
            lenps = x_val.size // segments
            return {"status": "SKIPPED", "reason": f"Too few valid points for {segments} segments (lenps={lenps})", "n_valid": x_val.size}, {}

        lenps = x_val.size // segments
        if lenps < 256:
            return {"status": "SKIPPED", "reason": f"lenps={lenps} < 256 (not enough points per segment)", "n_valid": x_val.size}, {}

        fps = float(camera_meta.get("fps", 1.0))

        fx, pxx = compute_psd_procfft(x_val, fps, segments=segments)
        fy, pyy = compute_psd_procfft(y_val, fps, segments=segments)

        # Fit Lorentzian (ignoring first few bins by setting fmin_hz)
        fit_x = fit_lorentzian_psd(fx, pxx, fmin_hz=1.0)
        fit_y = fit_lorentzian_psd(fy, pyy, fmin_hz=1.0)

        # Calibration
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

        result_dict = {
            "status": "COMPLETED",
            "procfft_params": {
                "segments": segments,
                "lenps": lenps,
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
