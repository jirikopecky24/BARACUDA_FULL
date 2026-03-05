"""AFM V2 Pipeline — Cellpose-only segmentation + rod geometry filter.

Pipeline version: AFM_V2_CELLPOSE
Backend: Cellpose (mandatory)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional

import numpy as np
from skimage import measure
from skimage.transform import resize
import logging

logger = logging.getLogger(__name__)

# ── Cellpose availability ────────────────────────────────────────────
try:
    from cellpose import models as cp_models
    import cellpose as _cellpose_pkg

    _HAS_CELLPOSE = True
    _CELLPOSE_VERSION = getattr(_cellpose_pkg, "__version__", "unknown")
except Exception:
    _HAS_CELLPOSE = False
    _CELLPOSE_VERSION = None

_AFM_PIPELINE_VERSION = "AFM_V2_CELLPOSE"


# ── Parameters ───────────────────────────────────────────────────────
@dataclass
class AfmV2Params:
    """Cellpose-only AFM segmentation parameters."""

    # preprocessing
    invert: bool = False
    clip_p_low: float = 1.0
    clip_p_high: float = 99.0

    # cellpose
    # cellpose
    cp_model: str = "cyto3"
    cp_diameter_mode: str = "auto"         # 'auto' or 'fixed'
    cp_diameter_px: Optional[int] = None   # None if auto, int if fixed
    cp_flow_threshold: float = 0.4
    cp_cellprob_threshold: float = -0.5

    # compute & preview
    compute_profile: str = "auto"
    preview_fast_mode: bool = False
    preview_downscale: float = 0.5

    # rod filter (high recall)
    rods_only: bool = True
    rods_min_major_axis_px: float = 12.0
    rods_min_aspect_ratio: float = 1.8
    rods_min_eccentricity: float = 0.65
    rods_min_area_px: int = 8

    # overlay
    ellipse_thickness_px: int = 2
    ellipse_alpha: float = 0.6


# ── Internal helpers ─────────────────────────────────────────────────
def _normalize(img: np.ndarray, invert: bool, p_low: float, p_high: float) -> np.ndarray:
    x = img.astype(np.float32, copy=False)
    finite = x[np.isfinite(x)]
    if len(finite) == 0:
        return np.zeros_like(x)
    lo, hi = np.percentile(finite, [p_low, p_high])
    x = np.clip(x, lo, hi)
    x = (x - lo) / (hi - lo + 1e-9)
    if invert:
        x = 1.0 - x
    return x


def _segment_cellpose(norm: np.ndarray, p: AfmV2Params, um_per_px: float) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Run Cellpose segmentation. Raises RuntimeError if not installed."""
    if not _HAS_CELLPOSE:
        raise RuntimeError(
            "Cellpose is not installed. "
            "AFM V2 pipeline requires cellpose. "
            "Install via: pip install cellpose"
        )

    img8 = (norm * 255.0).astype(np.uint8)

    from barakuda.devices.afm.core.compute import resolve_device
    from barakuda.devices.afm.core.auto_diameter import estimate_diameter_px
    from barakuda.devices.afm.core.cellpose_cache import get_cellpose
    import time

    t_get_start = time.perf_counter()
    res = resolve_device(p.compute_profile)
    device_str = res["device"]

    model = get_cellpose(p.cp_model, device_str)

    t_get_end = time.perf_counter()
    cellpose_get_ms = round((t_get_end - t_get_start) * 1000.0, 1)

    is_v4 = _CELLPOSE_VERSION and str(_CELLPOSE_VERSION).startswith("4")

    # Resolve Diameter
    diameter_estimate = {"status": "USER_FIXED"}
    if p.cp_diameter_mode == "auto":
        eff_diam, audit_diam = estimate_diameter_px(um_per_px)
        diameter_effective_px = eff_diam if eff_diam > 0 else None
        diameter_estimate = audit_diam
    else:
        diameter_effective_px = p.cp_diameter_px

    eval_kwargs: Dict[str, Any] = {
        "diameter": diameter_effective_px,
        "flow_threshold": float(p.cp_flow_threshold),
        "cellprob_threshold": float(p.cp_cellprob_threshold),
    }

    if not is_v4:
        eval_kwargs["channels"] = [0, 0]

    import torch
    logger.info(f"torch.cuda.is_available(): {torch.cuda.is_available()}")
    logger.info(f"torch.__version__: {torch.__version__}")
    logger.info(f"device resolved: {device_str}")
    
    net = getattr(model, "net", None)
    if net is not None:
        try:
            net_dev = next(net.parameters()).device
        except StopIteration:
            net_dev = "NA"
    else:
        net_dev = "NA"
    logger.info(f"Cellpose net device: {net_dev}")

    t_eval_start = time.perf_counter()
    eval_out = model.eval(img8, **eval_kwargs)
    t_eval_end = time.perf_counter()
    cellpose_eval_ms = round((t_eval_end - t_eval_start) * 1000.0, 1)
    
    masks = eval_out[0]

    audit = {
        "compute_profile": res["compute_profile"],
        "device": res["device"],
        "gpu_name": res["gpu_name"],
        "torch_version": res["torch_version"],
        "cellpose_version": res["cellpose_version"],
        "cellpose_model": p.cp_model,
        "diameter_ui": "Auto" if p.cp_diameter_mode == "auto" else p.cp_diameter_px,
        "diameter_effective_px": diameter_effective_px if diameter_effective_px is not None else "Auto",
        "diameter_estimate": diameter_estimate,
        "flow_threshold": float(p.cp_flow_threshold),
        "cellprob_threshold": float(p.cp_cellprob_threshold),
        "cellpose_get_ms": cellpose_get_ms,
        "cellpose_eval_ms": cellpose_eval_ms,
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
    """Filter labels to keep only rod-shaped objects."""
    props = measure.regionprops(labels)
    keep = []
    for pr in props:
        area = int(pr.area)
        if not p.rods_only:
            # If not forcing rods, just filter tiny specks
            if area >= p.rods_min_area_px:
                keep.append(pr.label)
            continue
            
        maj = float(pr.axis_major_length) if hasattr(pr, 'axis_major_length') else float(pr.major_axis_length)
        mino_raw = float(pr.axis_minor_length) if hasattr(pr, 'axis_minor_length') else float(pr.minor_axis_length)
        mino = mino_raw if mino_raw > 0 else 1e-9
        ar = maj / mino
        ecc = float(getattr(pr, "eccentricity", 0.0))

        if (maj >= p.rods_min_major_axis_px
                and ar >= p.rods_min_aspect_ratio
                and ecc >= p.rods_min_eccentricity
                and area >= p.rods_min_area_px):
            keep.append(pr.label)

    if not keep:
        return np.zeros_like(labels, dtype=np.int32), _empty_rod_table()

    rod_labels = np.where(np.isin(labels, keep), labels, 0).astype(np.int32)

    # Build dict-of-arrays table
    rp = measure.regionprops(rod_labels)

    def _maj(r):
        return float(r.axis_major_length) if hasattr(r, 'axis_major_length') else float(r.major_axis_length)

    def _min(r):
        return float(r.axis_minor_length) if hasattr(r, 'axis_minor_length') else float(r.minor_axis_length)

    tbl = {
        "label": np.array([r.label for r in rp], dtype=np.int32),
        "centroid_x": np.array([r.centroid[1] for r in rp], dtype=np.float32),
        "centroid_y": np.array([r.centroid[0] for r in rp], dtype=np.float32),
        "orientation_rad": np.array([float(getattr(r, "orientation", 0.0)) for r in rp], dtype=np.float32),
        "major_axis_px": np.array([_maj(r) for r in rp], dtype=np.float32),
        "minor_axis_px": np.array([_min(r) for r in rp], dtype=np.float32),
        "aspect_ratio": np.array(
            [_maj(r) / (_min(r) + 1e-9) for r in rp],
            dtype=np.float32,
        ),
        "eccentricity": np.array([float(getattr(r, "eccentricity", 0.0)) for r in rp], dtype=np.float32),
        "solidity": np.array([float(getattr(r, "solidity", 0.0)) for r in rp], dtype=np.float32),
        "area_px": np.array([int(r.area) for r in rp], dtype=np.int32),
    }
    return rod_labels, tbl


# ── Main entry point ─────────────────────────────────────────────────
def run_afm_v2(height_img: np.ndarray, params: AfmV2Params, um_per_px: float = 0.0) -> Dict[str, Any]:
    """Run AFM V2 Cellpose-only segmentation pipeline.

    Guaranteed return keys:
        labels, rod_labels, rod_table, audit, norm
    No None values — empty arrays if no rods found.
    """
    import time
    t0 = time.perf_counter()
    
    scale_factor = 1.0
    downscaled = False
    
    norm = _normalize(height_img, invert=params.invert,
                      p_low=params.clip_p_low, p_high=params.clip_p_high)

    # 1) Downscale conditionally
    if params.preview_fast_mode and params.preview_downscale < 1.0:
        scale_factor = params.preview_downscale
        H, W = norm.shape
        new_h, new_w = max(1, int(H * scale_factor)), max(1, int(W * scale_factor))
        norm = resize(norm, (new_h, new_w), order=1, anti_aliasing=True).astype(np.float32)
        downscaled = True
        
        # We must multiply um_per_px because the pixels are now physically larger
        if um_per_px > 0:
            um_per_px = um_per_px / scale_factor

    t1 = time.perf_counter()

    # 2) Cellpose segmentation
    labels, cp_audit = _segment_cellpose(norm, params, um_per_px)
    
    t2 = time.perf_counter()

    # 3) Rescale purely for the mask dimensions to match original array natively
    if downscaled:
        H_orig, W_orig = height_img.shape
        labels = resize(labels, (H_orig, W_orig), order=0, anti_aliasing=False, preserve_range=True).astype(np.int32)
        norm = resize(norm, (H_orig, W_orig), order=1, anti_aliasing=True).astype(np.float32)

    # 4) Filter and generate rod table (done securely on the original image dimensions now)
    rod_labels, rod_table = rod_filter(labels, params)

    t3 = time.perf_counter()
    
    timings_ms = {
        "preprocess_ms": round((t1 - t0) * 1000.0, 1),
        "cellpose_get_ms": cp_audit.pop("cellpose_get_ms", 0.0),
        "cellpose_eval_ms": cp_audit.pop("cellpose_eval_ms", 0.0),
        "postprocess_ms": round((t3 - t2) * 1000.0, 1),
        "total_ms": round((t3 - t0) * 1000.0, 1)
    }

    # Audit
    audit: Dict[str, Any] = {
        "pipeline_version": _AFM_PIPELINE_VERSION,
        "invert": params.invert,
        "clip_p_low": params.clip_p_low,
        "clip_p_high": params.clip_p_high,
        "preview_fast_mode": params.preview_fast_mode,
        "preview_downscale_applied": downscaled,
        "preview_downscale_factor": scale_factor,
        "rods_only": params.rods_only,
        "rod_filter": {
            "min_major_axis_px": params.rods_min_major_axis_px,
            "min_aspect_ratio": params.rods_min_aspect_ratio,
            "min_eccentricity": params.rods_min_eccentricity,
            "min_area_px": params.rods_min_area_px,
        },
        "timings_ms": timings_ms,
        "cellpose": cp_audit
    }

    return {
        "labels": labels,          # raw cellpose ints (rescaled if fast mode)
        "rod_labels": rod_labels,  # kept rods
        "rod_table": rod_table,
        "audit": audit,
        "norm": norm               # 2D float32 [0,1] normalized back to full resolution scale
    }
