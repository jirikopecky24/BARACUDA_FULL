from __future__ import annotations

# Backward compatibility alias for Bible v2.1 pipeline
from barakuda.devices.optical_tweezers.strategies.psd_welch import PsdWelchStrategy as PsdLorentzianStrategy

__all__ = ["PsdLorentzianStrategy"]
