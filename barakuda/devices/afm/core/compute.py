"""AFM compute profile resolution."""

import logging

logger = logging.getLogger(__name__)

def get_runtime_info() -> dict:
    """Return AFM runtime info for PyTorch, CUDA, and Cellpose."""
    info = {
        "torch_version": "unknown",
        "cuda_available": False,
        "gpu_name": "unknown",
        "torch_cuda_ready": False,
        "torch_cuda_error": "",
        "cellpose_version": "unknown",
    }

    try:
        import torch
        info["torch_version"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["gpu_name"] = str(torch.cuda.get_device_name(0))
            try:
                probe = torch.empty((1,), device="cuda")
                info["torch_cuda_ready"] = bool(probe.is_cuda)
            except Exception as exc:
                info["torch_cuda_ready"] = False
                info["torch_cuda_error"] = str(exc)
    except ImportError:
        logger.debug("PyTorch not installed, fallback logic will trigger.")
    except Exception:
        pass

    try:
        import importlib.metadata as md
        info["cellpose_version"] = md.version("cellpose")
    except Exception:
        try:
            import cellpose
            info["cellpose_version"] = getattr(cellpose, "__version__", "unknown")
        except ImportError:
            pass

    return info


def resolve_compute_profile(profile: str) -> dict:
    """Resolve requested AFM compute profile to an explicit runtime path."""
    requested = str(profile or "auto").strip().lower()
    if requested not in {"auto", "gpu", "cpu"}:
        logger.warning("Unknown compute profile '%s', defaulting to 'auto'", requested)
        requested = "auto"

    runtime = get_runtime_info()
    gpu_runtime_supported = bool(runtime["torch_cuda_ready"])

    if requested == "cpu":
        resolved_profile = "cpu"
        resolved_device = "cpu"
        fallback_applied = False
        fallback_reason = "Explicit CPU profile selected."
    elif gpu_runtime_supported:
        resolved_profile = "gpu"
        resolved_device = "cuda"
        fallback_applied = False
        fallback_reason = ""
    elif not runtime["cuda_available"]:
        resolved_profile = "cpu"
        resolved_device = "cpu"
        fallback_applied = requested == "gpu"
        fallback_reason = "CUDA not available; falling back to CPU."
    elif not runtime["torch_cuda_ready"]:
        resolved_profile = "cpu"
        resolved_device = "cpu"
        fallback_applied = requested in {"auto", "gpu"}
        fallback_reason = (
            "Torch CUDA runtime is not ready; "
            f"falling back to CPU. {runtime['torch_cuda_error']}".strip()
        )
    else:
        resolved_profile = "cpu"
        resolved_device = "cpu"
        fallback_applied = requested in {"auto", "gpu"}
        fallback_reason = "GPU execution is not available; falling back to CPU."

    return {
        "requested_profile": requested,
        "resolved_profile": resolved_profile,
        "resolved_device": resolved_device,
        "gpu_runtime_supported": gpu_runtime_supported,
        "fallback_applied": fallback_applied,
        "fallback_reason": fallback_reason,
        "backend": "cellpose",
        **runtime,
    }


def resolve_device(profile: str) -> dict:
    """Legacy compatibility wrapper for older AFM call sites."""
    resolved = resolve_compute_profile(profile)
    return {
        "compute_profile": resolved["requested_profile"],
        "device": resolved["resolved_device"],
        "gpu_name": resolved["gpu_name"],
        "torch_version": resolved["torch_version"],
        "cellpose_version": resolved["cellpose_version"],
        "requested_profile": resolved["requested_profile"],
        "resolved_profile": resolved["resolved_profile"],
        "resolved_device": resolved["resolved_device"],
        "gpu_runtime_supported": resolved["gpu_runtime_supported"],
        "fallback_applied": resolved["fallback_applied"],
        "fallback_reason": resolved["fallback_reason"],
        "backend": resolved["backend"],
    }
