"""AFM Core Compute Utilities for intelligent hardware fallback."""

import logging

logger = logging.getLogger(__name__)

def get_versions() -> dict:
    """Return dictionary of hardware versions for PyTorch, CUDA, and Cellpose.
    
    Prioritizes importlib.metadata for Cellpose to guarantee auditing accuracy.
    """
    versions = {
        "torch_version": "unknown",
        "cuda_available": False,
        "gpu_name": "unknown",
        "cellpose_version": "unknown"
    }

    # 1. PyTorch & CUDA
    try:
        import torch
        versions["torch_version"] = torch.__version__
        versions["cuda_available"] = torch.cuda.is_available()
        if versions["cuda_available"]:
            versions["gpu_name"] = torch.cuda.get_device_name(0)
    except ImportError:
        logger.debug("PyTorch not installed, fallback logic will trigger.")

    # 2. Cellpose (require hard importlib check for reproducibility)
    try:
        import importlib.metadata as md
        versions["cellpose_version"] = md.version("cellpose")
    except Exception:
        try:
            import cellpose
            versions["cellpose_version"] = getattr(cellpose, "__version__", "unknown")
        except ImportError:
            pass

    return versions

def resolve_device(profile: str) -> dict:
    """Resolve the requested UI compute profile to a guaranteed device string.
    
    Parameters
    ----------
    profile : str
        The requested mode. Valid inputs: 'auto', 'gpu', 'cpu'.
        
    Returns
    -------
    dict
        Contains `compute_profile`, `device` (either "cuda" or "cpu"), 
        and hardware version metadata.
        
    Raises
    ------
    RuntimeError
        If 'gpu' is strictly requested but CUDA is unavailable.
    """
    profile = profile.lower().strip()
    if profile not in {"auto", "gpu", "cpu"}:
        logger.warning(f"Unknown compute profile '{profile}', defaulting to 'auto'")
        profile = "auto"
        
    versions = get_versions()
    cuda_avail = versions["cuda_available"]
    
    if profile == "gpu" and not cuda_avail:
        raise RuntimeError("GPU profile selected but CUDA not available on this system.")
        
    device = "cuda" if (profile in {"auto", "gpu"} and cuda_avail) else "cpu"
    
    return {
        "compute_profile": profile,
        "device": device,
        **versions
    }
