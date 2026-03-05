"""Camera factory — enumerate all available devices and instantiate backends.

Usage
-----
    from barakuda.devices.acquisition.camera_factory import enumerate_all, create

    devices = enumerate_all()          # list[CameraDeviceInfo]
    camera  = create(devices[0])       # AbstractCamera, already connected

Adding a new backend
--------------------
1. Write ``MyCamera(AbstractCamera)`` in a new file.
2. Add ``"mybackend": MyCamera`` to ``_REGISTRY`` below.
That's it — the selection dialog will show it automatically.
"""
from __future__ import annotations

from barakuda.devices.acquisition.camera_base import AbstractCamera, CameraDeviceInfo

# Registry maps backend name -> class.  Import lazily so missing SDKs don't
# break the whole application at startup.
_REGISTRY: dict[str, str] = {
    "basler": "barakuda.devices.acquisition.camera.BaslerCamera",
    "webcam": "barakuda.devices.acquisition.webcam_camera.WebcamCamera",
}


def _load_class(dotted_path: str):
    """Import and return a class given its dotted module path."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def enumerate_all() -> list[CameraDeviceInfo]:
    """Return every camera visible across all registered backends.

    Individual backend failures are silently swallowed so that a missing SDK
    (e.g. pypylon not installed) never blocks enumeration of other backends.
    """
    results: list[CameraDeviceInfo] = []
    for backend, dotted_path in _REGISTRY.items():
        try:
            cls = _load_class(dotted_path)
            results.extend(cls.enumerate())
        except Exception:
            pass
    return results


def create(info: CameraDeviceInfo) -> AbstractCamera:
    """Instantiate the correct backend for *info* and call ``connect(info)``.

    Returns a connected ``AbstractCamera`` instance.
    Raises ``ValueError`` if the backend is unknown, or re-raises any
    exception from ``connect()`` so the caller can surface it to the user.
    """
    dotted_path = _REGISTRY.get(info.backend)
    if dotted_path is None:
        raise ValueError(
            f"Unknown camera backend '{info.backend}'. "
            f"Registered backends: {list(_REGISTRY)}"
        )
    cls = _load_class(dotted_path)
    cam: AbstractCamera = cls()
    cam.connect(info)
    return cam
