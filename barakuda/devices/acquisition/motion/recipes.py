"""Motion recipes for synchronized DRAG acquisition.

NOW scope: only constant_velocity_drag.
FUTURE: step_response, oscillatory, multi_segment, frequency_sweep — plug in here
without touching orchestration code.

A recipe is a pure data class describing what to do.
Execution is handled by the orchestration layer (see AcquisitionPanel / worker).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ConstantVelocityDragRecipe:
    """Parameters for a single constant-velocity drag pass.

    All physical units are in stage user units (as reported by the controller).
    No physics is computed here — this is purely a motion command specification.
    """
    mode: Literal["constant_velocity_drag"] = "constant_velocity_drag"

    axis: str = "x"                    # "x" or "y"
    direction: int = 1                 # +1 or -1 relative to positive axis
    travel: float = 200.0             # total travel in stage user units
    speed: float = 50.0               # target speed (user units / s)
    accel: float = 100.0              # acceleration (user units / s²)
    decel: float = 100.0              # deceleration (user units / s²)
    pre_delay_s: float = 2.0          # hold time before motion starts
    post_delay_s: float = 2.0         # hold time after motion stops

    # Sign mapping: +1 means positive stage motion corresponds to positive image axis.
    sign_stage_to_image_x: int = 1
    sign_stage_to_image_y: int = 1

    def validate(self) -> list[str]:
        """Return a list of validation error strings (empty = OK)."""
        errors: list[str] = []
        if self.axis not in ("x", "y"):
            errors.append(f"axis must be 'x' or 'y', got {self.axis!r}")
        if self.direction not in (1, -1):
            errors.append(f"direction must be +1 or -1, got {self.direction}")
        if self.travel <= 0:
            errors.append(f"travel must be > 0, got {self.travel}")
        if self.speed <= 0:
            errors.append(f"speed must be > 0, got {self.speed}")
        if self.accel <= 0:
            errors.append(f"accel must be > 0, got {self.accel}")
        if self.decel <= 0:
            errors.append(f"decel must be > 0, got {self.decel}")
        if self.pre_delay_s < 0:
            errors.append(f"pre_delay_s must be >= 0, got {self.pre_delay_s}")
        if self.post_delay_s < 0:
            errors.append(f"post_delay_s must be >= 0, got {self.post_delay_s}")
        if self.sign_stage_to_image_x not in (1, -1):
            errors.append(f"sign_stage_to_image_x must be +1 or -1")
        if self.sign_stage_to_image_y not in (1, -1):
            errors.append(f"sign_stage_to_image_y must be +1 or -1")
        return errors
