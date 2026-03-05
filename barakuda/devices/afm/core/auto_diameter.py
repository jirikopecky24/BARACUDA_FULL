"""AFM Auto-Diameter Estimation."""

import logging

logger = logging.getLogger(__name__)

def estimate_diameter_px(
    um_per_px: float,
    mode: str = "rods",
    default_um: float = 0.6
) -> tuple[int, dict]:
    """Estimate the required Cellpose diameter in pixels from the physical scale.

    Parameters
    ----------
    um_per_px : float
        The physical scale of the image (µm per pixel).
    mode : str
        The estimation logic strategy (currently "rods": mapping thickness).
    default_um : float
        The assumed typical thickness of the object measured in micrometers.
        For bacteria short-axis thickness, ~0.6 µm is typical.

    Returns
    -------
    (int, dict)
        The estimated diameter [px] clamped to sensible limits, and the audit trace.
    """
    if um_per_px <= 0.0:
        logger.warning("um_per_px is <= 0. Auto-diameter cannot proceed. Returning 0.")
        return 0, {"status": "UNKNOWN_SCALE"}

    # Base formula: convert the assumed physical width into pixels at this magnification
    diam_float = default_um / um_per_px
    diam_px = round(diam_float)

    # Clamp bounds to prevent absurd outcomes that might hang Cellpose
    LB, UB = 8, 80
    clamped = max(LB, min(UB, diam_px))
    
    if clamped != diam_px:
        logger.debug(f"Auto-diameter calculation ({diam_float:.1f}px) required clamping to {clamped}px")

    audit = {
        "status": "OK",
        "assumed_object_diameter_um": default_um,
        "um_per_px": um_per_px,
        "strategy": mode,
        "raw_diam_px": round(diam_float, 2)
    }

    return clamped, audit
