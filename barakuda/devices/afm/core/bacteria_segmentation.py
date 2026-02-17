from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import numpy as np


@dataclass(frozen=True)
class AfmBacteriaSegParams:
    # Background flattening (AFM tilt/curvature removal)
    bg_sigma: float = 12.0

    # Denoise
    smooth_sigma: float = 1.0

    # Morphology
    min_area_px: int = 120
    closing_radius_px: int = 2
    hole_area_px: int = 240  # default: 2 * min_area_px

    # Touching objects separation
    separate: bool = True

    # If bacteria are dark instead of bright
    invert: bool = False

    # Deterministic histogram bins for "četnosti"
    area_bins: int = 20


def _normalize01(img: np.ndarray) -> np.ndarray:
    x = np.asarray(img, dtype=np.float32)
    x = x - np.nanmin(x)
    mx = np.nanmax(x)
    if mx > 0:
        x = x / mx
    return x


def segment_bacteria_afm(
    img: np.ndarray,
    params: AfmBacteriaSegParams,
) -> dict[str, Any]:
    """
    Segment rod-like bacteria from AFM image.

    Returns dict with:
      - mask (bool HxW)
      - labels (int HxW, 0=bg)
      - objects (list of dicts: label, area_px, centroid, perimeter, ecc, solidity)
      - summary (counts + area histogram)
      - audit (params + key algorithm steps)
    """
    # Lazy imports (keeps core import light)
    from scipy import ndimage as ndi
    from skimage import exposure, filters, morphology, measure, segmentation

    img01 = _normalize01(img)
    if params.invert:
        img01 = 1.0 - img01

    # --- background flattening (deterministic) ---
    bg = ndi.gaussian_filter(img01, sigma=float(params.bg_sigma))
    flat = img01 - bg
    flat = exposure.rescale_intensity(flat, in_range="image", out_range=(0.0, 1.0))

    # --- denoise ---
    den = ndi.gaussian_filter(flat, sigma=float(params.smooth_sigma))

    # --- threshold ---
    thr = float(filters.threshold_otsu(den))
    mask = den > thr

    # --- morphology (shape-preserving) ---
    min_area = int(params.min_area_px)
    hole_area = int(params.hole_area_px) if int(params.hole_area_px) > 0 else int(2 * min_area)

    mask = morphology.remove_small_objects(mask, min_size=min_area)
    mask = morphology.remove_small_holes(mask, area_threshold=hole_area)
    mask = morphology.closing(mask, morphology.disk(int(params.closing_radius_px)))

    # --- labeling ---
    if bool(params.separate):
        dist = ndi.distance_transform_edt(mask)
        local_max = morphology.local_maxima(dist)  # deterministic
        markers = ndi.label(local_max)[0]
        labels = segmentation.watershed(-dist, markers, mask=mask)
    else:
        labels = measure.label(mask)

    # --- object stats ---
    props = measure.regionprops(labels)
    objects: list[dict[str, Any]] = []
    for p in props:
        objects.append({
            "label": int(p.label),
            "area_px": int(p.area),
            "centroid_x_px": float(p.centroid[1]),
            "centroid_y_px": float(p.centroid[0]),
            "perimeter_px": float(getattr(p, "perimeter", float("nan"))),
            "eccentricity": float(getattr(p, "eccentricity", float("nan"))),
            "solidity": float(getattr(p, "solidity", float("nan"))),
        })

    # --- counts + "četnosti" (area histogram) ---
    areas = np.array([o["area_px"] for o in objects], dtype=np.float64)
    count = int(areas.size)

    # deterministic bins: [min..max] if any objects else dummy
    if count > 0:
        a_min = float(np.min(areas))
        a_max = float(np.max(areas))
        if a_max <= a_min:
            a_max = a_min + 1.0
        hist, edges = np.histogram(areas, bins=int(params.area_bins), range=(a_min, a_max))
        hist = hist.astype(int)
        edges = edges.astype(np.float64)
        bins_out = [{
            "bin_lo": float(edges[i]),
            "bin_hi": float(edges[i + 1]),
            "count": int(hist[i]),
        } for i in range(hist.size)]
    else:
        bins_out = []

    summary = {
        "count_bacteria": count,
        "area_histogram": {
            "bins": bins_out,
            "n_bins": int(params.area_bins),
        },
        "threshold_otsu": thr,
    }

    audit = {
        "method": "AFM_BACTERIA_SEG_V1",
        "params": asdict(params),
        "notes": {
            "flatten": "gaussian subtract + rescale",
            "threshold": "otsu",
            "morphology": "remove_small_objects/holes + closing(disk)",
            "separate": "watershed(distance_transform)" if params.separate else "connected_components",
        },
    }

    return {
        "mask": mask,
        "labels": labels,
        "objects": objects,
        "summary": summary,
        "audit": audit,
    }
