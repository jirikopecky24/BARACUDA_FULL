from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple


class DragPhysicsError(ValueError):
    """Error raised when physical inputs are invalid for DRAG computation."""


def compute_drag_force(eta_pa_s: float, radius_m: float, velocity_m_s: float) -> float:
    """Compute Stokes drag force in SI units.

    F_drag = 6π η R v
    """
    eta = float(eta_pa_s)
    r = float(radius_m)
    v = float(velocity_m_s)
    if not math.isfinite(eta) or eta <= 0:
        raise DragPhysicsError("eta_pa_s must be > 0")
    if not math.isfinite(r) or r <= 0:
        raise DragPhysicsError("radius_m must be > 0")
    if not math.isfinite(v) or v <= 0:
        raise DragPhysicsError("velocity_m_s must be > 0")
    return float(6.0 * math.pi * eta * r * v)


def compute_kappa_from_drag(
    eta_pa_s: float,
    radius_m: float,
    velocity_m_s: float,
    offset_m: float,
) -> float:
    """Compute trap stiffness kappa [N/m] from Stokes drag and steady-state offset.

    kappa = F_drag / Δx
    """
    off = float(offset_m)
    if not math.isfinite(off) or abs(off) <= 0.0:
        raise DragPhysicsError("offset_m must be non-zero and finite")
    f_drag = compute_drag_force(eta_pa_s, radius_m, velocity_m_s)
    return float(f_drag / off)


def compute_eta_from_drag(
    kappa_n_per_m: float,
    radius_m: float,
    velocity_m_s: float,
    offset_m: float,
) -> float:
    """Infer viscosity η [Pa·s] from known kappa, velocity and offset.

    From:
      F_drag = 6π η R v
      F_trap = kappa Δx
      F_drag = F_trap  =>  6π η R v = kappa Δx
      η = (kappa Δx) / (6π R v)
    """
    kappa = float(kappa_n_per_m)
    r = float(radius_m)
    v = float(velocity_m_s)
    off = float(offset_m)
    if not math.isfinite(kappa) or kappa <= 0:
        raise DragPhysicsError("kappa_n_per_m must be > 0")
    if not math.isfinite(r) or r <= 0:
        raise DragPhysicsError("radius_m must be > 0")
    if not math.isfinite(v) or v <= 0:
        raise DragPhysicsError("velocity_m_s must be > 0")
    if not math.isfinite(off) or abs(off) <= 0.0:
        raise DragPhysicsError("offset_m must be non-zero and finite")

    numerator = kappa * off
    denom = 6.0 * math.pi * r * v
    return float(numerator / denom)

