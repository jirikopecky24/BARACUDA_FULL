import cv2
import numpy as np
from typing import Tuple

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
    
    h, w = gray.shape
    roi_w = roi_size
    roi_h = roi_size
    
    # Clamp bounds to image size
    rx = max(0, min(cx - roi_w // 2, w - roi_w))
    ry = max(0, min(cy - roi_h // 2, h - roi_h))
    
    return (rx, ry, roi_w, roi_h)
