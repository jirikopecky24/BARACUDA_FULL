"""Optical Tweezers compute profile resolution."""

from __future__ import annotations


def get_runtime_info() -> dict:
    info = {
        "torch_version": "unknown",
        "cuda_available": False,
        "gpu_name": "unknown",
        "torch_cuda_ready": False,
        "torch_cuda_error": "",
    }
    try:
        import torch

        info["torch_version"] = getattr(torch, "__version__", "unknown")
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["gpu_name"] = str(torch.cuda.get_device_name(0))
            try:
                _probe = torch.empty((1,), device="cuda")
                info["torch_cuda_ready"] = bool(_probe.is_cuda)
            except Exception as exc:
                info["torch_cuda_ready"] = False
                info["torch_cuda_error"] = str(exc)
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
    gpu_tracking_supported = bool(runtime["torch_cuda_ready"]) and method == "RADIAL_SYMMETRY"

    if requested == "cpu":
        resolved_profile = "cpu"
        resolved_device = "cpu"
        fallback_applied = False
        fallback_reason = "Explicit CPU profile selected."
    elif gpu_tracking_supported:
        resolved_profile = "gpu"
        resolved_device = "cuda"
        fallback_applied = False
        fallback_reason = ""
    elif method != "RADIAL_SYMMETRY":
        resolved_profile = "cpu"
        resolved_device = "cpu"
        fallback_applied = True
        fallback_reason = f"Tracking method {method} currently supports CPU only."
    elif not runtime["cuda_available"]:
        resolved_profile = "cpu"
        resolved_device = "cpu"
        fallback_applied = True
        fallback_reason = "CUDA not available; falling back to CPU."
    elif not runtime["torch_cuda_ready"]:
        resolved_profile = "cpu"
        resolved_device = "cpu"
        fallback_applied = True
        fallback_reason = (
            "Torch CUDA runtime is not ready; "
            f"falling back to CPU. {runtime['torch_cuda_error']}".strip()
        )
    else:
        resolved_profile = "cpu"
        resolved_device = "cpu"
        fallback_applied = True
        fallback_reason = "GPU tracking is not available for the requested configuration."

    return {
        "requested_profile": requested,
        "resolved_profile": resolved_profile,
        "resolved_device": resolved_device,
        "gpu_runtime_supported": gpu_tracking_supported,
        "fallback_applied": fallback_applied,
        "fallback_reason": fallback_reason,
        "tracking_method": method,
        **runtime,
    }
