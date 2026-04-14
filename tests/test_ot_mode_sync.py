from __future__ import annotations

import sys
import types

if "PyQt6" not in sys.modules:
    _qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    _qtwidgets.QApplication = object
    for _name in (
        "QWidget",
        "QVBoxLayout",
        "QHBoxLayout",
        "QPushButton",
        "QListWidget",
        "QListWidgetItem",
        "QFileDialog",
        "QLabel",
        "QStyle",
        "QSizePolicy",
        "QMessageBox",
        "QListView",
        "QTreeView",
        "QTreeWidget",
        "QTreeWidgetItem",
        "QAbstractItemView",
        "QDialog",
        "QDialogButtonBox",
        "QLineEdit",
        "QCheckBox",
    ):
        setattr(_qtwidgets, _name, object)
    _qtcore = types.ModuleType("PyQt6.QtCore")
    _qtcore.QObject = object
    _qtcore.pyqtSignal = lambda *args, **kwargs: None  # type: ignore[assignment]
    _qtcore.Qt = types.SimpleNamespace()
    _qtcore.QDir = types.SimpleNamespace(Filter=types.SimpleNamespace(Dirs=1, NoDotAndDotDot=2))
    _qtgui = types.ModuleType("PyQt6.QtGui")
    _qtgui.QIcon = object
    _pyqt6 = types.ModuleType("PyQt6")
    _pyqt6.QtWidgets = _qtwidgets
    _pyqt6.QtCore = _qtcore
    _pyqt6.QtGui = _qtgui
    sys.modules["PyQt6"] = _pyqt6
    sys.modules["PyQt6.QtWidgets"] = _qtwidgets
    sys.modules["PyQt6.QtCore"] = _qtcore
    sys.modules["PyQt6.QtGui"] = _qtgui

from barakuda.shell.batch_controller import BatchController
from barakuda.shell.workers.ot_run_worker import MockPanel


def test_resolve_calibration_mode_runtime_maps_drag_to_dragging() -> None:
    post = {"calibration_mode": "Drag"}
    requested, effective = BatchController._resolve_calibration_mode_runtime(post)
    assert requested == "Drag"
    assert effective == "Drag"
    assert post["physics_mode"] == "DRAGGING"
    assert post["effective_calibration_mode_runtime"] == "Drag"


def test_mock_panel_forces_item_mode_to_ui_snapshot() -> None:
    panel = MockPanel(
        dataset_params={
            "run_a.raw": {
                "postprocess": {
                    "calibration_mode": "Brownian",
                    "brownian_baseline_folder": "",
                }
            }
        },
        fallback_tp={},
        fallback_pp={"calibration_mode": "Drag", "brownian_baseline_folder": "C:/baseline"},
        fallback_sp={},
        fallback_fr=(0, 0),
        fallback_output_root="",
    )
    panel.set_current_path("run_a.raw")
    post = panel.get_postprocess_params()
    assert post["requested_calibration_mode_from_ui"] == "Drag"
    assert post["calibration_mode_item_snapshot"] == "Brownian"
    assert post["calibration_mode"] == "Drag"
    assert post["calibration_mode_forced_from_ui"] is True
