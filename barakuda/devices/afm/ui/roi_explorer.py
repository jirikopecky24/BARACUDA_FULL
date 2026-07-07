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


def _repo_root() -> Path:
    """Return repository root resolved from this source file."""
    return Path(__file__).resolve().parents[4]


def _default_roi_dir() -> Path:
    """Return the validated aligned ROI directory relative to repo root."""
    return _repo_root() / "diagnostics" / "afm_jpk_qi" / "1-prct-AG-10x10-512x512" / "aligned_roi_all_channels"


DEFAULT_CHANNEL_PATHS: dict[str, Path] = {
    "Page 5 height calibrated": _default_roi_dir() / "page5_height_leveled_roi_nm.npy",
    "Page 4 measuredHeight nominal": _default_roi_dir() / "page4_measuredHeight_leveled_roi_nm.npy",
}

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
        self.resize(1400, 850)
        self.setMinimumSize(900, 600)

        self._channels: dict[str, np.ndarray | None] = {}
        self._current_key: str = ""
        self._shape: tuple[int, int] | None = None
        self._profile_line: pg.InfiniteLine | None = None
        self._updating_profile_line: bool = False

        self._build_ui()

    def _build_ui(self) -> None:
        main = QHBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(splitter)

        # ── Left: 2D map ───────────────────────────────────────────────
        map_panel = QWidget()
        map_panel.setMinimumSize(520, 420)
        map_layout = QVBoxLayout(map_panel)
        map_layout.setContentsMargins(0, 0, 0, 0)

        self._img_view = pg.ImageView()
        self._img_view.ui.histogram.gradient.loadPreset("viridis")
        self._img_view.setMinimumSize(480, 360)
        map_layout.addWidget(self._img_view)

        splitter.addWidget(map_panel)

        # ── Right: controls + profile ──────────────────────────────────
        right = QWidget()
        right.setMinimumWidth(320)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # Load group
        load_group = QGroupBox("Data")
        load_layout = QVBoxLayout(load_group)
        load_layout.setSpacing(8)

        self._btn_load_demo = QPushButton("Load validated demo ROI")
        self._btn_load_demo.setStyleSheet("font-weight: 600;")
        self._btn_load_demo.clicked.connect(self._load_demo_rois)
        load_layout.addWidget(self._btn_load_demo)

        manual_layout = QHBoxLayout()
        self._btn_load_page5 = QPushButton("Load Page 5…")
        self._btn_load_page5.clicked.connect(self._browse_page5)
        manual_layout.addWidget(self._btn_load_page5)

        self._btn_load_page4 = QPushButton("Load Page 4…")
        self._btn_load_page4.clicked.connect(self._browse_page4)
        manual_layout.addWidget(self._btn_load_page4)
        load_layout.addLayout(manual_layout)

        self._lbl_loaded = QLabel("No ROI loaded.")
        self._lbl_loaded.setWordWrap(True)
        load_layout.addWidget(self._lbl_loaded)

        self._lbl_roi_info = QLabel(
            "This v0 viewer loads validated ROI .npy arrays, not raw .jpk-qi-data yet."
        )
        self._lbl_roi_info.setWordWrap(True)
        self._lbl_roi_info.setStyleSheet("color: #666; font-size: 11px;")
        load_layout.addWidget(self._lbl_roi_info)

        self._btn_raw_jpk = QPushButton("Raw JPK/QI loading — future")
        self._btn_raw_jpk.setToolTip("Raw JPK/QI loading will be added in a later step.")
        self._btn_raw_jpk.setEnabled(False)
        load_layout.addWidget(self._btn_raw_jpk)

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

        self._btn_refresh = QPushButton("Refresh now")
        self._btn_refresh.setEnabled(False)
        self._btn_refresh.clicked.connect(self._refresh_profile)
        profile_form.addRow(self._btn_refresh)

        self._lbl_drag_hint = QLabel("Drag the red cut line or edit the index.")
        self._lbl_drag_hint.setWordWrap(True)
        self._lbl_drag_hint.setStyleSheet("color: #666; font-size: 11px;")
        profile_form.addRow(self._lbl_drag_hint)

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
        splitter.setSizes([920, 360])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)

        # ── Bottom/right profile plot ──────────────────────────────────
        self._profile_plot = pg.PlotWidget()
        self._profile_plot.setMinimumHeight(160)
        self._profile_plot.setLabel("bottom", "Distance", units="µm")
        self._profile_plot.setLabel("left", "Height", units="nm")
        self._profile_curve = self._profile_plot.plot(pen=pg.mkPen("y", width=2))
        right_layout.addWidget(self._profile_plot, stretch=1)

    # ── Loading ───────────────────────────────────────────────────────

    def _browse_page5(self) -> None:
        self._load_channel(
            "Page 5 height calibrated",
            self._btn_load_page5,
        )

    def _browse_page4(self) -> None:
        self._load_channel(
            "Page 4 measuredHeight nominal",
            self._btn_load_page4,
        )

    def _default_dir_str(self) -> str:
        roi_dir = _default_roi_dir()
        return str(roi_dir) if roi_dir.is_dir() else ""

    def _load_demo_rois(self) -> None:
        """Auto-load both validated demo ROI arrays relative to repo root."""
        missing: list[str] = []
        loaded: list[str] = []

        for label, path in DEFAULT_CHANNEL_PATHS.items():
            if not path.is_file():
                missing.append(str(path.name))
                continue
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
            loaded.append(path.name)

        if missing:
            self._lbl_loaded.setText(
                "Validated ROI arrays not found. Run the AFM JPK/QI loading validation pipeline first.\n"
                f"Missing: {', '.join(missing)}"
            )
            return

        self._btn_load_page5.setText(f"Loaded {DEFAULT_CHANNEL_PATHS['Page 5 height calibrated'].name}")
        self._btn_load_page4.setText(f"Loaded {DEFAULT_CHANNEL_PATHS['Page 4 measuredHeight nominal'].name}")
        self._lbl_loaded.setText(
            f"Loaded {len(loaded)} demo ROI arrays:\n" + "\n".join(loaded)
        )
        self._populate_channel_selector()

    def _load_channel(self, label: str, button: QPushButton, *, path: Path | None = None) -> None:
        if path is None:
            path_str, _ = QFileDialog.getOpenFileName(
                self,
                f"Load {label}",
                self._default_dir_str(),
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

        # Pixel-based image coordinates: simplest stable v0 mapping.
        # Profile plot distances stay in physical units (um).
        self._img_view.setImage(arr, axes={"x": 1, "y": 0})

        rows, cols = arr.shape
        self._shape = (rows, cols)
        mode = self._cb_profile_mode.currentText()
        if mode == "horizontal row":
            self._spin_index.setRange(0, max(0, rows - 1))
        else:
            self._spin_index.setRange(0, max(0, cols - 1))

        self._refresh_profile()

    def _update_profile_line(self) -> None:
        """Update or create the InfiniteLine overlay showing the current profile cut.

        ImageView is kept in pixel coordinates, so line positions are plain
        row/column indices. Profile plot distances remain in physical um.
        """
        if self._shape is None:
            return
        mode = self._cb_profile_mode.currentText()
        idx = self._spin_index.value()
        rows, cols = self._shape

        if mode == "horizontal row":
            if not (0 <= idx < rows):
                return
            angle = 0  # horizontal line
            pos = float(idx)
        else:
            if not (0 <= idx < cols):
                return
            angle = 90  # vertical line
            pos = float(idx)

        if self._profile_line is None:
            self._profile_line = pg.InfiniteLine(
                pos=pos,
                angle=angle,
                pen=pg.mkPen("r", width=2),
                movable=True,
            )
            self._profile_line.sigPositionChangeFinished.connect(self._on_line_dragged)
            self._img_view.getView().addItem(self._profile_line)
        else:
            self._updating_profile_line = True
            try:
                self._profile_line.setAngle(angle)
                self._profile_line.setPos(pos)
            finally:
                self._updating_profile_line = False

    def _on_line_dragged(self) -> None:
        """Sync spinbox index when the user drags the profile cut line."""
        if self._updating_profile_line or self._profile_line is None or self._shape is None:
            return
        mode = self._cb_profile_mode.currentText()
        rows, cols = self._shape
        raw_pos = self._profile_line.value()
        pos = float(raw_pos) if not isinstance(raw_pos, (list, tuple, np.ndarray)) else float(raw_pos[0])

        if mode == "horizontal row":
            limit = rows - 1
        else:
            limit = cols - 1
        clamped = max(0.0, min(pos, float(limit)))
        idx = int(round(clamped))

        self._spin_index.blockSignals(True)
        self._spin_index.setValue(idx)
        self._spin_index.blockSignals(False)
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
        self._update_profile_line()


def launch_afm_roi_explorer() -> AfmRoiExplorer:
    """Create and show the AFM ROI Explorer widget (standalone, no main window)."""
    widget = AfmRoiExplorer()
    widget.show()
    return widget
