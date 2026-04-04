import pytest


@pytest.mark.ui
def test_acquisition_motion_ui_scaffold_imports_with_pyqt6():
    """Optional scaffold for future widget-level Motion panel tests."""
    pytest.importorskip("PyQt6")
    from barakuda.devices.acquisition.ui.panel import AcquisitionPanel

    assert AcquisitionPanel is not None
