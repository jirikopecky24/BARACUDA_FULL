from __future__ import annotations

import numpy as np
from typing import Any

from barakuda.core.qc_flags import QcParams, compute_track_loss_flags


def compute_qc(
    traj: dict[str, Any],
    camera_meta: dict[str, Any],
    params: dict[str, Any]
) -> dict[str, Any]:
    """
    Validate camera metadata and evaluate track-loss flags.
    
    Args:
        traj: Trajectory dictionary with 'x_px', 'y_px', 'quality'.
        camera_meta: Camera metadata JSON dict.
        params: UI QC params (qc_enabled, q_min, jump_max_px).
        
    Returns:
        dict: qc.json-compatible output with {"flags": {...}, "warnings": [...]}
    """
    
    warnings = []
    
    # 1. Validate mandatory camera_meta keys
    mandatory_keys = ["fps", "roi_w_px", "roi_h_px"]
    missing_mandatory = [k for k in mandatory_keys if k not in camera_meta or camera_meta[k] is None]
    if missing_mandatory:
        raise ValueError(f"Camera metadata missing required keys: {missing_mandatory}")
        
    for opt_key in ["exposure_ms", "gain", "timestamp_start_iso", "timestamp_end_iso", "binning"]:
        if opt_key not in camera_meta or camera_meta[opt_key] is None:
            warnings.append({
                "code": f"{opt_key.upper()}_MISSING",
                "message": f"{opt_key} not provided",
                "details": None
            })
            
    fps = float(camera_meta["fps"])
    
    # 2. Heuristic warnings (if expected_f0 is known from camera_meta)
    expected_f0 = camera_meta.get("expected_f0", None)
    if expected_f0 is not None and expected_f0 > 0:
        if fps < 10.0 * expected_f0:
            warnings.append({
                "code": "LOW_FPS",
                "message": "fps < 10*expected_f0",
                "details": {"fps": fps, "expected_f0": expected_f0}
            })
            
        exposure_ms = camera_meta.get("exposure_ms")
        if exposure_ms is not None:
            max_exp = 0.2 * (1.0 / expected_f0) * 1000.0
            if float(exposure_ms) > max_exp:
                warnings.append({
                    "code": "HIGH_EXPOSURE",
                    "message": "exposure_ms too large vs period",
                    "details": {"exposure_ms": exposure_ms, "max_allowed": max_exp}
                })

    # 3. Track-loss QC
    x = np.asarray(traj["x_px"], dtype=np.float64)
    y = np.asarray(traj["y_px"], dtype=np.float64)
    
    # Track quality (1.0 if not from rs, or from peak)
    if "quality" in traj:
        q = np.asarray(traj["quality"], dtype=np.float64)
    else:
        q = np.ones_like(x)

    n_frames = len(x)
    
    if bool(params.get("qc_enabled", True)):
        q_min = float(params.get("q_min", 0.0))
        jump_max = float(params.get("jump_max_px", 50.0))
        qc_p = QcParams(q_min=q_min, jump_max_px=jump_max)
        lost, reason = compute_track_loss_flags(x, y, q, qc_p)
    else:
        lost = np.zeros_like(x, dtype=bool)
        reason = np.full(n_frames, "", dtype="<U16")

    lost_n = int(np.sum(lost))
    lost_frac = float(lost_n) / float(n_frames) if n_frames > 0 else 0.0
    
    flags = {
        "track_loss_frames": lost_n,
        "track_loss_fraction": lost_frac,
    }

    return {
        "flags": flags,
        "warnings": warnings,
        # We also return mask so orchestrator can add it to traj_pp
        "_lost_mask": lost,
        "_lost_reason": reason
    }
