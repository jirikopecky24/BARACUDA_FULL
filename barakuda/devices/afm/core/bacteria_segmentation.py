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
    low_mask_factor: float = 0.45   # mask = den > (otsu * factor)
    max_markers: int = 5000
    
    # Watershed detect-all
    dist_sigma: float = 1.0            # vyhlazení distance mapy
    seed_percentile: float = 75.0      # procentil pro seed threshold (nižší => víc seedů)
    peak_min_distance: int = 6         # min vzdálenost seedů (nižší => víc objektů)
    watershed_compactness: float = 0.0 # 0 = klasika, >0 trochu “zpevní” tvary
        # Contour-first segmentation (edge -> close -> fill -> contours)
    use_contours: bool = True          # default: použijeme nový přístup
    edge_sigma: float = 1.2            # rozmazání před hranami
    canny_low: float = 0.05            # dolní práh (0..1)
    canny_high: float = 0.20           # horní práh (0..1)
    edge_dilate_px: int = 1            # ztloustnutí hran (pomáhá uzavřít)
    close_radius_px: int = 2           # closing pro uzavření smyček
    fill_holes_area_px: int = 300      # vyplnit malé díry
    min_perimeter_px: int = 60         # vyhodit malé rozpadlé kontury
    min_eccentricity: float = 0.70     # tyčinky mají vyšší excentricitu
    min_solidity: float = 0.50         # vyhodit hodně “děravé” tvary


def _normalize01(img: np.ndarray) -> np.ndarray:
    x = np.asarray(img, dtype=np.float32)
    x = x - np.nanmin(x)
    mx = np.nanmax(x)
    if mx > 0:
        x = x / mx
    return x


    return x


def segment_bacteria_watershed_afm(img: np.ndarray, params: AfmBacteriaSegParams):
    """
    Detect-all watershed segmentation for dense bacterial fields.

    Returns:
      labels (int32): instance labels 1..N
      mask (bool): labels>0
      debug (dict)
    """
    import numpy as np
    from scipy import ndimage as ndi
    from skimage import filters, exposure, morphology, measure, segmentation, feature

    # --- ensure grayscale 2D ---
    # --- ensure grayscale 2D ---
    if img.ndim == 3:
        img = img[..., 0]

    img01 = _normalize01(img)
    if params.invert:
        img01 = 1.0 - img01

    # 1) Background subtraction (flatten illumination / height drift)
    bg = ndi.gaussian_filter(img01, sigma=float(params.bg_sigma))
    flat = img01 - bg
    flat = exposure.rescale_intensity(flat, in_range="image", out_range=(0.0, 1.0))

    # 2) Gentle denoise (not too much; bacteria edges matter)
    den = ndi.gaussian_filter(flat, sigma=float(params.smooth_sigma))

    # 3) Threshold to get "bacteria mask"
    thr = filters.threshold_otsu(den)
    thr_low = thr * float(params.low_mask_factor)
    base_mask = den > thr_low

    # cleanup: remove speckles + fill small holes
    base_mask = morphology.remove_small_objects(base_mask, min_size=int(params.min_area_px))
    base_mask = morphology.remove_small_holes(base_mask, area_threshold=int(params.hole_area_px))

    # 4) Distance transform inside mask
    dist = ndi.distance_transform_edt(base_mask)
    if float(params.dist_sigma) > 0:
        dist = ndi.gaussian_filter(dist, sigma=float(params.dist_sigma))

    # 5) Seeds (markers) from distance peaks
    # Use percentile threshold to control number of seeds
    dist_vals = dist[base_mask]
    if dist_vals.size == 0:
        out = np.zeros_like(dist, dtype=np.int32)
        return out, (out > 0), {"reason": "empty_mask"}

    seed_thr = np.percentile(dist_vals, float(params.seed_percentile))
    peaks = feature.peak_local_max(
        dist,
        min_distance=int(params.peak_min_distance),
        threshold_abs=float(seed_thr),
        labels=base_mask,
        exclude_border=False,
    )

    markers = np.zeros_like(dist, dtype=np.int32)
    for i, (r, c) in enumerate(peaks, start=1):
        markers[r, c] = i

    n_markers = int(markers.max())
    if n_markers < 2:
        # fallback: at least label connected components
        labels = measure.label(base_mask)
        labels = morphology.remove_small_objects(labels, min_size=int(params.min_area_px))
        labels = measure.label(labels, background=0)
        mask = labels > 0
        debug = {
            "thr_otsu": float(thr),
            "thr_low": float(thr_low),
            "mask_coverage": float(base_mask.mean()),
            "n_markers": n_markers,
            "mode": "cc_fallback",
        }
        return labels.astype(np.int32), mask, debug

    # 6) Watershed on negative distance (basins grow from peaks)
    labels = segmentation.watershed(
        -dist,
        markers,
        mask=base_mask,
        compactness=float(getattr(params, "watershed_compactness", 0.0)),
    )

    # 7) Remove small instances and reindex 1..N
    if labels.max() > 1:
        labels = morphology.remove_small_objects(labels, min_size=int(params.min_area_px))
    labels = measure.label(labels, background=0)

    mask = labels > 0
    debug = {
        "thr_otsu": float(thr),
        "thr_low": float(thr_low),
        "mask_coverage": float(base_mask.mean()),
        "n_markers": int(np.max(markers)),
        "count": int(labels.max()),
        "mode": "watershed",
    }
    debug["n_markers"] = int(markers.max()) if "markers" in locals() else 0
    debug["labels_max"] = int(labels.max()) if labels is not None else 0
    
    return labels.astype(np.int32), mask, debug


def segment_bacteria_afm(img: np.ndarray, params: AfmBacteriaSegParams) -> dict[str, Any]:
    # Default = detect-all watershed (best for dense bacterial carpet)
    labels, mask, dbg = segment_bacteria_watershed_afm(img, params)

    # Prefer contour-first for dense bacterial fields (better UX: closed contours)
    if getattr(params, "use_contours", False):
        labels, mask, dbg = segment_bacteria_contours_afm(img, params)
        # dál ať běží stejný export/props jako doposud
        # (jen si do summary přidej dbg)
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
        threshold_abs=float(np.percentile(log_resp[base_mask], 85)) if np.any(base_mask) else 0.0,
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
        # 1) Watershed vrací "instance labels" (každý objekt má své číslo)
        grad = filters.sobel(den)
        labels = segmentation.watershed(grad, markers, mask=base_mask)

        # 2) Odstraníme malé oblasti, ale POZOR:
        #    remove_small_objects umí pracovat i s int label mapou.
        labels = morphology.remove_small_objects(labels, min_size=int(params.min_area_px))

        # 3) Reindex – přečísluje labely na 1..N (zůstává instance segmentation)
        labels = measure.label(labels, background=0)

        # 4) Maska je jen derivát (True/False), ale labels si necháváme!
        mask = labels > 0

        # !!! DŮLEŽITÉ !!!
        # Closing tady neděláme, protože by spojoval blízké bakterie do jedné.

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
        "debug": dbg,
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
def segment_bacteria_contours_afm(img: np.ndarray, params: AfmBacteriaSegParams):
    """
    Contour-first segmentation:
    1) normalize + background subtract + denoise
    2) Canny edges
    3) dilate + closing (make loops)
    4) fill holes -> binary mask
    5) label + filter by shape (area/perimeter/eccentricity/solidity)
    Returns: labels (int), mask (bool), debug dict
    """
    from scipy import ndimage as ndi
    from skimage import exposure, filters, morphology, measure, feature

    # ensure grayscale (2D)
    if img.ndim == 3:
        img = img[..., 0].astype(np.float32) * 0.299 + img[..., 1].astype(np.float32) * 0.587 + img[..., 2].astype(np.float32) * 0.114

    img01 = _normalize01(img)
    if params.invert:
        img01 = 1.0 - img01

    # background flatten (stejně jako dřív)
    bg = ndi.gaussian_filter(img01, sigma=float(params.bg_sigma))
    flat = img01 - bg
    flat = exposure.rescale_intensity(flat, in_range="image", out_range=(0.0, 1.0))

    # denoise
    den = ndi.gaussian_filter(flat, sigma=float(params.edge_sigma))

    # edges
    edges = feature.canny(
        den,
        sigma=0.0,  # už jsme rozmazali přes edge_sigma
        low_threshold=float(params.canny_low),
        high_threshold=float(params.canny_high),
    )

    # make edges thicker + close gaps => more closed loops
    if int(params.edge_dilate_px) > 0:
        edges = morphology.binary_dilation(edges, morphology.disk(int(params.edge_dilate_px)))

    if int(params.close_radius_px) > 0:
        edges = morphology.binary_closing(edges, morphology.disk(int(params.close_radius_px)))

    # ---- build candidate mask without "fill everything" risk ----
    # 1) Instead of binary_fill_holes (can fill whole ROI), we create a thin band and then fill only small holes.
    # Start from edges, then a gentle closing to make local loops.
    cand = edges.copy()

    # Optional: a bit more closing for local continuity (already applied above, so keep small)
    # cand = morphology.binary_closing(cand, morphology.disk(1))

    # 2) Convert edge-net into regions by dilation + erosion (a controlled "thickening")
    # This avoids creating a single giant closed boundary that would fill everything.
    cand = morphology.binary_dilation(cand, morphology.disk(1))
    cand = morphology.binary_erosion(cand, morphology.disk(1))

    # 3) Remove speckles
    cand = morphology.remove_small_objects(cand, min_size=int(params.min_area_px // 3))

    # 4) Fill only small holes INSIDE regions (bounded by area threshold)
    filled = morphology.remove_small_holes(cand, area_threshold=int(params.fill_holes_area_px))

    # 5) Safety guard: if mask covers too much, it's unusable (likely full-fill situation)
    filled_cov = float(filled.mean())
    if filled_cov > 0.60:
        # too much area -> edges are too dense; return empty and let caller/fallback handle it
        out = np.zeros_like(img01, dtype=np.int32)
        mask = out > 0
        debug = {
            "edges_coverage": float(edges.mean()),
            "filled_coverage": filled_cov,
            "kept_objects": 0,
            "guard_triggered": True,
        }
        return out, mask, debug

    # label objects
    labels = measure.label(filled)

    # shape filtering
    keep = np.zeros(labels.max() + 1, dtype=bool)
    props = measure.regionprops(labels)

    for p in props:
        area = float(p.area)
        perim = float(p.perimeter) if hasattr(p, "perimeter") else 0.0
        ecc = float(getattr(p, "eccentricity", 0.0))
        sol = float(getattr(p, "solidity", 0.0))

        if area < float(params.min_area_px):
            continue
        if perim < float(params.min_perimeter_px):
            continue
        if ecc < float(params.min_eccentricity):
            continue
        if sol < float(params.min_solidity):
            continue

        keep[p.label] = True

    # build filtered labels
    out = np.zeros_like(labels, dtype=np.int32)
    new_id = 0
    for lab in range(1, labels.max() + 1):
        if keep[lab]:
            new_id += 1
            out[labels == lab] = new_id

    mask = out > 0

    debug = {
        "edges_coverage": float(edges.mean()),
        "filled_coverage": float(filled.mean()),
        "kept_objects": int(new_id),
    }
    return out, mask, debug

