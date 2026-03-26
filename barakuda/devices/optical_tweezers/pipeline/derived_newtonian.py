import math
import numpy as np
from typing import Optional, Dict, Any

K_B = 1.380649e-23  # J/K

def compute_newtonian_derived(
    fc_hz: float, 
    x_um_series: np.ndarray, 
    temperature_c: float, 
    bead_diameter_um: float, 
    qc_mask: Optional[np.ndarray] = None
) -> Dict[str, Any]:
    """
    Computes derived physical parameters using Newtonian assumptions.
    All scalar values returned in canonical units for Barakuda endpoints.
    """
    if not np.isfinite(fc_hz) or fc_hz <= 0:
        raise ValueError("fc_hz must be positive finite")
    if bead_diameter_um <= 0:
        raise ValueError("bead_diameter_um must be positive")
        
    x = np.asarray(x_um_series, dtype=np.float64)
    if qc_mask is not None:
        x = x[qc_mask]
        
    valid = np.isfinite(x)
    x = x[valid]
    if x.size < 32:
        raise ValueError("Not enough valid samples to compute derived stats")
        
    var_um2 = float(np.var(x, ddof=1))
    if var_um2 <= 0:
        raise ValueError("variance of x_um is <= 0")
        
    T_k = temperature_c + 273.15
    kbt = K_B * T_k
    r_m = (bead_diameter_um / 2.0) * 1e-6
    
    # Stiffness from equipartition
    var_m2 = var_um2 * 1e-12
    k_N_m = kbt / var_m2
    k_pN_um = k_N_m * 1e6
    
    # Gamma from corner frequency: k = 2 * pi * gamma * fc => gamma = k / (2 * pi * fc)
    gamma_N_s_m = k_N_m / (2.0 * math.pi * fc_hz)
    
    # Viscosity from Stokes drag: gamma = 6 * pi * eta * r => eta = gamma / (6 * pi * r)
    eta_Pa_s = gamma_N_s_m / (6.0 * math.pi * r_m)
    
    # Diffusion coefficient from Einstein relation: D = kBT / gamma
    D_m2_s = kbt / gamma_N_s_m
    D_um2_s = D_m2_s * 1e12

    return {
        "status": "OK",
        "fc_hz": float(fc_hz),
        "k_pN_um": float(k_pN_um),
        "eta_Pa_s": float(eta_Pa_s),
        "gamma_Ns_m": float(gamma_N_s_m),
        "D_um2_s": float(D_um2_s),
        "var_um2": float(var_um2),
        "temperature_c": float(temperature_c),
        "bead_diameter_um": float(bead_diameter_um)
    }

def compute_mean_derived(dx: Dict[str, Any], dy: Dict[str, Any], method: str = "median") -> Dict[str, Any]:
    """
    Combines X and Y derived dictionaries.
    Keys matching the physical outputs are averaged by the chosen method.
    """
    out = {"status": "OK"}
    
    if dx.get("status") != "OK" or dy.get("status") != "OK":
        return {"status": "SKIPPED", "reason": "X or Y derived is invalid"}
        
    keys_to_combine = [
        "fc_hz", "k_pN_um", "eta_Pa_s", "gamma_Ns_m", "D_um2_s", "var_um2"
    ]
    
    for k in keys_to_combine:
        vx = dx.get(k)
        vy = dy.get(k)
        if vx is not None and vy is not None:
            if method == "median":
                out[k] = float(np.median([vx, vy]))
            else:
                out[k] = float(np.mean([vx, vy]))
                
    # Copy shared params from dx
    out["temperature_c"] = dx.get("temperature_c")
    out["bead_diameter_um"] = dx.get("bead_diameter_um")
    
    # Calculate ratios
    if dy.get("eta_Pa_s") is not None and dx.get("eta_Pa_s") and dx["eta_Pa_s"] > 0:
        out["eta_ratio_y_x"] = dy["eta_Pa_s"] / dx["eta_Pa_s"]
    if dy.get("k_pN_um") is not None and dx.get("k_pN_um") and dx["k_pN_um"] > 0:
        out["k_ratio_y_x"] = dy["k_pN_um"] / dx["k_pN_um"]
        
    return out
