import cv2
import math
import numpy as np
from typing import Tuple
from barakuda.core.tracking import track_particle, TrackingMethod, Roi, roi_follow_center

def centered_roi(cx: float, cy: float, roi_size: int, frame_shape: Tuple[int, ...]) -> Roi:
    """Helper for exact ROI center math, clamping, and odd size enforcing."""
    h = int(frame_shape[0])
    w = int(frame_shape[1])
    
    roi_size = int(max(16, roi_size))
    roi_size = min(roi_size, w, h)
    roi_size |= 1  # enforce odd
    
    # We want cx to be at exactly rx + (roi_size-1)/2.0
    # rx = cx - (roi_size-1)/2.0
    half_w = (roi_size - 1) / 2.0
    half_h = (roi_size - 1) / 2.0
    rx = int(round(float(cx) - half_w))
    ry = int(round(float(cy) - half_h))
    
    rx = max(0, min(rx, w - roi_size))
    ry = max(0, min(ry, h - roi_size))
    
    return Roi(x=rx, y=ry, w=roi_size, h=roi_size)

def refine(frame: np.ndarray, roi: Roi) -> Tuple[Roi, object]:
    """Helper to detect within ROI and recenter if det is good."""
    det = track_particle(
        frame,
        roi=roi,
        method=TrackingMethod.RADIAL_SYMMETRY,
        auto_polarity=True,
        blur_sigma=1.2,
        radial_grad_threshold=2.0
    )
    if det.quality < 0.1:
        return roi, det
        
    # track_particle currently returns global coordinates because it adds ox, oy internally.
    # self-check guard just in case it returned local:
    cx, cy = det.x_px, det.y_px
    if cx < 0 or (cx <= roi.w and cy <= roi.h and roi.x > 0 and roi.y > 0):
        # A tiny heuristic in case we missed a local-coord edge case (though code looks global)
        # If it's suspiciously local (e.g. x < roi.w despite ROI being far from 0)
        # Actually tracking.py line 367 states: x = float(ox) + float(cx) which means it's GLOBAL.
        # So we leave cx, cy as is.
        pass
        
    roi2 = centered_roi(cx, cy, roi.w, frame.shape)
    
    # Optional debug print for local validation (can be removed later)
    # print(f"refine: cx={cx:.2f}, cy={cy:.2f}, new_rx={roi2.x}, new_ry={roi2.y}")
    
    return roi2, det

def auto_detect_particle(frame: np.ndarray, roi_size: int = 50) -> Tuple[int, int, int, int]:
    """
    Finds the most prominent dark or bright spot and returns a centered ROI.
    Supports polarity auto (dark+bright) by scoring both via TopHat and BlackHat morphology.
    """
    if frame.ndim == 3:
        if frame.shape[-1] >= 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame[..., 0]
    else:
        gray = frame.copy()
    
    # Slight blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    
    # Use morphological operations to highlight both bright and dark spots
    # A 15x15 ellipse kernel is roughly the size of a typical bead
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    tophat = cv2.morphologyEx(blurred, cv2.MORPH_TOPHAT, kernel)    # bright spots
    blackhat = cv2.morphologyEx(blurred, cv2.MORPH_BLACKHAT, kernel)  # dark spots
    
    # Combine both responses
    combined = cv2.addWeighted(tophat, 1.0, blackhat, 1.0, 0)
    
    # Find global maximum response
    _, _, _, max_loc = cv2.minMaxLoc(combined)
    cx, cy = max_loc
    
    roi = centered_roi(cx, cy, roi_size, gray.shape)
    return (roi.x, roi.y, roi.w, roi.h)

def auto_roi_rs(frame: np.ndarray, um_per_px: float, bead_diameter_um: float, margin_factor: float = 1.8) -> Tuple[int, int, int, int]:
    """
    Finds bead center using RS and returns ROI sized by bead_diameter_um.
    Falls back to morphological scoring (auto_detect_particle) if RS fails.
    """
    if um_per_px <= 0 or bead_diameter_um <= 0:
        return auto_detect_particle(frame, roi_size=50)

    h, w = frame.shape[:2]

    bead_radius_px = (bead_diameter_um / 2.0) / um_per_px
    roi_half = math.ceil(margin_factor * bead_radius_px)
    base_size = int(roi_half * 2)

    for attempt in range(3):
        det = track_particle(
            frame,
            roi=None, 
            method=TrackingMethod.RADIAL_SYMMETRY, 
            auto_polarity=True,
            blur_sigma=1.2,
            radial_grad_threshold=2.0
        )
        
        if det.quality < 0.1:
            break

        roi_size_try = int(base_size * (1.0 + 0.25 * attempt))
        roi_size_try = max(16, roi_size_try)
        roi_size_try = min(roi_size_try, w, h)
        roi_size_try |= 1

        roi_try = centered_roi(det.x_px, det.y_px, roi_size_try, frame.shape)
        
        # Pass 1
        roi1, det1 = refine(frame, roi_try)
        if det1.quality < 0.1:
            continue
            
        # Pass 2
        roi2, det2 = refine(frame, roi1)
        if det2.quality >= 0.1:
            return (roi2.x, roi2.y, roi2.w, roi2.h)

    # Fallback
    roi_size_try = max(16, base_size)
    roi_size_try = min(roi_size_try, w, h)
    roi_size_try |= 1
    
    fx, fy, fw, fh = auto_detect_particle(frame, roi_size=roi_size_try)
    fallback_roi = Roi(x=fx, y=fy, w=fw, h=fh)
    roi_fin, _ = refine(frame, fallback_roi)
    return (roi_fin.x, roi_fin.y, roi_fin.w, roi_fin.h)
