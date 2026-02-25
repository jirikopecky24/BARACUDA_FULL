"""Abstract base class for AFM analysis methods."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np


class AfmMethodBase(ABC):
    """Base class for all AFM analysis methods.

    Each method encapsulates:
    - Pipeline compute logic
    - Default parameter set
    - Method display name for UI
    """

    # Subclasses must set these
    METHOD_ID: str = ""
    DISPLAY_NAME: str = ""

    @abstractmethod
    def compute(
        self,
        image: np.ndarray,
        params: Any,
    ) -> dict:
        """Run the analysis pipeline.

        Args:
            image: Input image (2D float or uint8).
            params: Method-specific parameter object.

        Returns:
            Result dict (labels, rod_table, audit, etc.)
        """
        ...

    @abstractmethod
    def get_default_params(self) -> dict:
        """Return default UI parameter values for this method."""
        ...
