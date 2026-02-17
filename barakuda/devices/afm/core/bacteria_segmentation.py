from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import numpy as np


@dataclass(frozen=True)
class AfmBacteriaSegParams:
    bg_sigma: float = 12.0
    smooth_sigma: float = 1.0
    min_area_px: int = 120
    closing_radius_px: int = 2
    hole_area_px: int = 240
    separate: bool = True
    invert: bool = False
    area_bins: int = 20

    # Marker-based watershed (LoG seeds)
    log_sigma: float = 2.0
    peak_min_distance_px: int = 6
    low_mask_factor: float = 0.65   # mask = den > (otsu * factor)
    max_markers: int = 5000


def _normalize01(img: np.ndarray) -> np.ndarray:
    x = np.asarray(img, dtype=np.float32)
    x = x - np.nanmin(x)
    mx = np.nanmax(x)
    if mx > 0:
        x = x / mx
    return x


def segment_bacteria_afm(img: np.ndarray, params: AfmBacteriaSegParams) -> dict[str, Any]:
    from scipy import ndimage as ndi
    from skimage import exposure, filters, morphology, measure, segmentation, feature

    img01 = _normalize01(img)
    if params.invert:
        img01 = 1.0 - img01

    # --- background flattening ---
    bg = ndi.gaussian_filter(img01, sigma=float(params.bg_sigma))
    flat = img01 - bg
    flat = exposure.rescale_intensity(flat, in_range="image", out_range=(0.0, 1.0))

    # --- denoise ---
    den = ndi.gaussian_filter(flat, sigma=float(params.smooth_sigma))

    # ------------------------------------------------------------
    # Marker-based watershed (LoG seeds)  ✅ správně pro dense field
    # ------------------------------------------------------------

    # base mask: not "den > otsu" (too aggressive), but a lower mask to constrain watershed
    thr_otsu = float(filters.threshold_otsu(den))
    thr_low = float(thr_otsu * float(params.low_mask_factor))
    base_mask = den > thr_low

    # clean base mask slightly (avoid speckles)
    base_mask = morphology.remove_small_objects(base_mask, min_size=max(20, int(params.min_area_px // 6)))
    base_mask = morphology.remove_small_holes(base_mask, area_threshold=max(30, int(params.min_area_px // 6)))

    # LoG response: peaks ~ centers of rod-like objects / local maxima structures
    # Use LoG on den (already flattened), then find local maxima as markers.
    log_resp = -ndi.gaussian_laplace(den, sigma=float(params.log_sigma))
    # normalize response for stability
    log_resp = (log_resp - np.nanmin(log_resp)) / (np.nanmax(log_resp) - np.nanmin(log_resp) + 1e-12)

    # peak picking only inside base mask
    peaks = feature.peak_local_max(
        log_resp,
        min_distance=int(params.peak_min_distance_px),
        threshold_abs=float(np.percentile(log_resp[base_mask], 70)) if np.any(base_mask) else 0.0,
        labels=base_mask.astype(np.uint8),
        num_peaks=int(params.max_markers),
    )

    markers = np.zeros_like(den, dtype=np.int32)
    for i, (r, c) in enumerate(peaks, start=1):
        markers[r, c] = i

    # If no markers found, fall back to a very conservative connected-components mask
    if markers.max() < 2:
        # conservative fallback: higher threshold + morphology
        mask = den > thr_otsu
        mask = morphology.remove_small_objects(mask, min_size=int(params.min_area_px))
        mask = morphology.remove_small_holes(mask, area_threshold=int(params.hole_area_px) if int(params.hole_area_px) > 0 else int(2 * params.min_area_px))
        mask = morphology.closing(mask, morphology.disk(int(params.closing_radius_px)))
        labels = measure.label(mask)
    else:
        # Watershed on gradient (best practice: use gradient to follow ridges/boundaries)
        grad = filters.sobel(den)
        labels = segmentation.watershed(grad, markers, mask=base_mask)

        # Post-filter: remove tiny fragments & relabel
        # (watershed sometimes creates tiny regions)
        labels = morphology.remove_small_objects(labels, min_size=int(params.min_area_px))
        labels = measure.label(labels > 0)

        # Reconstruct final mask from labels
        mask = labels > 0

    # Optional closing to ensure "solid" bacteria shapes
    if int(params.closing_radius_px) > 0:
        mask = morphology.closing(mask, morphology.disk(int(params.closing_radius_px)))
        labels = measure.label(mask)

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

    areas = np.array([o["area_px"] for o in objects], dtype=np.float64)
    count = int(areas.size)
    coverage = float(mask.mean()) if mask.size else 0.0

    bins_out: list[dict[str, Any]] = []
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

    summary = {
        "count_bacteria": count,
        "coverage_mask": coverage,
        "threshold_otsu": thr_otsu,
        "threshold_low": thr_low,
        "markers_found": int(markers.max()),
        "area_frequencies": {"n_bins": int(params.area_bins), "bins": bins_out},
    }

    audit = {
        "method": "AFM_BACTERIA_SEG_V2_MARKER_WATERSHED",
        "params": asdict(params),
        "notes": {
            "flatten": "gaussian subtract + rescale",
            "masking": "low threshold (otsu * factor)",
            "markers": "LoG seeds on intensity",
            "segmentation": "watershed on sobel gradient",
        },
    }

    return {"mask": mask, "labels": labels, "objects": objects, "summary": summary, "audit": audit}
