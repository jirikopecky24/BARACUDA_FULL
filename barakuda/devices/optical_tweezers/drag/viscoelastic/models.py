from __future__ import annotations

import numpy as np


def g_storage_loss_from_complex(g_star: complex | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split complex modulus into storage (real) and loss (imag)."""
    arr = np.asarray(g_star, dtype=np.complex128)
    return arr.real, arr.imag


def complex_modulus_maxwell(omega_rad_s: float | np.ndarray, G_pa: float, tau_s: float) -> np.ndarray:
    """Maxwell element complex modulus (G0, tau form).

    G*(omega) = G0 * (i*omega*tau)/(1 + i*omega*tau)
    """
    omega = np.asarray(omega_rad_s, dtype=np.float64)
    iwt = 1j * omega * float(tau_s)
    return float(G_pa) * (iwt / (1.0 + iwt))


def complex_modulus_kelvin_voigt(omega_rad_s: float | np.ndarray, E_pa: float, eta_pa_s: float) -> np.ndarray:
    """Kelvin-Voigt element complex modulus.

    G*(omega) = E + i*omega*eta
    """
    omega = np.asarray(omega_rad_s, dtype=np.float64)
    return float(E_pa) + 1j * omega * float(eta_pa_s)


def complex_modulus_sls_zener(
    omega_rad_s: float | np.ndarray,
    G0_pa: float,
    Ginf_pa: float,
    tau_s: float,
) -> np.ndarray:
    """Standard Linear Solid (Zener) complex modulus.

    G*(omega) = Ginf + (G0 - Ginf)/(1 + i*omega*tau)
    """
    omega = np.asarray(omega_rad_s, dtype=np.float64)
    return float(Ginf_pa) + (float(G0_pa) - float(Ginf_pa)) / (1.0 + 1j * omega * float(tau_s))


def complex_modulus_jeffreys(
    omega_rad_s: float | np.ndarray,
    E_pa: float,
    eta2_pa_s: float,
    eta1_pa_s: float,
) -> np.ndarray:
    """Jeffreys model (dashpot in series with Kelvin-Voigt).

    Implemented via complex compliance additivity:
      J*(omega) = 1/(E + i*omega*eta2) + 1/(i*omega*eta1)
      G*(omega) = 1 / J*(omega)
    """
    omega = np.asarray(omega_rad_s, dtype=np.float64)
    j_kv = 1.0 / (float(E_pa) + 1j * omega * float(eta2_pa_s))
    j_d = 1.0 / (1j * omega * float(eta1_pa_s))
    j_total = j_kv + j_d
    return 1.0 / j_total


# --- Placeholder time-domain APIs (for future integrations) ---


def relaxation_modulus_maxwell(t_s: float | np.ndarray, G_pa: float, tau_s: float) -> np.ndarray:
    """Maxwell relaxation modulus: G(t) = G0 * exp(-t/tau)."""
    t = np.asarray(t_s, dtype=np.float64)
    return float(G_pa) * np.exp(-t / float(tau_s))


def creep_compliance_maxwell(t_s: float | np.ndarray, G_pa: float, tau_s: float) -> np.ndarray:
    """Maxwell creep compliance (one common form).

    J(t) = 1/G0 + t/eta, where eta = G0*tau
    """
    t = np.asarray(t_s, dtype=np.float64)
    eta = float(G_pa) * float(tau_s)
    return 1.0 / float(G_pa) + t / eta


def relaxation_modulus_kelvin_voigt(t_s: float | np.ndarray, E_pa: float) -> np.ndarray:
    """Kelvin-Voigt relaxation modulus is constant (stress does not relax)."""
    t = np.asarray(t_s, dtype=np.float64)
    return float(E_pa) * np.ones_like(t)


def creep_compliance_kelvin_voigt(t_s: float | np.ndarray, E_pa: float, eta_pa_s: float) -> np.ndarray:
    """Kelvin-Voigt creep compliance placeholder with the common exponential form.

    J(t) = 1/E * (1 - exp(-t/eta/E)) in one convention.

    NOTE: time-domain conventions differ across rheology references; this is a scaffold.
    """
    t = np.asarray(t_s, dtype=np.float64)
    tau = float(eta_pa_s) / float(E_pa)
    return (1.0 / float(E_pa)) * (1.0 - np.exp(-t / tau))

