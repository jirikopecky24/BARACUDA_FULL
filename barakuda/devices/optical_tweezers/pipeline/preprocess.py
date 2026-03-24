from __future__ import annotations

import numpy as np
from typing import Any
import scipy.signal

def preprocess_trajectory(
    traj: dict[str, Any],
    fps: float,
    drift_mode: str,
    params: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Apply preprocessing (drift correction) to the trajectory.
    
    Args:
        traj: Output from tracking containing 't_s', 'x_px', 'y_px', 'x_um', 'y_um'.
        fps: Camera frame rate in Hz.
        drift_mode: One of "none", "lowpass_subtract", "detrend_linear".
        params: Additional UI parameters for drift correction.
        
    Returns:
        (traj_pp, audit_dict)
        traj_pp: New trajectory dictionary with 'x_corr_px', 'y_corr_px', etc.
        audit_dict: Record for ot_summary.json under 'preprocess.drift'
    """
    
    # We will compute corrected arrays and add them to a copy of traj
    traj_pp = dict(traj)
    
    # We always need to output x_corr_px, y_corr_px.
    # Optional x_corr_um, y_corr_um will be added if x_um, y_um exist and are not NaN
    n_frames = len(traj["x_px"])
    x_px = np.asarray(traj["x_px"], dtype=np.float64)
    y_px = np.asarray(traj["y_px"], dtype=np.float64)
    
    has_um = "x_um" in traj and "y_um" in traj
    if has_um:
        x_um = np.asarray(traj["x_um"], dtype=np.float64)
        y_um = np.asarray(traj["y_um"], dtype=np.float64)
    else:
        x_um = np.full(n_frames, np.nan)
        y_um = np.full(n_frames, np.nan)
        
    mode = str(drift_mode).lower().strip()
    
    audit_dict = {
        "mode": "none"
    }

    # Identify finite segments for filtering/detrending
    # Missing frames/failed tracking must not blow up the filter
    valid = np.isfinite(x_px) & np.isfinite(y_px)
    
    drift_x_px = np.zeros_like(x_px)
    drift_y_px = np.zeros_like(y_px)
    drift_x_um = np.zeros_like(x_um)
    drift_y_um = np.zeros_like(y_um)

    if mode == "none" or not np.any(valid):
        # Passthrough
        audit_dict["mode"] = "none"
        
    elif mode == "lowpass_subtract":
        cutoff_hz = float(params.get("cutoff_hz", 3.0))
        order = int(params.get("order", 4))
        
        # We need a continuous array for filtfilt. Fill NaNs to avoid propagating them.
        def _fill_nans_nearest(arr):
            out = arr.copy()
            mask = np.isnan(out)
            if not np.any(mask):
                return out
            # forward fill
            idx = np.arange(len(out))
            idx[mask] = 0
            np.maximum.accumulate(idx, out=idx)
            out = out[idx]
            # backward fill (if leading NaNs)
            mask2 = np.isnan(out)
            if np.any(mask2):
                idx = np.arange(len(out))[::-1]
                idx[mask2] = len(out) - 1
                np.minimum.accumulate(idx, out=idx)
                out = out[idx[::-1]]
            if np.any(np.isnan(out)):
                out = np.nan_to_num(out)
            return out
            
        x_filled = _fill_nans_nearest(x_px)
        y_filled = _fill_nans_nearest(y_px)
        x_um_filled = _fill_nans_nearest(x_um) if has_um else x_um
        y_um_filled = _fill_nans_nearest(y_um) if has_um else y_um
        
        nyq = 0.5 * fps
        normalized_cutoff = cutoff_hz / nyq
        
        if normalized_cutoff >= 1.0 or normalized_cutoff <= 0.0:
            # Cannot filter if cutoff is outside valid range -> passthrough or error?
            # Graceful degrade to passthrough
            pass
        else:
            b, a = scipy.signal.butter(order, normalized_cutoff, btype='low')
            
            # Use filtfilt for zero phase
            drift_x_px = scipy.signal.filtfilt(b, a, x_filled)
            drift_y_px = scipy.signal.filtfilt(b, a, y_filled)
            if has_um:
                drift_x_um = scipy.signal.filtfilt(b, a, x_um_filled)
                drift_y_um = scipy.signal.filtfilt(b, a, y_um_filled)
                
        audit_dict.update({
            "mode": "lowpass_subtract",
            "cutoff_hz": float(cutoff_hz),
            "filter_type": "butterworth",
            "order": int(order),
            "fs_hz": float(fps),
            "method": "filtfilt"
        })
        
    elif mode == "detrend_linear":
        t_src = traj.get("t_s")
        exec_mode = str(params.get("execution_mode", "interactive")).strip().lower()
        if t_src is None:
            if exec_mode == "batch":
                raise ValueError("Batch mode requires trajectory 't_s' from validated timestamps.")
            t_s = np.arange(n_frames) / fps
            audit_dict["time_axis_warning"] = "Missing t_s -> fallback to uniform fps axis in interactive mode."
            audit_dict["time_axis_source"] = "fps_fallback"
        else:
            t_s = np.asarray(t_src, dtype=np.float64)
            if t_s.shape[0] != n_frames:
                if exec_mode == "batch":
                    raise ValueError("Batch mode requires time axis length equal to trajectory length.")
                t_s = np.arange(n_frames) / fps
                audit_dict["time_axis_warning"] = "Invalid t_s length -> fallback to uniform fps axis in interactive mode."
                audit_dict["time_axis_source"] = "fps_fallback"
            else:
                audit_dict["time_axis_source"] = str(params.get("time_axis_source", "trajectory_t_s"))
        
        # Fit only on valid data
        t_v = t_s[valid]
        if len(t_v) > 1:
            cx = np.polyfit(t_v, x_px[valid], 1)
            cy = np.polyfit(t_v, y_px[valid], 1)
            drift_x_px = np.polyval(cx, t_s)
            drift_y_px = np.polyval(cy, t_s)
            
            if has_um:
                cx_u = np.polyfit(t_v, x_um[valid], 1)
                cy_u = np.polyfit(t_v, y_um[valid], 1)
                drift_x_um = np.polyval(cx_u, t_s)
                drift_y_um = np.polyval(cy_u, t_s)
                
        audit_dict.update({
            "mode": "detrend_linear",
            "degree": 1
        })
    else:
        raise ValueError(f"Unknown drift correction mode: {mode}")

    traj_pp["x_corr_px"] = x_px - drift_x_px
    traj_pp["y_corr_px"] = y_px - drift_y_px
    
    if has_um:
        traj_pp["x_corr_um"] = x_um - drift_x_um
        traj_pp["y_corr_um"] = y_um - drift_y_um
    else:
        traj_pp["x_corr_um"] = np.full(n_frames, np.nan)
        traj_pp["y_corr_um"] = np.full(n_frames, np.nan)

    return traj_pp, {"drift": audit_dict}
