"""SPM loader via AFMReader with explicit Bruker fallback.

Primary: AFMReader.spm.load_spm
Fallback: brucker_spm.read_channel (logged + audited, NEVER silent)
"""
from __future__ import annotations

import logging
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


def list_spm_channels(path: str) -> list[str]:
    """Return list of preferred channel names to try.

    Does NOT rely on AFMReader internals for enumeration.
    Returns the fixed preferred list; caller should try them in order.
    """
    return list(_PREFERRED_CHANNELS)


def load_spm_height(
    path: str,
    prefer: tuple[str, ...] = _PREFERRED_CHANNELS,
) -> Tuple[np.ndarray, dict]:
    """Load height channel from .spm file.

    Returns
    -------
    (height_2d_float32, meta_dict)

    meta_dict keys:
        selected_channel, shape, pixel_to_nm, pixel_to_nm_source,
        loader, loader_reason, afmreader_version
    """
    if _HAS_AFMREADER:
        return _load_via_afmreader(path, prefer)
    else:
        logger.warning(
            "AFMReader not installed – falling back to brucker_spm.read_channel. "
            "Install AFMReader for full metadata + scaling support."
        )
        return _load_via_brucker_fallback(path, prefer)


def _load_via_afmreader(
    path: str, prefer: tuple[str, ...]
) -> Tuple[np.ndarray, dict]:
    """Try each preferred channel via AFMReader until one succeeds."""
    last_err = None
    for ch_name in prefer:
        try:
            image, px_to_nm = _afmreader_load_spm(file_path=path, channel=ch_name)
            img = np.asarray(image, dtype=np.float32)

            # Determine scaling source
            if px_to_nm is not None and float(px_to_nm) > 0:
                pixel_to_nm = float(px_to_nm)
                px_source = "afmreader"
            else:
                pixel_to_nm = 0.0
                px_source = "unknown"
                logger.warning(
                    "AFMReader returned no pixel-to-nm scaling for channel '%s'. "
                    "Marking as unknown.", ch_name,
                )

            meta = {
                "selected_channel": ch_name,
                "shape": list(img.shape),
                "pixel_to_nm": pixel_to_nm,
                "pixel_to_nm_source": px_source,
                "loader": "afmreader",
                "loader_reason": "",
                "afmreader_version": _AFMREADER_VERSION,
            }
            logger.info(
                "Loaded .spm via AFMReader: channel=%s, shape=%s, px_to_nm=%.4f",
                ch_name, img.shape, pixel_to_nm,
            )
            return img, meta
        except Exception as exc:
            last_err = exc
            continue

    # All preferred channels failed
    raise RuntimeError(
        f"AFMReader could not load any of channels {prefer} from '{path}'. "
        f"Last error: {last_err!r}"
    )


def _load_via_brucker_fallback(
    path: str, prefer: tuple[str, ...]
) -> Tuple[np.ndarray, dict]:
    """Explicit fallback to brucker_spm – ALWAYS logged + audit-tagged."""
    from barakuda.devices.afm.io.brucker_spm import read_channel

    prefer_str = prefer[0] if prefer else "Height"
    img, ch = read_channel(path, prefer_name_contains=prefer_str)
    img = np.asarray(img, dtype=np.float32)

    meta = {
        "selected_channel": ch.name,
        "shape": list(img.shape),
        "pixel_to_nm": 0.0,
        "pixel_to_nm_source": "unknown",
        "loader": "brucker_fallback",
        "loader_reason": "AFMReader not installed",
        "afmreader_version": None,
        "brucker_meta": ch.meta,
    }
    logger.warning(
        "Loaded .spm via BRUCKER FALLBACK: channel=%s, shape=%s. "
        "Install AFMReader for scaling + full metadata.",
        ch.name, img.shape,
    )
    return img, meta
