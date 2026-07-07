"""
AFM ROI Explorer — minimal 2D ROI viewer + horizontal/vertical profile tool.

Visualization/QA only.
No segmentation, no porosity, no pore metrics, no roughness, no final channel selection.

This widget is intentionally standalone so it can be launched from a development
script without touching the main AFM panel or shell main window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pyqtgraph as pg

pg.setConfigOptions(imageAxisOrder="row-major")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QPushButton,
    QFileDialog,
    QGroupBox,
    QSplitter,
)


UM_PER_PX = 0.01953125
EXPECTED_SHAPE = (300, 472)
PHYSICAL_WIDTH_UM = EXPECTED_SHAPE[1] * UM_PER_PX
PHYSICAL_HEIGHT_UM = EXPECTED_SHAPE[0] * UM_PER_PX


class AfmRoiExplorer(QWidget):
    """
    Standalone widget for inspecting validated AFM ROI arrays.

    Loads one or two .npy arrays (Page 5 height calibrated, Page 4 measuredHeight)
    and shows a 2D map with horizontal/vertical profile plots.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("BARAKUDA AFM ROI Explorer — QA only")
        self.resize(1100, 700)

        self._channels: dict[str, np.ndarray | None] = {}
        self._current_key: str = ""
        self._shape: tuple[int, int] | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        main = QHBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(splitter)

        # ── Left: 2D map ───────────────────────────────────────────────
        map_panel = QWidget()
        map_layout = QVBoxLayout(map_panel)
        map_layout.setContentsMargins(0, 0, 0, 0)

        self._img_view = pg.ImageView()
        self._img_view.ui.histogram.gradient.loadPreset("viridis")
        map_layout.addWidget(self._img_view)

        splitter.addWidget(map_panel)

        # ── Right: controls + profile ──────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # Load group
        load_group = QGroupBox("Data")
        load_form = QFormLayout(load_group)

        self._btn_load_page5 = QPushButton("Load Page 5 height…")
        self._btn_load_page5.clicked.connect(self._browse_page5)
        load_form.addRow("Primary:", self._btn_load_page5)

        self._btn_load_page4 = QPushButton("Load Page 4 measuredHeight…")
        self._btn_load_page4.clicked.connect(self._browse_page4)
        load_form.addRow("Control:", self._btn_load_page4)

        self._lbl_loaded = QLabel("No ROI loaded.")
        self._lbl_loaded.setWordWrap(True)
        load_form.addRow(self._lbl_loaded)

        right_layout.addWidget(load_group)

        # Channel group
        channel_group = QGroupBox("Channel")
        channel_layout = QVBoxLayout(channel_group)

        self._cb_channel = QComboBox()
        self._cb_channel.setEnabled(False)
        self._cb_channel.currentTextChanged.connect(self._on_channel_changed)
        channel_layout.addWidget(self._cb_channel)

        right_layout.addWidget(channel_group)

        # Profile group
        profile_group = QGroupBox("Profile")
        profile_form = QFormLayout(profile_group)

        self._cb_profile_mode = QComboBox()
        self._cb_profile_mode.addItems(["horizontal row", "vertical column"])
        self._cb_profile_mode.setEnabled(False)
        self._cb_profile_mode.currentTextChanged.connect(self._refresh_profile)
        profile_form.addRow("Mode:", self._cb_profile_mode)

        self._spin_index = QSpinBox()
        self._spin_index.setRange(0, 0)
        self._spin_index.setEnabled(False)
        self._spin_index.valueChanged.connect(self._refresh_profile)
        profile_form.addRow("Index:", self._spin_index)

        self._btn_refresh = QPushButton("Refresh profile")
        self._btn_refresh.setEnabled(False)
        self._btn_refresh.clicked.connect(self._refresh_profile)
        profile_form.addRow(self._btn_refresh)

        right_layout.addWidget(profile_group)

        # Metadata group
        meta_group = QGroupBox("Metadata")
        meta_layout = QVBoxLayout(meta_group)

        self._lbl_meta = QLabel(
            f"Expected shape: {EXPECTED_SHAPE} px\n"
            f"Pixel size: {UM_PER_PX} µm/px\n"
            f"Physical ROI: {PHYSICAL_WIDTH_UM:.4f} × {PHYSICAL_HEIGHT_UM:.4f} µm\n"
            "\n"
            "WARNING: diagnostic QA only.\n"
            "No segmentation, porosity, pore metrics, or roughness computed."
        )
        self._lbl_meta.setWordWrap(True)
        meta_layout.addWidget(self._lbl_meta)

        right_layout.addWidget(meta_group)
        right_layout.addStretch(1)

        splitter.addWidget(right)
        splitter.setSizes([700, 360])

        # ── Bottom/right profile plot ──────────────────────────────────
        self._profile_plot = pg.PlotWidget()
        self._profile_plot.setLabel("bottom", "Distance", units="µm")
        self._profile_plot.setLabel("left", "Height", units="nm")
        self._profile_curve = self._profile_plot.plot(pen=pg.mkPen("y", width=2))
        right_layout.addWidget(self._profile_plot, stretch=1)

    # ── Loading ───────────────────────────────────────────────────────

    def _browse_page5(self) -> None:
        self._load_channel(
            "Page 5 height calibrated",
            "page5_height_leveled_roi_nm.npy",
            self._btn_load_page5,
        )

    def _browse_page4(self) -> None:
        self._load_channel(
            "Page 4 measuredHeight nominal",
            "page4_measuredHeight_leveled_roi_nm.npy",
            self._btn_load_page4,
        )

    def _load_channel(self, label: str, default_name: str, button: QPushButton) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            f"Load {label}",
            "",
            "NumPy arrays (*.npy);;All files (*.*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            arr = np.load(path)
        except Exception as exc:  # pragma: no cover
            self._lbl_loaded.setText(f"Failed to load {path.name}: {exc}")
            return

        if arr.ndim != 2:
            self._lbl_loaded.setText(f"{path.name}: expected 2D array, got shape {arr.shape}")
            return

        self._channels[label] = arr
        self._shape = arr.shape
        button.setText(f"Loaded {path.name}")
        self._populate_channel_selector()
        self._lbl_loaded.setText(
            f"Loaded {label}: {arr.shape} px\n"
            f"Physical: {arr.shape[1] * UM_PER_PX:.4f} × {arr.shape[0] * UM_PER_PX:.4f} µm"
        )

    def _populate_channel_selector(self) -> None:
        current = self._cb_channel.currentText()
        self._cb_channel.blockSignals(True)
        self._cb_channel.clear()
        for key in self._channels:
            self._cb_channel.addItem(key)
        if current in self._channels:
            self._cb_channel.setCurrentText(current)
        elif self._channels:
            self._cb_channel.setCurrentIndex(0)
        self._cb_channel.blockSignals(False)
        self._cb_channel.setEnabled(True)
        self._cb_profile_mode.setEnabled(True)
        self._spin_index.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._on_channel_changed()

    def _on_channel_changed(self) -> None:
        key = self._cb_channel.currentText()
        if not key or key not in self._channels:
            return
        self._current_key = key
        arr = self._channels[key]
        if arr is None:
            return

        self._img_view.setImage(
            arr,
            axes={"x": 1, "y": 0},
            scale=(UM_PER_PX, UM_PER_PX),
            pos=(0, 0),
        )

        rows, cols = arr.shape
        self._shape = (rows, cols)
        mode = self._cb_profile_mode.currentText()
        if mode == "horizontal row":
            self._spin_index.setRange(0, max(0, rows - 1))
        else:
            self._spin_index.setRange(0, max(0, cols - 1))

        self._refresh_profile()

    def _refresh_profile(self) -> None:
        if not self._current_key:
            return
        arr = self._channels.get(self._current_key)
        if arr is None or self._shape is None:
            return

        mode = self._cb_profile_mode.currentText()
        idx = self._spin_index.value()
        rows, cols = self._shape

        if mode == "horizontal row":
            if not (0 <= idx < rows):
                return
            profile = arr[idx, :]
            distances = np.arange(cols, dtype=np.float64) * UM_PER_PX
            self._profile_plot.setLabel("bottom", "X distance", units="µm")
        else:
            if not (0 <= idx < cols):
                return
            profile = arr[:, idx]
            distances = np.arange(rows, dtype=np.float64) * UM_PER_PX
            self._profile_plot.setLabel("bottom", "Y distance", units="µm")

        self._profile_curve.setData(distances, profile)


def launch_afm_roi_explorer() -> AfmRoiExplorer:
    """Create and show the AFM ROI Explorer widget (standalone, no main window)."""
    widget = AfmRoiExplorer()
    widget.show()
    return widget
