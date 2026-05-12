"""Startup/mode smoke tests — BARAKUDA CP01.

Covers:
- _apply_mode_device_filter logic for all three modes and the unknown-mode fallback.
- Safe importability of all launcher modules (no QApplication, no GUI, no hardware).

All tests are headless and hardware-free.
"""

import pytest

from barakuda.devices.base import DeviceSpec
from barakuda.shell.main_window import _apply_mode_device_filter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(device_id: str) -> DeviceSpec:
    """Create a minimal fake DeviceSpec for filter testing.

    create_panel is never called by _apply_mode_device_filter, so
    lambda: None is safe here.
    """
    return DeviceSpec(device_id=device_id, display_name=device_id, create_panel=lambda: None)


_ALL_DEVICES = [
    _make_spec("optical_tweezers"),
    _make_spec("afm"),
    _make_spec("acquisition"),
]


def _ids(devices):
    return [d.device_id for d in devices]


# ---------------------------------------------------------------------------
# Filter logic tests
# ---------------------------------------------------------------------------

def test_full_mode_keeps_all_devices():
    result = _apply_mode_device_filter(_ALL_DEVICES, "full")
    assert _ids(result) == ["optical_tweezers", "afm", "acquisition"]


def test_acquisition_mode_keeps_only_acquisition():
    result = _apply_mode_device_filter(_ALL_DEVICES, "acquisition")
    assert _ids(result) == ["acquisition"]


def test_analysis_mode_excludes_acquisition():
    result = _apply_mode_device_filter(_ALL_DEVICES, "analysis")
    assert _ids(result) == ["optical_tweezers", "afm"]


def test_unknown_mode_falls_back_to_full_list():
    result = _apply_mode_device_filter(_ALL_DEVICES, "unknown_mode")
    assert _ids(result) == ["optical_tweezers", "afm", "acquisition"]


def test_full_mode_preserves_original_order():
    """Confirm full mode is a pass-through that does not reorder devices."""
    result = _apply_mode_device_filter(_ALL_DEVICES, "full")
    assert result is _ALL_DEVICES  # same object returned, no copy


def test_acquisition_mode_with_no_acquisition_device_returns_empty():
    """If list_devices() cannot import Acquisition, acquisition mode gives []."""
    devices_without_acq = [_make_spec("optical_tweezers"), _make_spec("afm")]
    result = _apply_mode_device_filter(devices_without_acq, "acquisition")
    assert result == []


def test_analysis_mode_with_no_acquisition_device_returns_unchanged():
    """Analysis mode on a list with no acquisition device is a no-op."""
    devices_without_acq = [_make_spec("optical_tweezers"), _make_spec("afm")]
    result = _apply_mode_device_filter(devices_without_acq, "analysis")
    assert _ids(result) == ["optical_tweezers", "afm"]


# ---------------------------------------------------------------------------
# Launcher import safety tests
# ---------------------------------------------------------------------------

def test_import_main():
    import main  # noqa: F401


def test_import_barakuda_main():
    import barakuda.main  # noqa: F401


def test_import_main_acquisition():
    import main_acquisition  # noqa: F401


def test_import_main_analysis():
    import main_analysis  # noqa: F401


def test_import_barakuda_startup():
    import barakuda.startup  # noqa: F401
