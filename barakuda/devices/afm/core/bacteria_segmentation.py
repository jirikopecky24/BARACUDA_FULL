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
    height_aware: bool = True
    invert: bool = False
    save_overlay: bool = True
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

    # Audit-stable edge-map export (SORA-style outlines)
    clahe_clip: float = 2.0           # CLAHE clip limit (unitless)
    clahe_tile: int = 8               # CLAHE tile grid size (NxN)
    nlm_strength: float = 12.0        # Non-local means strength (OpenCV-like h in 0..255 scale)
    edge_canny_sigma: float = 1.2     # Canny sigma (Gaussian before edges)
    edge_canny_low: float = 0.10      # Canny low threshold (0..1)
    edge_canny_high: float = 0.30     # Canny high threshold (0..1)
    edge_link_radius_px: int = 1      # Morphological closing radius to link broken edges
    edge_min_fragment_px: int = 10    # Remove edge fragments shorter than this (px on skeleton)
    edge_thickness_px: int = 1        # Dilation radius after skeletonization (1 => ~2-3 px thickness)

    # Outline-only smoothing (visualization, in px). Improves symmetry / reduces jagged contours.
    # 0 = off
    outline_smoothing_radius_px: int = 2

    # Outline rendering mode (audit-ready)
    outline_mode: str = "inclusive"  # "strict" | "inclusive"

    # Inclusive outline: detect extra edges from intensity, but ONLY in a ring around the mask
    outline_ring_radius_px: int = 2          # ring half-width in px
    outline_edge_sigma: float = 1.2          # Gaussian sigma for Canny (px)
    outline_canny_low: float = 0.10          # 0..1
    outline_canny_high: float = 0.30         # 0..1


    # Rod-only mode (keep only long rods for downstream fitting)
    rods_only: bool = False
    rods_min_major_axis_px: float = 18.0
    rods_min_aspect_ratio: float = 2.5
    rods_min_eccentricity: float = 0.85

def _normalize01(img: np.ndarray) -> np.ndarray:
    x = np.asarray(img, dtype=np.float32)
    x = x - np.nanmin(x)
    mx = np.nanmax(x)
    if mx > 0:
        x = x / mx
    return x



def compute_bacteria_edge_outline_afm(img: np.ndarray, region_mask: np.ndarray, params: AfmBacteriaSegParams) -> dict[str, Any]:
    """Audit-ready outline generator.

    Modes:
      - strict: outline only from (smoothed) region_mask boundary
      - inclusive: strict boundary + extra intensity edges, but ONLY inside a thin ring around the mask
    """
    import numpy as np
    from skimage import morphology, exposure, feature
    from skimage.segmentation import find_boundaries
    from skimage import restoration

    # --- input prep ---
    # Supports:
    #  - bool mask (union)
    #  - int label image (instance segmentation) -> per-object boundaries (desired "kanálek" look)
    src = np.asarray(region_mask)

    if src.dtype.kind in ("i", "u") and src.ndim == 2 and int(np.max(src)) > 0:
        lab = src.astype(np.int32, copy=False)
        m = lab > 0
        # per-object boundaries (between different labels and background)
        boundary = find_boundaries(lab, mode="outer")
    else:
        m = src.astype(bool)
        boundary = find_boundaries(m, mode="outer")

    # --- mask cleanup for stable geometry (applied to m, not to boundary) ---
    close_r = int(getattr(params, "closing_radius", 1))
    if close_r > 0:
        m = morphology.binary_closing(m, morphology.disk(close_r))

    fill_area = int(getattr(params, "fill_holes_area", 50))
    if fill_area > 0:
        m = morphology.remove_small_holes(m, area_threshold=fill_area)

    # outline-only smoothing (geometric look)
    rs = int(getattr(params, "outline_smoothing_radius_px", 2))
    if rs > 0:
        m = morphology.binary_closing(m, morphology.disk(rs))
        m = morphology.binary_opening(m, morphology.disk(1))

    # NOTE:
    # boundary is computed above (either instance or union boundary).
    # m is used below for ring/inclusive mode restriction.

    mode = str(getattr(params, "outline_mode", "inclusive")).strip().lower()

    extra = np.zeros_like(boundary, dtype=bool)

    if mode == "inclusive":
        # --- build ring around the mask (limits where we look for extra edges) ---
        ring_r = int(getattr(params, "outline_ring_radius_px", 2))
        ring_r = max(1, ring_r)

        dil = morphology.binary_dilation(m, morphology.disk(ring_r))
        ero = morphology.binary_erosion(m, morphology.disk(ring_r))
        ring = dil & (~ero)

        # --- intensity prep (deterministic, mild; keeps auditability) ---
        x = np.asarray(img)
        if x.ndim == 3:
            if x.shape[-1] >= 3:
                x = x[..., 0].astype(np.float32) * 0.299 + x[..., 1].astype(np.float32) * 0.587 + x[..., 2].astype(np.float32) * 0.114
            else:
                x = x[..., 0]
        x = np.asarray(x, dtype=np.float32)
        # normalize 0..1
        x = x - np.nanmin(x)
        mx = np.nanmax(x)
        if mx > 0:
            x = x / mx

        if getattr(params, "invert", False):
            x = 1.0 - x

        # CLAHE (mild, consistent)
        try:
            x = exposure.equalize_adapthist(x, clip_limit=2.0, kernel_size=(8, 8)).astype(np.float32)
        except Exception:
            pass

        # light NLM to reduce AFM microtexture impact (fast_mode deterministic)
        try:
            x = restoration.denoise_nl_means(
                x, h=(12.0 / 255.0), fast_mode=True, patch_size=5, patch_distance=6, channel_axis=None
            ).astype(np.float32)
        except Exception:
            pass

        # --- canny edges, then restrict to ring ---
        sigma = float(getattr(params, "outline_edge_sigma", 1.2))
        low = float(getattr(params, "outline_canny_low", 0.10))
        high = float(getattr(params, "outline_canny_high", 0.30))

        edges = feature.canny(x, sigma=sigma, low_threshold=low, high_threshold=high)
        extra = edges & ring

        # connect tiny gaps lightly (reuse edge_link_radius_px if present)
        link_r = int(getattr(params, "edge_link_radius_px", 1))
        if link_r > 0:
            extra = morphology.binary_closing(extra, morphology.disk(link_r))

    # combine strict boundary + extra ring edges
    combined = boundary | extra

    # thickness control (your existing convention)
    t = int(getattr(params, "edge_thickness_px", 2))
    if t <= 0:
        out_edges = combined
    else:
        dil_r = max(0, t - 1)  # 2 => ~2–3 px
        out_edges = morphology.binary_dilation(combined, morphology.disk(dil_r)) if dil_r > 0 else combined

    debug = {
        "outline_mode": mode,
        "outline_smoothing_radius_px": int(getattr(params, "outline_smoothing_radius_px", 2)),
        "edge_thickness_px": int(getattr(params, "edge_thickness_px", 2)),
        "closing_radius": close_r,
        "fill_holes_area": fill_area,
        "outline_ring_radius_px": int(getattr(params, "outline_ring_radius_px", 2)),
        "outline_edge_sigma": float(getattr(params, "outline_edge_sigma", 1.2)),
        "outline_canny_low": float(getattr(params, "outline_canny_low", 0.10)),
        "outline_canny_high": float(getattr(params, "outline_canny_high", 0.30)),
        "coverage": float(out_edges.mean()),
    }
    return {"edge_mask": out_edges, "debug": debug}


def segment_bacteria_watershed_afm(img: np.ndarray, params: AfmBacteriaSegParams):
    """
    Detect-all watershed segmentation for dense bacterial fields.

    Returns:
      labels (int32): instance labels 1..N
      mask (bool): labels>0
      debug (dict)
    """
    print(
        "[AFM SEG PARAMS]",
        "separate=", getattr(params, "separate", None),
        "log_sigma=", getattr(params, "log_sigma", None),
        "peak_min_distance=", getattr(params, "peak_min_distance", None),
        "low_mask_factor=", getattr(params, "low_mask_factor", None),
        "min_area_px=", getattr(params, "min_area_px", None),
    )
    import numpy as np
    from scipy import ndimage as ndi
    from skimage import filters, exposure, morphology, measure, segmentation, feature

    # --- ensure grayscale 2D ---
    # --- ensure grayscale 2D ---
    img = np.asarray(img)
    if img.ndim == 3:
        # standard luminance
        if img.shape[-1] >= 3:
             img = img[..., :3].mean(axis=2)
        else:
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
    if getattr(params, "height_aware", True):
        # NEW LOGIC (StdDev relative threshold)
        # Background was already calculated above: bg = gaussian(img01, ...)
        
        # height_rel = data - bg. 
        # Note: 'flat' at line 94 is (img01 - bg), but line 95 rescales it.
        # We use raw difference for physical-like thresholding.
        height_rel = img01 - bg
        
        # User requested: mask = height_rel > (k * std(height_rel))
        # k = low_mask_factor (defaults to 0.0 in profile = strict > 0)
        
        std_val = np.std(height_rel)
        k = float(params.low_mask_factor) 
        
        threshold = k * std_val
        base_mask = height_rel > threshold
        
        thr = threshold
        thr_low = threshold
        
        # 4a) Morphology Clean (Closing)
        # User: "morphology clean"
        # AFM specific closing to connect fragmented parts or smoothing
        c_rad = int(getattr(params, "closing_radius_px", 2))
        if c_rad > 0:
            base_mask = morphology.binary_closing(base_mask, morphology.disk(c_rad))
        
    else:
        # Legacy mode
        threshold = np.percentile(den, 65)
        base_mask = den > threshold
        thr_low = threshold 
        thr = threshold

    # cleanup: remove speckles + fill small holes ON BOOLEAN MASK
    # This avoids "Only one label was provided" warning from skier remove_small_objects on int array
    base_mask = morphology.remove_small_objects(base_mask, min_size=int(params.min_area_px))
    base_mask = morphology.remove_small_holes(base_mask, area_threshold=int(params.hole_area_px))

    # Check which logic to use
    # Check which logic to use
    do_separate = bool(getattr(params, "separate", True))
    
    n_markers = 0
    if do_separate:
        # --- SAFE watershed block ---
        try:
            # 4) Improved Watershed Separation
            # (Less aggressive smoothing -> better separation of touching bacteria)
            dist = ndi.distance_transform_edt(base_mask)
            
            # Sigma 0.8 is generally good for bacterial shapes in AFM
            dist_smooth = ndi.gaussian_filter(dist, sigma=0.8)

            # Find peaks (markers)
            coords = feature.peak_local_max(
                dist_smooth,
                min_distance=int(getattr(params, "peak_min_distance", 12)),
                labels=base_mask
            )

            # Create markers array
            markers = np.zeros_like(dist, dtype=int)
            for i, (r, c) in enumerate(coords, start=1):
                markers[r, c] = i
            
            n_markers = int(markers.max())

            # Watershed
            labels = segmentation.watershed(
                -dist_smooth, 
                markers, 
                mask=base_mask,
                compactness=float(getattr(params, "watershed_compactness", 0.0))
            )
            
            # 7) Remove small instances + Keep instances
            if labels.max() > 1:
                labels = morphology.remove_small_objects(labels, min_size=int(params.min_area_px))
            elif labels.max() == 1:
                # Avoid "Only one label" warning
                tmp_mask = labels > 0
                tmp_mask = morphology.remove_small_objects(tmp_mask, min_size=int(params.min_area_px))
                labels = measure.label(tmp_mask)

            # ✅ IMPORTANT: keep watershed instances
            # measure.label(labels) would treat all non-zero pixels as one binary mask and destroy instances.
            labels = segmentation.relabel_sequential(labels)[0]
            
        except Exception:
            # fallback to simple mask if watershed fails
            labels = measure.label(base_mask)
            labels = segmentation.relabel_sequential(labels)[0]
            n_markers = 0
    else:
        # 🔵 Stable mode – no watershed (Connected Components)
        # We use measure.label to get distinct objects from the mask
        labels = measure.label(base_mask)
        n_markers = 0
        
    labels = labels.astype(np.int32)

    mask = labels > 0
    debug = {
        "thr_otsu": float(thr),
        "thr_low": float(thr_low),
        "mask_coverage": float(base_mask.mean()),
        "n_markers": n_markers,
        "count": int(labels.max()),
        "mode": "watershed" if do_separate else "cc_no_watershed",
    }
    # debug["n_markers"] is already set above safely
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
    # Only if not already segmented
    if labels is None:
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

    from skimage.measure import regionprops_table
    import numpy as np

    rod_mask = None
    rod_labels = None
    rod_table = None

    if bool(getattr(params, "rods_only", False)):
        props = regionprops_table(
            labels,
            properties=("label", "area", "centroid", "orientation",
                        "major_axis_length", "minor_axis_length",
                        "eccentricity", "solidity")
        )

        # compute aspect ratio safely
        major = np.asarray(props["major_axis_length"], dtype=float)
        minor = np.asarray(props["minor_axis_length"], dtype=float)
        aspect = major / np.maximum(minor, 1e-6)

        min_major = float(getattr(params, "rods_min_major_axis_px", 18.0))
        min_ar = float(getattr(params, "rods_min_aspect_ratio", 2.5))
        min_ecc = float(getattr(params, "rods_min_eccentricity", 0.85))

        keep = (major >= min_major) & (aspect >= min_ar) & (np.asarray(props["eccentricity"], float) >= min_ecc)

        keep_labels = set(np.asarray(props["label"], int)[keep].tolist())

        rod_labels = np.zeros_like(labels, dtype=np.int32)
        if keep_labels:
            # re-label sequentially for clean downstream
            new_id = 1
            for lab in sorted(keep_labels):
                rod_labels[labels == lab] = new_id
                new_id += 1

        rod_mask = rod_labels > 0

        # Build CSV-ready table (for fitting scripts)
        # Use new labels indexing: we recompute props on rod_labels for consistent label IDs
        props2 = regionprops_table(
            rod_labels,
            properties=("label", "area", "centroid", "orientation",
                        "major_axis_length", "minor_axis_length",
                        "eccentricity", "solidity")
        )
        major2 = np.asarray(props2["major_axis_length"], dtype=float)
        minor2 = np.asarray(props2["minor_axis_length"], dtype=float)
        aspect2 = major2 / np.maximum(minor2, 1e-6)

        rod_table = {
            "label": props2["label"],
            "area_px": props2["area"],
            "centroid_y": props2["centroid-0"],  # row
            "centroid_x": props2["centroid-1"],  # col
            "orientation_rad": props2["orientation"],
            "major_axis_px": major2,
            "minor_axis_px": minor2,
            "aspect_ratio": aspect2,
            "eccentricity": props2["eccentricity"],
            "solidity": props2["solidity"],
        }

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
        "threshold_otsu": float(dbg.get("thr_otsu", 0.0)),
        "threshold_low": float(dbg.get("thr_low", 0.0)),
        "markers_found": int(dbg.get("n_markers", markers.max() if "markers" in locals() else 0)),
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

    # Use instance labels for per-object outlines (matches desired "kanálek" geometry).
    # In rod-only mode, use rod_labels so overlay corresponds to rod_mask export.
    outline_src = labels
    if bool(getattr(params, "rods_only", False)) and (rod_labels is not None):
        outline_src = rod_labels

    edge = compute_bacteria_edge_outline_afm(img, outline_src, params)

    return {
        "mask": mask,
        "labels": labels,
        "objects": objects,
        "summary": summary,
        "audit": audit,
        "edge_mask": edge["edge_mask"],
        "edge_debug": edge["debug"],
        "rod_mask": rod_mask,
        "rod_labels": rod_labels,
        "rod_table": rod_table,
    }
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

