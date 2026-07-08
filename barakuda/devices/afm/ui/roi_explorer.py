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
    QSlider,
)

# Optional scikit-image imports: used for exploratory QA masks only.
try:
    from skimage.filters import threshold_otsu, threshold_local

    _SKIMAGE_AVAILABLE = True
except Exception:  # pragma: no cover
    threshold_otsu = None  # type: ignore[assignment]
    threshold_local = None  # type: ignore[assignment]
    _SKIMAGE_AVAILABLE = False


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
        self._overlay_item: pg.ImageItem | None = None
        self._mask_array: np.ndarray | None = None
        self._profile_mask_regions: list[pg.LinearRegionItem] = []

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

        # Mask overlay group (exploratory QA only)
        mask_group = QGroupBox("Mask overlay (exploratory QA)")
        mask_layout = QVBoxLayout(mask_group)
        mask_layout.setSpacing(6)

        self._cb_mask = QComboBox()
        self._cb_mask.setToolTip(
            "Select an in-memory exploratory mask. No mask is saved or used for final metrics."
        )
        self._cb_mask.addItem("None")
        self._cb_mask.addItem("Page 5 P20 depression")
        if _SKIMAGE_AVAILABLE:
            self._cb_mask.addItem("Page 5 Otsu depression")
        self._cb_mask.addItem("Page 5 P30 depression")
        if _SKIMAGE_AVAILABLE:
            self._cb_mask.addItem("Page 5 local/adaptive exploratory")
        self._cb_mask.addItem("Page 4 P20 depression")
        if _SKIMAGE_AVAILABLE:
            self._cb_mask.addItem("Page 4 Otsu depression")
        self._cb_mask.addItem("Page 4 P30 depression")
        if _SKIMAGE_AVAILABLE:
            self._cb_mask.addItem("Page 4 local/adaptive exploratory")
        self._cb_mask.setEnabled(False)
        self._cb_mask.currentTextChanged.connect(self._on_mask_changed)
        mask_layout.addWidget(self._cb_mask)

        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("Opacity:"))
        self._slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self._slider_opacity.setRange(0, 100)
        self._slider_opacity.setValue(40)
        self._slider_opacity.setEnabled(False)
        self._slider_opacity.valueChanged.connect(self._update_overlay_opacity)
        opacity_layout.addWidget(self._slider_opacity)
        self._lbl_opacity_value = QLabel("40%")
        opacity_layout.addWidget(self._lbl_opacity_value)
        mask_layout.addLayout(opacity_layout)

        self._lbl_mask_warning = QLabel(
            "Mask overlay is exploratory QA only — no porosity or pore metrics."
        )
        self._lbl_mask_warning.setWordWrap(True)
        self._lbl_mask_warning.setStyleSheet("color: #c60; font-size: 11px;")
        mask_layout.addWidget(self._lbl_mask_warning)

        self._lbl_mask_status = QLabel("No mask selected.")
        self._lbl_mask_status.setWordWrap(True)
        self._lbl_mask_status.setStyleSheet("color: #666; font-size: 11px;")
        mask_layout.addWidget(self._lbl_mask_status)

        right_layout.addWidget(mask_group)

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

        self._lbl_profile_mask_note = QLabel(
            "Profile mask marks are QA-only visual intersections, not metrics."
        )
        self._lbl_profile_mask_note.setWordWrap(True)
        self._lbl_profile_mask_note.setStyleSheet("color: #c60; font-size: 11px;")
        profile_form.addRow(self._lbl_profile_mask_note)

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
        self._cb_mask.setEnabled(True)
        self._slider_opacity.setEnabled(True)
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

    def _update_index_range(self) -> None:
        """Set spinbox range from the active image shape and clamp the index.

        Profile index limits are derived from the active image shape;
        do not hard-code ROI dimensions.
        """
        if self._shape is None:
            self._spin_index.setRange(0, 0)
            return
        mode = self._cb_profile_mode.currentText()
        rows, cols = self._shape
        if mode == "horizontal row":
            max_index = max(0, rows - 1)
        else:
            max_index = max(0, cols - 1)

        self._spin_index.blockSignals(True)
        self._spin_index.setRange(0, max_index)
        current = self._spin_index.value()
        if current > max_index:
            self._spin_index.setValue(max_index)
        elif current < 0:
            self._spin_index.setValue(0)
        self._spin_index.blockSignals(False)

    def _refresh_profile(self) -> None:
        if not self._current_key:
            return
        arr = self._channels.get(self._current_key)
        if arr is None or self._shape is None:
            return

        # Profile index limits are derived from the active image shape;
        # do not hard-code ROI dimensions.
        self._update_index_range()

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
        self._update_profile_mask_marks()

    def _clear_profile_mask_regions(self) -> None:
        """Remove all QA mask intersection bands from the profile plot."""
        for region in self._profile_mask_regions:
            self._profile_plot.removeItem(region)
        self._profile_mask_regions.clear()

    def _find_true_intervals(self, mask_1d: np.ndarray) -> list[tuple[int, int]]:
        """Return half-open [start, end) index intervals where mask_1d is True.

        Merging consecutive True samples is visualization-only: it reduces the
        number of drawn bands without changing which samples are highlighted.
        No counts, lengths, fractions, or other metrics are computed or stored.
        """
        if not mask_1d.any():
            return []
        edges = np.where(np.diff(mask_1d.astype(np.int8)) != 0)[0]
        intervals: list[tuple[int, int]] = []
        if mask_1d[0]:
            start = 0
        else:
            start = None
        for edge in edges:
            if mask_1d[edge] and not mask_1d[edge + 1]:
                # True -> False: close interval at edge+1 (exclusive)
                if start is not None:
                    intervals.append((start, edge + 1))
                    start = None
            elif not mask_1d[edge] and mask_1d[edge + 1]:
                # False -> True: open interval
                start = edge + 1
        if start is not None and mask_1d[-1]:
            intervals.append((start, len(mask_1d)))
        return intervals

    def _update_profile_mask_marks(self) -> None:
        """Show where the active exploratory mask intersects the current profile.

        Uses the current mask array and the active profile row/column. Draws
        semi-transparent background bands in the profile plot. No metrics are
        computed or displayed.
        """
        self._clear_profile_mask_regions()

        if self._mask_array is None or self._shape is None:
            return

        # Safety: the mask must match the active image shape.
        if self._mask_array.shape != self._shape:
            self._lbl_mask_status.setText(
                "Mask/image shape mismatch — profile intersection not shown.\n"
                "exploratory only"
            )
            return

        mode = self._cb_profile_mode.currentText()
        idx = self._spin_index.value()
        rows, cols = self._shape

        if mode == "horizontal row":
            if not (0 <= idx < rows):
                return
            mask_1d = self._mask_array[idx, :]
            n_samples = cols
        else:
            if not (0 <= idx < cols):
                return
            mask_1d = self._mask_array[:, idx]
            n_samples = rows

        # Only render if the 1D mask has any True samples.
        if not mask_1d.any():
            return

        intervals = self._find_true_intervals(mask_1d)
        if not intervals:
            return

        for start, end in intervals:
            x0 = start * UM_PER_PX
            x1 = end * UM_PER_PX
            region = pg.LinearRegionItem(
                values=(x0, x1),
                orientation="vertical",
                brush=pg.mkBrush(255, 0, 0, 60),
                pen=pg.mkPen(None),
                movable=False,
            )
            # Keep the band behind the profile curve.
            region.setZValue(-100)
            self._profile_plot.addItem(region)
            self._profile_mask_regions.append(region)

    # ── Mask overlay (exploratory QA only) ────────────────────────────

    def _on_mask_changed(self) -> None:
        """Regenerate and display the selected exploratory mask overlay."""
        mask_name = self._cb_mask.currentText()
        if not mask_name or mask_name == "None":
            self._mask_array = None
            self._clear_overlay()
            self._clear_profile_mask_regions()
            self._lbl_mask_status.setText("No mask selected.")
            return

        source_key, method = self._parse_mask_name(mask_name)
        arr = self._channels.get(source_key)
        if arr is None:
            self._mask_array = None
            self._clear_overlay()
            self._clear_profile_mask_regions()
            self._lbl_mask_status.setText(f"Source channel {source_key!r} not loaded.")
            return

        mask, threshold = self._generate_mask(arr, method)
        self._mask_array = mask
        self._update_overlay_display()
        self._update_profile_mask_marks()

        threshold_str = f"{threshold:.3f} nm" if threshold is not None else "N/A"
        self._lbl_mask_status.setText(
            f"Mask: {mask_name}\n"
            f"Source: {source_key}\n"
            f"Threshold: {threshold_str}\n"
            f"Profile intersection shown visually only.\n"
            f"exploratory only"
        )

    def _parse_mask_name(self, name: str) -> tuple[str, str]:
        """Return (source channel label, method token) from mask selector text."""
        if name.startswith("Page 5"):
            source = "Page 5 height calibrated"
            method = name[len("Page 5 "):].strip()
        elif name.startswith("Page 4"):
            source = "Page 4 measuredHeight nominal"
            method = name[len("Page 4 "):].strip()
        else:
            source = self._current_key or ""
            method = name
        return source, method

    def _generate_mask(self, arr: np.ndarray, method: str) -> tuple[np.ndarray, float | None]:
        """Create a boolean depression mask in memory. No labels, no metrics.

        Polarity is always depression: mask = Z <= threshold.
        """
        z = arr.astype(np.float64, copy=False)
        if method == "P20 depression":
            threshold = float(np.nanpercentile(z, 20))
            mask = z <= threshold
        elif method == "P30 depression":
            threshold = float(np.nanpercentile(z, 30))
            mask = z <= threshold
        elif method == "Otsu depression":
            finite = z[np.isfinite(z)]
            if _SKIMAGE_AVAILABLE and threshold_otsu is not None and finite.size > 0:
                threshold = float(threshold_otsu(finite))
            else:
                threshold = float(np.nanmedian(z))
            mask = z <= threshold
        elif method == "local/adaptive exploratory":
            finite = z[np.isfinite(z)]
            if _SKIMAGE_AVAILABLE and threshold_local is not None and finite.size > 0:
                # Conservative default: block size ~1/8 of smaller ROI dimension,
                # rounded to an odd integer >= 3.
                block = max(3, min(z.shape) // 8)
                if block % 2 == 0:
                    block += 1
                # Replace NaNs temporarily with median so threshold_local can run.
                med = float(np.nanmedian(z))
                z_filled = np.where(np.isfinite(z), z, med)
                threshold = threshold_local(z_filled, block_size=block, method="gaussian")
                mask = z <= threshold
                threshold = float(np.mean(threshold))
            else:
                threshold = float(np.nanpercentile(z, 25))
                mask = z <= threshold
        else:
            threshold = None
            mask = np.zeros_like(z, dtype=bool)

        mask = np.asarray(mask, dtype=bool)
        # Ensure NaN source pixels are not counted as mask pixels.
        mask &= np.isfinite(z)
        return mask, threshold

    def _update_overlay_opacity(self) -> None:
        """Refresh overlay when the opacity slider moves."""
        opacity = self._slider_opacity.value()
        self._lbl_opacity_value.setText(f"{opacity}%")
        self._update_overlay_display()

    def _update_overlay_display(self) -> None:
        """Render the current mask array as a transparent red overlay."""
        if self._mask_array is None or self._shape is None:
            self._clear_overlay()
            return

        opacity = self._slider_opacity.value() / 100.0
        rows, cols = self._shape
        # RGBA overlay: red where mask is True, transparent elsewhere.
        overlay = np.zeros((rows, cols, 4), dtype=np.uint8)
        overlay[self._mask_array] = [255, 0, 0, int(255 * opacity)]

        if self._overlay_item is None:
            self._overlay_item = pg.ImageItem(overlay, axisOrder="row-major")
            self._img_view.getView().addItem(self._overlay_item)
        else:
            self._overlay_item.setImage(overlay)

        # Keep profile line on top of overlay.
        if self._profile_line is not None:
            self._profile_line.setZValue(1000)

    def _clear_overlay(self) -> None:
        """Remove the mask overlay from the view."""
        if self._overlay_item is not None:
            self._img_view.getView().removeItem(self._overlay_item)
            self._overlay_item = None


def launch_afm_roi_explorer() -> AfmRoiExplorer:
    """Create and show the AFM ROI Explorer widget (standalone, no main window)."""
    widget = AfmRoiExplorer()
    widget.show()
    return widget
