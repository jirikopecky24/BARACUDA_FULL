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
    
    half = (roi_size - 1) / 2.0
    rx = int(round(cx - half))
    ry = int(round(cy - half))
    
    rx = max(0, min(rx, w - roi_size))
    ry = max(0, min(ry, h - roi_size))
    
    return Roi(x=rx, y=ry, w=roi_size, h=roi_size)

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
        det_ref = track_particle(
            frame, 
            roi=roi_try, 
            method=TrackingMethod.RADIAL_SYMMETRY, 
            auto_polarity=True,
            blur_sigma=1.2,
            radial_grad_threshold=2.0
        )
        if det_ref.quality >= 0.1:
            # Here det_ref coordinates are locally inside roi_try. We will unify this in Step 3.
            # But the requirement asks us to use the helper.
            # We skip using the helper for the result of refine() until Step 2/3.
            roi2 = roi_follow_center(frame.shape, roi_try, det_ref.x_px, det_ref.y_px)
            return (roi2.x, roi2.y, roi2.w, roi2.h)

    # Fallback
    roi_size_try = max(16, base_size)
    roi_size_try = min(roi_size_try, w, h)
    roi_size_try |= 1
    
    fx, fy, fw, fh = auto_detect_particle(frame, roi_size=roi_size_try)
    fallback_roi = Roi(x=fx, y=fy, w=fw, h=fh)
    det_fall = track_particle(
        frame,
        roi=fallback_roi,
        method=TrackingMethod.RADIAL_SYMMETRY,
        auto_polarity=True,
        blur_sigma=1.2,
        radial_grad_threshold=2.0
    )
    roi_fin = roi_follow_center(frame.shape, fallback_roi, det_fall.x_px, det_fall.y_px)
    return (roi_fin.x, roi_fin.y, roi_fin.w, roi_fin.h)
