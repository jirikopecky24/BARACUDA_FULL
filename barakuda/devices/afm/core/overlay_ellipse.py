"""Ellipse-only overlay renderer from rod_table.

Single source of truth for overlay drawing — no inline drawing
in compute_afm_preview or run_afm_batch is allowed.
"""
from __future__ import annotations

import numpy as np
from skimage import draw, morphology


def render_ellipse_overlay(
    base_gray_or_rgb: np.ndarray,
    rod_table: dict,
    thickness_px: int = 2,
    ellipse_alpha: float = 0.6,
) -> np.ndarray:
    """Draw yellow ellipse perimeters for each row in rod_table.

    Parameters
    ----------
    base_gray_or_rgb : ndarray
        2-D grayscale or 3-D RGB image used as background.
    rod_table : dict
        Dict-of-arrays with keys: centroid_x, centroid_y,
        major_axis_px, minor_axis_px, orientation_rad.
    thickness_px : int
        Stroke thickness in pixels (>= 1).
    ellipse_alpha : float
        Opacity of the yellow ellipse strokes [0.0 .. 1.0].
        1.0 = fully opaque (legacy), 0.6 = recommended Nature-grade.

    Returns
    -------
    uint8 RGB overlay image.
    """
    # Ensure RGB uint8 base
    if base_gray_or_rgb.ndim == 2:
        base = np.stack([base_gray_or_rgb] * 3, axis=-1)
    elif base_gray_or_rgb.ndim == 3 and base_gray_or_rgb.shape[2] >= 3:
        base = base_gray_or_rgb[..., :3].copy()
    else:
        base = np.stack([base_gray_or_rgb[..., 0]] * 3, axis=-1)

    if base.dtype != np.uint8:
        bmin = float(np.nanmin(base))
        bmax = float(np.nanmax(base))
        if bmax > bmin:
            base = ((base - bmin) / (bmax - bmin) * 255.0).astype(np.uint8)
        else:
            base = np.zeros_like(base, dtype=np.uint8)

    overlay = base.copy()
    h, w = overlay.shape[:2]

    # Nothing to draw if rod_table is empty or missing keys
    if not isinstance(rod_table, dict) or "label" not in rod_table:
        return overlay

    n = len(rod_table["label"])
    if n == 0:
        return overlay

    # Build ellipse perimeter mask
    ell = np.zeros((h, w), dtype=bool)

    for k in range(n):
        cy = float(rod_table["centroid_y"][k])
        cx = float(rod_table["centroid_x"][k])
        maj = float(rod_table["major_axis_px"][k])
        mino = float(rod_table["minor_axis_px"][k])
        ang = float(rod_table["orientation_rad"][k])

        r_radius = max(1, int(round(maj / 2.0)))
        c_radius = max(1, int(round(mino / 2.0)))

        try:
            pr, pc = draw.ellipse_perimeter(
                int(round(cy)),
                int(round(cx)),
                r_radius,
                c_radius,
                orientation=-ang,   # image coord convention
                shape=(h, w),
            )
            ell[pr, pc] = True
        except Exception:
            # Skip degenerate ellipses (e.g. radii too small)
            continue

    # Apply thickness
    if thickness_px > 1:
        ell = morphology.binary_dilation(ell, morphology.disk(thickness_px - 1))

    # Alpha-blend yellow onto base
    alpha = float(np.clip(ellipse_alpha, 0.0, 1.0))
    yellow = np.array([255, 255, 0], dtype=np.float32)
    overlay[ell] = (alpha * yellow + (1.0 - alpha) * overlay[ell].astype(np.float32)).astype(np.uint8)

    return overlay
