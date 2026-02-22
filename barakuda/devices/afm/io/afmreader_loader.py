"""SPM loader via AFMReader — mandatory, no fallback.

If AFMReader is not installed, raises RuntimeError.
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
    """Return list of preferred channel names to try."""
    return list(_PREFERRED_CHANNELS)


def load_spm_height(
    path: str,
    prefer: tuple[str, ...] = _PREFERRED_CHANNELS,
) -> Tuple[np.ndarray, dict]:
    """Load height channel from .spm file via AFMReader.

    Returns
    -------
    (height_2d_float32, meta_dict)

    meta_dict keys:
        selected_channel, shape, pixel_to_nm, pixel_to_nm_source,
        loader, afmreader_version

    Raises
    ------
    RuntimeError
        If AFMReader is not installed.
    """
    if not _HAS_AFMREADER:
        raise RuntimeError(
            "AFMReader is required for .spm files but is not installed. "
            "Install via: pip install AFMReader"
        )

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
                "afmreader_version": _AFMREADER_VERSION,
            }
            logger.info(
                "SPM loaded via AFMReader | channel=%s | shape=%s | pixel_to_nm=%.4f",
                ch_name, img.shape, pixel_to_nm,
            )
            return img, meta
        except Exception as exc:
            last_err = exc
            continue

    raise RuntimeError(
        f"AFMReader could not load any of channels {prefer} from '{path}'. "
        f"Last error: {last_err!r}"
    )
