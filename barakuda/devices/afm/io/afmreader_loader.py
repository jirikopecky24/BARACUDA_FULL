"""SPM loader via AFMReader — mandatory, no fallback.

If AFMReader is not installed, raises RuntimeError.
Scale derived from Scan Size header (primary) or AFMReader px_to_nm (fallback).
Never from OT/camera.
"""
from __future__ import annotations

import logging
import re
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Preferred channel names (deterministic order)
_PREFERRED_CHANNELS: tuple[str, ...] = ("Height", "Height Sensor", "ZSensor")

# Probe AFMReader availability at import time
try:
    from AFMReader.spm import load_spm as _afmreader_load_spm
    import AFMReader as _afmreader_pkg

    _HAS_AFMREADER = True
    _AFMREADER_VERSION = getattr(_afmreader_pkg, "__version__", "unknown")
except Exception:
    _HAS_AFMREADER = False
    _AFMREADER_VERSION = None


# ── Scan Size header parser ──────────────────────────────────────
_SCAN_SIZE_RE = re.compile(
    r"\\Scan\s+Size:\s*([\d.]+)\s*(um|nm|mm|µm)",
    re.IGNORECASE,
)

_UNIT_TO_UM = {
    "um": 1.0,
    "µm": 1.0,
    "nm": 1e-3,
    "mm": 1e3,
}


def _parse_scan_size_um(path: str) -> float | None:
    """Extract Scan Size in µm from .spm binary header.

    Reads first ~256 kB, decodes as latin1, and regex-matches
    'Scan Size: <value> <unit>'.  Returns None if not found.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read(256 * 1024)
        text = raw.decode("latin1", errors="ignore")

        m = _SCAN_SIZE_RE.search(text)
        if m:
            val = float(m.group(1))
            unit = m.group(2).lower().replace("µ", "µ")  # normalize
            factor = _UNIT_TO_UM.get(unit, _UNIT_TO_UM.get("um", 1.0))
            return val * factor
    except Exception as exc:
        logger.debug("Could not parse Scan Size header: %s", exc)
    return None


# ── Public API ────────────────────────────────────────────────────

def list_spm_channels(path: str) -> list[str]:
    """Return list of preferred channel names to try."""
    return list(_PREFERRED_CHANNELS)


def load_spm_height(
    path: str,
    prefer: tuple[str, ...] = _PREFERRED_CHANNELS,
) -> Tuple[np.ndarray, dict]:
    """Load height channel from .spm file via AFMReader.

    Scale derivation priority:
        1. Scan Size header → um_per_px = scan_size_um / width_px
        2. AFMReader px_to_nm → um_per_px = px_to_nm / 1000
        3. unknown → um_per_px = 0.0

    Returns
    -------
    (height_2d_float32, meta_dict)
    """
    if not _HAS_AFMREADER:
        raise RuntimeError(
            "AFMReader is required for .spm files but is not installed. "
            "Install via: pip install AFMReader"
        )

    # Try parsing Scan Size before loading channels (header is always there)
    scan_size_um = _parse_scan_size_um(path)
    scan_size_source = "header" if scan_size_um is not None else "unknown"

    last_err = None
    for ch_name in prefer:
        try:
            image, px_to_nm = _afmreader_load_spm(file_path=path, channel=ch_name)
            img = np.asarray(image, dtype=np.float32)
            width_px = img.shape[1] if img.ndim >= 2 else img.shape[0]

            # ── Derive AFM scale (independent from OT) ───────────
            pixel_to_nm = 0.0
            px_source = "unknown"
            um_per_px = 0.0
            um_source = "unknown"

            # Priority 1: Scan Size header
            if scan_size_um is not None and scan_size_um > 0 and width_px > 0:
                um_per_px = scan_size_um / width_px
                um_source = "scan_size/header"
                logger.info(
                    "Scale from header: scan_size=%.4f µm / %d px = %.6f µm/px",
                    scan_size_um, width_px, um_per_px,
                )
            # Priority 2: AFMReader px_to_nm
            elif px_to_nm is not None and float(px_to_nm) > 0:
                pixel_to_nm = float(px_to_nm)
                px_source = "afmreader"
                um_per_px = pixel_to_nm / 1000.0
                um_source = "afmreader(px_to_nm)"
                logger.info(
                    "Scale from AFMReader: px_to_nm=%.4f nm = %.6f µm/px",
                    pixel_to_nm, um_per_px,
                )
            # Priority 3: unknown
            else:
                logger.warning(
                    "No scale found for '%s'. Scan Size header not found, "
                    "AFMReader returned no px_to_nm. Scale set to unknown.",
                    path,
                )

            # Also store px_to_nm from AFMReader regardless of which scale we used
            if px_to_nm is not None and float(px_to_nm) > 0:
                pixel_to_nm = float(px_to_nm)
                px_source = "afmreader"

            meta = {
                "selected_channel": ch_name,
                "shape": list(img.shape),
                "pixel_to_nm": pixel_to_nm,
                "pixel_to_nm_source": px_source,
                "afm_um_per_px": um_per_px,
                "afm_um_per_px_source": um_source,
                "afm_scan_size_um": scan_size_um if scan_size_um is not None else 0.0,
                "afm_scan_size_source": scan_size_source,
                "loader": "afmreader",
                "afmreader_version": _AFMREADER_VERSION,
                "device": "AFM",
            }
            logger.info(
                "SPM loaded | ch=%s | shape=%s | um_per_px=%.6f (%s) | "
                "scan_size=%.4f µm (%s)",
                ch_name, img.shape, um_per_px, um_source,
                meta["afm_scan_size_um"], scan_size_source,
            )
            return img, meta
        except Exception as exc:
            last_err = exc
            continue

    raise RuntimeError(
        f"AFMReader could not load any of channels {prefer} from '{path}'. "
        f"Last error: {last_err!r}"
    )
