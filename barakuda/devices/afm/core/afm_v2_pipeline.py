from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
import numpy as np
from scipy.ndimage import distance_transform_edt
from skimage import filters, morphology, measure, segmentation, exposure, feature

try:
    from cellpose import models as cp_models  # optional
    import cellpose as _cellpose_pkg
    _HAS_CELLPOSE = True
    _CELLPOSE_VERSION = getattr(_cellpose_pkg, "__version__", "unknown")
except Exception:
    _HAS_CELLPOSE = False
    _CELLPOSE_VERSION = None

_AFM_PIPELINE_VERSION = "2.0"


@dataclass
class AfmV2Params:
    backend: str = "classic"  # "classic" | "cellpose"
    invert: bool = False

    # preprocessing
    clip_p_low: float = 1.0
    clip_p_high: float = 99.0

    # classic backend
    smooth_sigma: float = 0.3
    log_sigma: float = 1.6
    min_area_px: int = 8
    separate_watershed: bool = True
    peak_min_distance_px: int = 2
    watershed_compactness: float = 0.03

    # cellpose backend (high recall)
    cp_model: str = "cyto3"
    cp_diameter: float = 0.0  # 0 = auto
    cp_flow_threshold: float = 0.4
    cp_cellprob_threshold: float = -0.5

    # rod filter (high recall defaults)
    rods_only: bool = True
    rods_min_major_axis_px: float = 12.0
    rods_min_aspect_ratio: float = 1.8
    rods_min_eccentricity: float = 0.65

    # overlay
    ellipse_thickness_px: int = 2


def _normalize(img: np.ndarray, invert: bool, p_low: float, p_high: float) -> np.ndarray:
    x = img.astype(np.float32, copy=False)
    lo, hi = np.percentile(x[np.isfinite(x)], [p_low, p_high])
    x = np.clip(x, lo, hi)
    x = (x - lo) / (hi - lo + 1e-9)
    if invert:
        x = 1.0 - x
    return x


def segment_classic(norm: np.ndarray, p: AfmV2Params) -> np.ndarray:
    # smooth
    sm = filters.gaussian(norm, sigma=p.smooth_sigma, preserve_range=True)
    # LoG response for blobs/ridges
    log = -filters.laplace(filters.gaussian(sm, sigma=p.log_sigma, preserve_range=True))
    # threshold
    thr = filters.threshold_otsu(log)
    m = log > thr
    m = morphology.remove_small_objects(m, min_size=max(1, int(p.min_area_px)), connectivity=1)

    if not p.separate_watershed:
        lab = measure.label(m)
        return lab

    # markers via distance peaks
    dist = distance_transform_edt(m)
    coords = feature.peak_local_max(dist, min_distance=int(p.peak_min_distance_px), labels=m)
    markers = np.zeros_like(m, dtype=np.int32)
    for i, (r, c) in enumerate(coords, start=1):
        markers[r, c] = i
    if markers.max() == 0:
        lab = measure.label(m)
        return lab

    lab = segmentation.watershed(-dist, markers, mask=m, compactness=float(p.watershed_compactness))
    return lab


def segment_cellpose(norm: np.ndarray, p: AfmV2Params) -> Tuple[np.ndarray, Dict[str, Any]]:
    if not _HAS_CELLPOSE:
        raise RuntimeError("Cellpose is not installed. Install dependency or switch backend=classic.")

    # cellpose expects image in [0..255] or float; we feed 0..255 grayscale
    img8 = (norm * 255.0).astype(np.uint8)

    model = cp_models.Cellpose(model_type=p.cp_model)
    masks, flows, styles, diams = model.eval(
        img8,
        channels=[0, 0],
        diameter=(None if p.cp_diameter == 0 else float(p.cp_diameter)),
        flow_threshold=float(p.cp_flow_threshold),
        cellprob_threshold=float(p.cp_cellprob_threshold),
    )
    # masks already is label image
    audit = {
        "cellpose_model": p.cp_model,
        "cellpose_installed": True,
        "cellpose_version": _CELLPOSE_VERSION,
        "diameter": float(p.cp_diameter),
        "flow_threshold": float(p.cp_flow_threshold),
        "cellprob_threshold": float(p.cp_cellprob_threshold),
    }
    return masks.astype(np.int32), audit


def _empty_rod_table() -> Dict[str, np.ndarray]:
    """Return a valid rod_table with empty arrays for all required columns."""
    return {
        "label": np.array([], dtype=np.int32),
        "centroid_x": np.array([], dtype=np.float32),
        "centroid_y": np.array([], dtype=np.float32),
        "orientation_rad": np.array([], dtype=np.float32),
        "major_axis_px": np.array([], dtype=np.float32),
        "minor_axis_px": np.array([], dtype=np.float32),
        "aspect_ratio": np.array([], dtype=np.float32),
        "eccentricity": np.array([], dtype=np.float32),
        "solidity": np.array([], dtype=np.float32),
        "area_px": np.array([], dtype=np.int32),
    }


def rod_filter(labels: np.ndarray, p: AfmV2Params) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    props = measure.regionprops(labels)
    keep = []
    for pr in props:
        maj = float(pr.major_axis_length)
        mino = float(pr.minor_axis_length) if pr.minor_axis_length > 0 else 1e-9
        ar = maj / mino
        ecc = float(getattr(pr, "eccentricity", 0.0))
        if maj >= p.rods_min_major_axis_px and ar >= p.rods_min_aspect_ratio and ecc >= p.rods_min_eccentricity:
            keep.append(pr.label)

    if not keep:
        return np.zeros_like(labels, dtype=np.int32), _empty_rod_table()

    rod_labels = np.where(np.isin(labels, keep), labels, 0).astype(np.int32)

    # Build dict-of-arrays table (stable + fast + CSV ready)
    rp = measure.regionprops(rod_labels)
    tbl = {
        "label": np.array([r.label for r in rp], dtype=np.int32),
        "centroid_x": np.array([r.centroid[1] for r in rp], dtype=np.float32),
        "centroid_y": np.array([r.centroid[0] for r in rp], dtype=np.float32),
        "orientation_rad": np.array([float(getattr(r, "orientation", 0.0)) for r in rp], dtype=np.float32),
        "major_axis_px": np.array([float(r.major_axis_length) for r in rp], dtype=np.float32),
        "minor_axis_px": np.array([float(r.minor_axis_length) for r in rp], dtype=np.float32),
        "aspect_ratio": np.array(
            [float(r.major_axis_length) / (float(r.minor_axis_length) + 1e-9) for r in rp],
            dtype=np.float32
        ),
        "eccentricity": np.array([float(getattr(r, "eccentricity", 0.0)) for r in rp], dtype=np.float32),
        "solidity": np.array([float(getattr(r, "solidity", 0.0)) for r in rp], dtype=np.float32),
        "area_px": np.array([int(r.area) for r in rp], dtype=np.int32),
    }
    return rod_labels, tbl


def run_afm_v2(height_img: np.ndarray, params: AfmV2Params) -> Dict[str, Any]:
    """Run AFM v2 segmentation pipeline.

    Guaranteed return keys:
        labels, rod_labels, rod_table, audit, norm
    No None values — empty arrays if no rods found.
    """
    norm = _normalize(height_img, invert=params.invert, p_low=params.clip_p_low, p_high=params.clip_p_high)

    audit: Dict[str, Any] = {
        "afm_pipeline_version": _AFM_PIPELINE_VERSION,
        "backend": params.backend,
        "invert": params.invert,
        "clip_p_low": params.clip_p_low,
        "clip_p_high": params.clip_p_high,
        "smooth_sigma": params.smooth_sigma,
        "log_sigma": params.log_sigma,
        "min_area_px": params.min_area_px,
        "separate_watershed": params.separate_watershed,
        "peak_min_distance_px": params.peak_min_distance_px,
        "watershed_compactness": params.watershed_compactness,
        "rods_only": params.rods_only,
        "rods_min_major_axis_px": params.rods_min_major_axis_px,
        "rods_min_aspect_ratio": params.rods_min_aspect_ratio,
        "rods_min_eccentricity": params.rods_min_eccentricity,
        "ellipse_thickness_px": params.ellipse_thickness_px,
    }

    if params.backend == "cellpose":
        labels, cp_audit = segment_cellpose(norm, params)
        audit.update(cp_audit)
    else:
        labels = segment_classic(norm, params)

    # Guaranteed: always compute rod_labels and rod_table
    rod_labels, rod_table = rod_filter(labels, params)

    return {
        "norm": norm,
        "labels": labels,
        "rod_labels": rod_labels,
        "rod_table": rod_table,
        "audit": audit,
    }
