"""Cellpose model caching module for AFM V2 Pipeline."""
import logging
import numpy as np

logger = logging.getLogger(__name__)

# Module global dict to persist models for application lifetime
_CACHE = {}

def get_cellpose(model_type: str, device: str):
    """
    Get or create a cached Cellpose model.
    Also performs a warmup inference on first creation to avoid alloc overhead later.
    
    Parameters
    ----------
    model_type : str
        Cellpose model type (e.g., 'cyto3').
    device : str
        Target device, either "cuda" or "cpu".
        
    Returns
    -------
    model : cellpose.models.Cellpose or cellpose.models.CellposeModel
        The requested model.
    """
    key = (model_type, device)
    
    if key in _CACHE:
        return _CACHE[key]
        
    gpu_flag = (device == "cuda")
    
    try:
        from cellpose import models as cp_models
        import cellpose as _cellpose_pkg
    except ImportError:
        raise RuntimeError("Cellpose is not installed.")
        
    _CELLPOSE_VERSION = getattr(_cellpose_pkg, "__version__", "unknown")
    is_v4 = _CELLPOSE_VERSION and str(_CELLPOSE_VERSION).startswith("4")
    
    logger.info(f"Creating new Cellpose model (type={model_type}, gpu={gpu_flag})")
    
    if is_v4:
        m = cp_models.CellposeModel(model_type=model_type, gpu=gpu_flag)
    elif hasattr(cp_models, "Cellpose"):
        m = cp_models.Cellpose(model_type=model_type, gpu=gpu_flag)
    else:
        m = cp_models.CellposeModel(model_type=model_type, gpu=gpu_flag)
        
    # Warmup
    logger.info("Running Cellpose warmup...")
    dummy = np.zeros((64, 64), dtype=np.float32)
    try:
        eval_kwargs = {"diameter": 20}
        if not is_v4:
            eval_kwargs["channels"] = [0, 0]
        m.eval(dummy, **eval_kwargs)
        logger.info("Cellpose warmup done.")
    except Exception as e:
        logger.warning(f"Cellpose warmup failed: {e}")
        
    _CACHE[key] = m
    return m
