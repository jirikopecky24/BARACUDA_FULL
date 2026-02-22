"""AFM V2 Pipeline — Cellpose-only segmentation + rod geometry filter.

Pipeline version: AFM_V2_CELLPOSE
Backend: Cellpose (mandatory)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Tuple

import numpy as np
from skimage import measure

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
    cp_model: str = "cyto3"
    cp_diameter: float = 0.0       # 0 = auto
    cp_flow_threshold: float = 0.4
    cp_cellprob_threshold: float = -0.5

    # rod filter (high recall)
    rods_only: bool = True
    rods_min_major_axis_px: float = 12.0
    rods_min_aspect_ratio: float = 1.8
    rods_min_eccentricity: float = 0.65
    rods_min_area_px: int = 8

    # overlay
    ellipse_thickness_px: int = 2


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


def _segment_cellpose(norm: np.ndarray, p: AfmV2Params) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Run Cellpose segmentation. Raises RuntimeError if not installed."""
    if not _HAS_CELLPOSE:
        raise RuntimeError(
            "Cellpose is not installed. "
            "AFM V2 pipeline requires cellpose. "
            "Install via: pip install cellpose"
        )

    img8 = (norm * 255.0).astype(np.uint8)

    model = cp_models.Cellpose(model_type=p.cp_model)
    masks, flows, styles, diams = model.eval(
        img8,
        channels=[0, 0],
        diameter=(None if p.cp_diameter == 0 else float(p.cp_diameter)),
        flow_threshold=float(p.cp_flow_threshold),
        cellprob_threshold=float(p.cp_cellprob_threshold),
    )

    audit = {
        "cellpose_model": p.cp_model,
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
    """Filter labels to keep only rod-shaped objects."""
    props = measure.regionprops(labels)
    keep = []
    for pr in props:
        maj = float(pr.axis_major_length) if hasattr(pr, 'axis_major_length') else float(pr.major_axis_length)
        mino_raw = float(pr.axis_minor_length) if hasattr(pr, 'axis_minor_length') else float(pr.minor_axis_length)
        mino = mino_raw if mino_raw > 0 else 1e-9
        ar = maj / mino
        ecc = float(getattr(pr, "eccentricity", 0.0))
        area = int(pr.area)

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
def run_afm_v2(height_img: np.ndarray, params: AfmV2Params) -> Dict[str, Any]:
    """Run AFM V2 Cellpose-only segmentation pipeline.

    Guaranteed return keys:
        labels, rod_labels, rod_table, audit, norm
    No None values — empty arrays if no rods found.
    """
    norm = _normalize(height_img, invert=params.invert,
                      p_low=params.clip_p_low, p_high=params.clip_p_high)

    # Cellpose segmentation
    labels, cp_audit = _segment_cellpose(norm, params)

    # Audit
    audit: Dict[str, Any] = {
        "pipeline_version": _AFM_PIPELINE_VERSION,
        "invert": params.invert,
        "clip_p_low": params.clip_p_low,
        "clip_p_high": params.clip_p_high,
        "rods_only": params.rods_only,
        "rods_min_major_axis_px": params.rods_min_major_axis_px,
        "rods_min_aspect_ratio": params.rods_min_aspect_ratio,
        "rods_min_eccentricity": params.rods_min_eccentricity,
        "rods_min_area_px": params.rods_min_area_px,
        "ellipse_thickness_px": params.ellipse_thickness_px,
    }
    audit.update(cp_audit)

    # Rod filter (always computed for guaranteed return contract)
    rod_labels, rod_table = rod_filter(labels, params)

    return {
        "norm": norm,
        "labels": labels,
        "rod_labels": rod_labels,
        "rod_table": rod_table,
        "audit": audit,
    }
