from __future__ import annotations

import numpy as np


def normalize_strength(image: np.ndarray, strength: float) -> np.ndarray:
    """
    Jednoduchá, bezpečná úprava kontrastu.
    strength = 0  -> žádná změna
    strength = 1  -> standardní normalizace (roztažení histogramu)
    strength >1   -> trochu agresivnější (stále bezpečné)

    Funguje pro grayscale i RGB.
    """
    strength = float(strength)
    if strength <= 0:
        return image.copy()

    img = image.astype(np.float32)

    # roztažení na 0..1 podle min/max
    mn = float(img.min())
    mx = float(img.max())
    if mx - mn < 1e-12:
        return image.copy()

    norm01 = (img - mn) / (mx - mn)

    # jemné zvýraznění kontrastu (gamma-like)
    # strength=1 -> gamma 1.0 (beze změny), strength=2 -> gamma ~0.7 (víc kontrastu)
    gamma = 1.0 / (0.6 + 0.4 * strength)  # držíme rozumný rozsah
    norm01 = np.clip(norm01, 0.0, 1.0) ** gamma

    # zpátky do původního dtype rozsahu (použijeme uint8 pro zobrazení)
    out = (norm01 * 255.0).round().astype(np.uint8)

    return out
