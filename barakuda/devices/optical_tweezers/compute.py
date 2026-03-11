"""Optical Tweezers compute profile resolution.

This stage wires the requested profile through runtime and audit while
keeping OT execution on the stable CPU path.
"""

from __future__ import annotations


def get_runtime_info() -> dict:
    info = {
        "torch_version": "unknown",
        "cuda_available": False,
        "gpu_name": "unknown",
    }
    try:
        import torch

        info["torch_version"] = getattr(torch, "__version__", "unknown")
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["gpu_name"] = str(torch.cuda.get_device_name(0))
    except ImportError:
        pass
    except Exception:
        pass
    return info


def resolve_compute_profile(profile: str, tracking_method: str = "RADIAL_SYMMETRY") -> dict:
    requested = str(profile or "cpu").strip().lower()
    if requested not in {"auto", "cpu", "gpu"}:
        requested = "cpu"

    runtime = get_runtime_info()
    method = str(tracking_method or "RADIAL_SYMMETRY").strip().upper()
    resolved_profile = "cpu"
    resolved_device = "cpu"

    if requested == "cpu":
        fallback_applied = False
        fallback_reason = "Explicit CPU profile selected."
    elif runtime["cuda_available"]:
        fallback_applied = True
        fallback_reason = (
            f"CUDA device detected ({runtime['gpu_name']}), "
            "but OT mainline runtime currently uses the stable CPU path."
        )
    else:
        fallback_applied = True
        fallback_reason = "CUDA not available; falling back to CPU."

    return {
        "requested_profile": requested,
        "resolved_profile": resolved_profile,
        "resolved_device": resolved_device,
        "gpu_runtime_supported": False,
        "fallback_applied": fallback_applied,
        "fallback_reason": fallback_reason,
        "tracking_method": method,
        **runtime,
    }
