"""
AcquisitionPanel — self-contained Basler camera acquisition UI.

Embeds live preview (pyqtgraph ImageView) + draggable ROI + controls.
Fully import-guarded: shows a warning when pypylon is not available.
"""
from __future__ import annotations

import json
import os
import time
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QDoubleSpinBox, QSpinBox, QLineEdit,
    QSplitter, QFileDialog, QGroupBox, QScrollArea, QFrame,
    QSlider, QGridLayout, QPlainTextEdit, QComboBox,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox,
    QTabWidget,
)
from PyQt6.QtGui import QFont

import numpy as np
import pyqtgraph as pg

pg.setConfigOptions(imageAxisOrder="row-major")

from barakuda.devices.acquisition.camera import (
    PYPYLON_AVAILABLE,
    BaslerCamera,
    RecordResult,
)
from barakuda.devices.acquisition.camera_base import AbstractCamera
from barakuda.devices.acquisition.camera_factory import enumerate_all, create as create_camera


# ------------------------------------------------------------------ #
#  Scroll-safe spinboxes (wheel events ignored so scrolling the panel
#  doesn't accidentally change parameter values)
# ------------------------------------------------------------------ #

class _NoScrollDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


class _NoScrollSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:
        event.ignore()


# ------------------------------------------------------------------ #
#  Camera selection dialog
# ------------------------------------------------------------------ #

class _CameraSelectDialog(QDialog):
    """Modal dialog listing all available cameras from every registered backend."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Camera")
        self.setMinimumWidth(420)
        self._selected_info = None

        layout = QVBoxLayout(self)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        self._status_label = QLabel("Searching for cameras…")
        layout.addWidget(self._status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setEnabled(False)
        layout.addWidget(buttons)

        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(lambda _: self._on_ok())

        self._populate()

    def _populate(self) -> None:
        self._list.clear()
        devices = enumerate_all()
        if not devices:
            self._status_label.setText("No cameras found.")
            return
        self._status_label.setText(f"{len(devices)} camera(s) found:")
        for info in devices:
            item = QListWidgetItem(str(info))
            item.setData(Qt.ItemDataRole.UserRole, info)
            self._list.addItem(item)
        self._list.setCurrentRow(0)

    def _on_selection_changed(self) -> None:
        selected = self._list.selectedItems()
        self._ok_btn.setEnabled(bool(selected))

    def _on_ok(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        self._selected_info = selected[0].data(Qt.ItemDataRole.UserRole)
        self.accept()

    def selected_info(self):
        """Return the chosen CameraDeviceInfo, or None if dialog was cancelled."""
        return self._selected_info


# ------------------------------------------------------------------ #
#  Worker: record in background thread
# ------------------------------------------------------------------ #

class _RecordWorker(QObject):
    """Runs BaslerCamera.record() in a QThread."""

    finished = pyqtSignal(object)   # RecordResult
    error = pyqtSignal(str)
    progress = pyqtSignal(int, float)  # frames, elapsed

    def __init__(
        self, camera: BaslerCamera, output_dir: str, basename: str,
        duration_s: float, roi: tuple, exposure_us: float,
        gain: float | None, fps_hint: float, pixel_format: str,
        rec_format: str = "RAW",
    ) -> None:
        super().__init__()
        self._cam = camera
        self._output_dir = output_dir
        self._basename = basename
        self._duration_s = duration_s
        self._roi = roi
        self._exposure_us = exposure_us
        self._gain = gain
        self._fps_hint = fps_hint
        self._pixel_format = pixel_format
        self._rec_format = rec_format

    def run(self) -> None:
        try:
            rec_fn = self._cam.record_raw if "RAW" in self._rec_format.upper() else self._cam.record
            result = rec_fn(
                output_dir=self._output_dir,
                basename=self._basename,
                duration_s=self._duration_s,
                roi=self._roi,
                exposure_us=self._exposure_us,
                gain=self._gain,
                fps_hint=self._fps_hint,
                pixel_format=self._pixel_format,
                progress_callback=lambda f, t: self.progress.emit(f, t),
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


# ------------------------------------------------------------------ #
#  AcquisitionPanel
# ------------------------------------------------------------------ #

class AcquisitionPanel(QWidget):
    """
    Self-contained acquisition panel.

    Layout (QSplitter):
      Left  — pyqtgraph ImageView (live camera stream) + ROI overlay
      Right — controls (connect, preview, exposure, gain, fps, ROI, record …)
    """

    # Signals for shell integration (minimal)
    value_changed = pyqtSignal()
    # Thread-safe signals from background fps/benchmark threads
    _fps_done_signal = pyqtSignal()
    _fps_result_signal = pyqtSignal(str)   # carries result text for label + status

    # Default recording ROI
    _DEFAULT_ROI_W = 48
    _DEFAULT_ROI_H = 50
    _DEFAULT_ROI_OX = 112
    _DEFAULT_ROI_OY = 24

    # Default sensor (used until camera connects)
    _DEFAULT_SENSOR_W = 640
    _DEFAULT_SENSOR_H = 480

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._camera: AbstractCamera = BaslerCamera()  # default; replaced after dialog
        self._record_thread: QThread | None = None
        self._record_worker: _RecordWorker | None = None

        # Connect thread-safe fps signals to UI slots (always run in main thread)
        self._fps_done_signal.connect(self._on_fps_done)
        self._fps_result_signal.connect(self._on_fps_result)

        # Sensor limits (updated on connect)
        self._sensor_w = self._DEFAULT_SENSOR_W
        self._sensor_h = self._DEFAULT_SENSOR_H
        self._w_inc = 1
        self._h_inc = 1
        self._ox_inc = 1
        self._oy_inc = 1
        self._w_min = 1
        self._h_min = 1

        # Guard against recursive signal updates
        self._roi_sync_lock = False

        # Preview fps tracking
        self._preview_frame_count = 0
        self._preview_fps_timer_start = time.perf_counter()
        self._preview_fps = 0.0
        self._preview_dropped = 0
        self._last_preview_ts_displayed = 0.0

        # Info block state
        self._last_estimated_fps: float | None = None
        self._last_record_result: RecordResult | None = None

        self._build_ui()

        # If pypylon is missing, disable everything and show warning
        if not PYPYLON_AVAILABLE:
            self._set_all_enabled(False)
            self._status.setText(
                "⚠ pypylon not installed.\n"
                "Install Basler Pylon SDK, then: pip install pypylon"
            )
            self._status.setStyleSheet("color: #cc3333; font-weight: bold;")

    # ------------------------------------------------------------------ #
    #  UI Construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- LEFT: Live preview ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)

        self._image_view = pg.ImageView()
        self._image_view.ui.roiBtn.hide()
        self._image_view.ui.menuBtn.hide()
        self._image_view.ui.histogram.hide()
        left_layout.addWidget(self._image_view)

        # ROI overlay
        pen = pg.mkPen(color="r", width=2)
        self._roi_item = pg.ROI(
            [self._DEFAULT_ROI_OX, self._DEFAULT_ROI_OY],
            [self._DEFAULT_ROI_W, self._DEFAULT_ROI_H],
            pen=pen,
            movable=True,
            resizable=False,  # body drag = move only; resize via handles
        )
        # Corner handles (resize both axes)
        self._roi_item.addScaleHandle([1, 1], [0, 0])
        self._roi_item.addScaleHandle([0, 0], [1, 1])
        self._roi_item.addScaleHandle([1, 0], [0, 1])
        self._roi_item.addScaleHandle([0, 1], [1, 0])
        self._image_view.getView().addItem(self._roi_item)
        self._roi_item.sigRegionChangeFinished.connect(self._on_roi_overlay_changed)

        # Info readout under preview
        self._info_text = QPlainTextEdit()
        self._info_text.setReadOnly(True)
        self._info_text.setFont(QFont("Consolas", 9))
        self._info_text.setMaximumHeight(160)
        self._info_text.setStyleSheet(
            "QPlainTextEdit { background: #1e1e1e; color: #cccccc;"
            " border: 1px solid #333; padding: 4px; }"
        )
        self._info_text.setToolTip("Live acquisition summary: device, preview FPS, ROI, record stats.")
        left_layout.addWidget(self._info_text)

        self._splitter.addWidget(left)

        # ---- RIGHT: Controls ----
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setMinimumWidth(340)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)

        # -- Connection --
        grp_conn = QGroupBox("Camera")
        grp_conn_l = QVBoxLayout(grp_conn)
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setToolTip("Connect/disconnect Basler camera (requires pypylon + Pylon SDK).")
        self._btn_connect.clicked.connect(self._on_connect_clicked)
        grp_conn_l.addWidget(self._btn_connect)

        btn_row = QHBoxLayout()
        self._btn_start_preview = QPushButton("Start Preview")
        self._btn_start_preview.setToolTip("Start live preview (full FOV). ROI overlay defines recording crop.")
        self._btn_start_preview.clicked.connect(self._on_start_preview)
        self._btn_start_preview.setEnabled(False)
        btn_row.addWidget(self._btn_start_preview)

        self._btn_stop_preview = QPushButton("Stop Preview")
        self._btn_stop_preview.setToolTip("Stop live preview and release grab loop.")
        self._btn_stop_preview.clicked.connect(self._on_stop_preview)
        self._btn_stop_preview.setEnabled(False)
        btn_row.addWidget(self._btn_stop_preview)
        grp_conn_l.addLayout(btn_row)
        # Settings, ROI, Recording, Status are added to tabs below.
        # -- Settings --
        grp_set = QGroupBox("Settings")
        form = QFormLayout(grp_set)

        self._spin_exposure = _NoScrollDoubleSpinBox()
        self._spin_exposure.setRange(1, 1_000_000)
        self._spin_exposure.setValue(450.0)
        self._spin_exposure.setSuffix(" µs")
        self._spin_exposure.setDecimals(0)
        self._spin_exposure.setToolTip("Camera exposure time in microseconds. Lower exposure allows higher FPS.")
        self._spin_exposure.editingFinished.connect(self._on_exposure_changed)
        form.addRow("Exposure:", self._spin_exposure)

        self._spin_gain = _NoScrollDoubleSpinBox()
        self._spin_gain.setRange(0, 48)
        self._spin_gain.setValue(0.0)
        self._spin_gain.setSuffix(" dB")
        self._spin_gain.setDecimals(1)
        self._spin_gain.setToolTip("Analog/digital gain (if supported). Increases brightness but adds noise.")
        self._spin_gain.editingFinished.connect(self._on_gain_changed)
        form.addRow("Gain:", self._spin_gain)

        self._spin_fps_hint = _NoScrollDoubleSpinBox()
        self._spin_fps_hint.setRange(1, 100_000)
        self._spin_fps_hint.setValue(2000.0)
        self._spin_fps_hint.setDecimals(0)
        self._spin_fps_hint.setSuffix(" fps")
        self._spin_fps_hint.setToolTip("Target FPS hint for metadata. True FPS is measured and saved to meta.json.")
        form.addRow("FPS target hint:", self._spin_fps_hint)

        self._btn_test_fps = QPushButton("Test FPS")
        self._btn_test_fps.setToolTip(
            "Quick ~1s dry-run at current record ROI + exposure\n"
            "to estimate achievable recording FPS."
        )
        self._btn_test_fps.clicked.connect(self._on_test_fps)
        self._btn_test_fps.setEnabled(False)
        form.addRow("", self._btn_test_fps)

        self._btn_benchmark = QPushButton("Benchmark (5s)")
        self._btn_benchmark.setToolTip(
            "5-second dry-run benchmark at current settings.\n"
            "Grabs frames without writing — reports achievable FPS and dropped frames."
        )
        self._btn_benchmark.clicked.connect(self._on_benchmark)
        self._btn_benchmark.setEnabled(False)
        form.addRow("", self._btn_benchmark)

        self._lbl_test_fps_result = QLabel("")
        form.addRow("", self._lbl_test_fps_result)

        # -- ROI (numeric controls + sliders) --
        grp_roi = QGroupBox("Record ROI")
        roi_grid = QGridLayout(grp_roi)
        roi_grid.setContentsMargins(6, 6, 6, 6)
        roi_grid.setHorizontalSpacing(6)
        roi_grid.setVerticalSpacing(4)

        # Column headers
        roi_grid.addWidget(QLabel(""), 0, 0)
        roi_grid.addWidget(QLabel("Value"), 0, 1)
        roi_grid.addWidget(QLabel("Slider"), 0, 2)

        self._roi_spins: dict[str, QSpinBox] = {}
        self._roi_sliders: dict[str, QSlider] = {}

        roi_params = [
            ("W",       "roi_w",  self._DEFAULT_ROI_W,  self._w_min,  self._sensor_w),
            ("H",       "roi_h",  self._DEFAULT_ROI_H,  self._h_min,  self._sensor_h),
            ("OffsetX", "roi_ox", self._DEFAULT_ROI_OX, 0,            self._sensor_w - self._DEFAULT_ROI_W),
            ("OffsetY", "roi_oy", self._DEFAULT_ROI_OY, 0,            self._sensor_h - self._DEFAULT_ROI_H),
        ]

        for row_idx, (label, key, default, mn, mx) in enumerate(roi_params, start=1):
            lbl = QLabel(f"{label}:")
            roi_grid.addWidget(lbl, row_idx, 0)

            spin = _NoScrollSpinBox()
            spin.setRange(mn, max(mn, mx))
            spin.setValue(default)
            spin.setMinimumWidth(70)
            roi_grid.addWidget(spin, row_idx, 1)
            self._roi_spins[key] = spin

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(mn, max(mn, mx))
            slider.setValue(default)
            roi_grid.addWidget(slider, row_idx, 2)
            self._roi_sliders[key] = slider

            # Bidirectional link (with recursion guard)
            spin.valueChanged.connect(lambda v, k=key: self._on_roi_spin_changed(k, v))
            slider.valueChanged.connect(lambda v, k=key: self._on_roi_slider_changed(k, v))

        # ROI tooltips
        _roi_tips = {
            "roi_w":  "Recording ROI width in sensor pixels (snapped to camera increments).",
            "roi_h":  "Recording ROI height in sensor pixels (snapped to camera increments).",
            "roi_ox": "Recording ROI left offset in sensor pixels (snapped).",
            "roi_oy": "Recording ROI top offset in sensor pixels (snapped).",
        }
        for k, tip in _roi_tips.items():
            self._roi_spins[k].setToolTip(tip)
            self._roi_sliders[k].setToolTip(tip)

        # -- Recording --
        grp_rec = QGroupBox("Recording")
        rec_form = QFormLayout(grp_rec)

        self._spin_duration = _NoScrollDoubleSpinBox()
        self._spin_duration.setRange(0, 3600)
        self._spin_duration.setValue(30.0)
        self._spin_duration.setSuffix(" s")
        self._spin_duration.setDecimals(1)
        self._spin_duration.setToolTip("Recording duration in seconds. 0 = record until Stop.")
        rec_form.addRow("Duration:", self._spin_duration)

        dir_row = QHBoxLayout()
        self._edit_output_dir = QLineEdit(r"C:\Work\Video")
        self._edit_output_dir.setToolTip("Folder to save recorded video + <basename>_meta.json.")
        dir_row.addWidget(self._edit_output_dir, 1)
        self._btn_browse = QPushButton("…")
        self._btn_browse.setToolTip("Choose output folder.")
        self._btn_browse.setFixedWidth(32)
        self._btn_browse.clicked.connect(self._on_browse_dir)
        dir_row.addWidget(self._btn_browse)
        rec_form.addRow("Output folder:", dir_row)

        self._edit_basename = QLineEdit(
            time.strftime("Basler_%Y%m%d_%H%M%S")
        )
        self._edit_basename.setToolTip("Base filename (without extension). Timestamp recommended.")
        rec_form.addRow("Basename:", self._edit_basename)

        self._combo_format = QComboBox()
        self._combo_format.addItem("RAW (fast)")
        self._combo_format.addItem("AVI (compat)")
        self._combo_format.setCurrentIndex(0)
        self._combo_format.setToolTip("RAW = raw binary (fastest, no codec overhead). AVI = MJPG container.")
        rec_form.addRow("Format:", self._combo_format)

        rec_btn_row = QHBoxLayout()
        self._btn_record = QPushButton("⏺ Record")
        self._btn_record.setToolTip("Record video + meta.json using current ROI/exposure/gain.")
        self._btn_record.clicked.connect(self._on_record)
        self._btn_record.setEnabled(False)
        rec_btn_row.addWidget(self._btn_record)

        self._btn_stop_record = QPushButton("⏹ Stop")
        self._btn_stop_record.setToolTip("Abort recording safely (closes file, writes partial meta).")
        self._btn_stop_record.clicked.connect(self._on_stop_record)
        self._btn_stop_record.setEnabled(False)
        rec_btn_row.addWidget(self._btn_stop_record)

        self._btn_sim_raw = QPushButton("Sim RAW (5s)")
        self._btn_sim_raw.setToolTip(
            "Generate a simulated 5s RAW recording (no camera needed).\n"
            "Creates .raw + _timestamps.csv + _meta.json + _qc.json."
        )
        self._btn_sim_raw.clicked.connect(self._on_sim_raw)
        rec_btn_row.addWidget(self._btn_sim_raw)
        rec_form.addRow("", rec_btn_row)

        # -- Status --
        grp_status = QGroupBox("Status")
        status_l = QVBoxLayout(grp_status)
        self._status = QLabel("Disconnected")
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        status_l.addWidget(self._status)
        self._status.setToolTip("Connection state, preview FPS, recording progress.")
        # -- Assemble tabs --
        tabs = QTabWidget()

        # Tab 0: Camera (connection + settings)
        tab_camera = QWidget()
        tab_camera_layout = QVBoxLayout(tab_camera)
        tab_camera_layout.setContentsMargins(4, 4, 4, 4)
        tab_camera_layout.addWidget(grp_conn)
        tab_camera_layout.addWidget(grp_set)
        tab_camera_layout.addStretch(1)
        tabs.addTab(tab_camera, "Camera")

        # Tab 1: ROI
        tab_roi = QWidget()
        tab_roi_layout = QVBoxLayout(tab_roi)
        tab_roi_layout.setContentsMargins(4, 4, 4, 4)
        tab_roi_layout.addWidget(grp_roi)
        tab_roi_layout.addStretch(1)
        tabs.addTab(tab_roi, "ROI")

        # Tab 2: Recording
        tab_rec = QWidget()
        tab_rec_layout = QVBoxLayout(tab_rec)
        tab_rec_layout.setContentsMargins(4, 4, 4, 4)
        tab_rec_layout.addWidget(grp_rec)
        tab_rec_layout.addStretch(1)
        tabs.addTab(tab_rec, "Recording")

        # Tab 3: Status
        tab_status = QWidget()
        tab_status_layout = QVBoxLayout(tab_status)
        tab_status_layout.setContentsMargins(4, 4, 4, 4)
        tab_status_layout.addWidget(grp_status)
        tab_status_layout.addStretch(1)
        tabs.addTab(tab_status, "Status")

        right_layout.addWidget(tabs)

        right_scroll.setWidget(right)
        self._splitter.addWidget(right_scroll)

        # Splitter stretch factors: preview=3, controls=2 (~60/40)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)

        root.addWidget(self._splitter)

        # Apply explicit default sizes after the widget is shown
        QTimer.singleShot(0, self._apply_default_splitter_sizes)

        # -- Preview fps update timer --
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._update_status_line)
        self._fps_timer.timeout.connect(self._render_info_text)
        self._fps_timer.start(500)

        # -- Preview render timer (~25 fps): pulls latest frame from camera buffer --
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._on_preview_timer_tick)

        # Initial info render
        QTimer.singleShot(0, self._render_info_text)

    def _apply_default_splitter_sizes(self) -> None:
        """Set default splitter sizes (60/40) after widget geometry is resolved."""
        total = self._splitter.width()
        if total < 100:
            total = 1500  # fallback
        self._splitter.setSizes([int(total * 0.60), int(total * 0.40)])

    # ------------------------------------------------------------------ #
    #  Connection
    # ------------------------------------------------------------------ #

    def _on_connect_clicked(self) -> None:
        if self._camera.is_connected:
            self._do_disconnect()
        else:
            self._do_connect()

    def _do_disconnect(self) -> None:
        """Stop preview if running, then disconnect. Always leaves UI in safe state."""
        self._btn_connect.setEnabled(False)
        self._status.setText("Disconnecting…")
        try:
            if self._camera.is_previewing:
                try:
                    self._camera.stop_preview()
                except Exception:
                    pass
                self._preview_timer.stop()
        except Exception:
            pass
        try:
            self._camera.disconnect()
        except Exception:
            pass
        self._btn_connect.setText("Connect")
        self._btn_connect.setEnabled(True)
        self._btn_start_preview.setEnabled(False)
        self._btn_stop_preview.setEnabled(False)
        self._btn_test_fps.setEnabled(False)
        self._btn_benchmark.setEnabled(False)
        self._btn_record.setEnabled(False)
        self._status.setText("Disconnected")

    def _do_connect(self) -> None:
        """Show camera selection dialog, then connect. Restores UI on failure."""
        # Show selection dialog
        dlg = _CameraSelectDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return  # user cancelled — button stays enabled, nothing changes
        info = dlg.selected_info()
        if info is None:
            return

        self._btn_connect.setEnabled(False)
        self._status.setText("Connecting…")
        try:
            # Disconnect any existing camera first (no-op if already disconnected)
            try:
                self._camera.disconnect()
            except Exception:
                pass
            self._camera = create_camera(info)
            self._btn_connect.setText("Disconnect")
            self._btn_connect.setEnabled(True)
            self._set_preview_ui(False)
            sensor = self._camera.get_sensor_size()
            self._sensor_w, self._sensor_h = sensor
            self._status.setText(
                f"Connected — {info.display_name}  {sensor[0]}×{sensor[1]}"
            )
            self._update_roi_ranges_from_camera()
        except Exception as exc:
            # Connect failed — restore to safe disconnected state
            self._btn_connect.setText("Connect")
            self._btn_connect.setEnabled(True)
            self._btn_start_preview.setEnabled(False)
            self._btn_stop_preview.setEnabled(False)
            self._btn_test_fps.setEnabled(False)
            self._btn_benchmark.setEnabled(False)
            self._btn_record.setEnabled(False)
            self._status.setText(f"Connect failed: {exc}")

    def _update_roi_ranges_from_camera(self) -> None:
        """After connect, query camera increments and update ROI spin/slider ranges."""
        try:
            cfg = self._camera.get_roi_config()
            self._w_inc = cfg.get("w_inc", 1)
            self._h_inc = cfg.get("h_inc", 1)
            self._ox_inc = cfg.get("ox_inc", 1)
            self._oy_inc = cfg.get("oy_inc", 1)
            self._w_min = cfg.get("w_min", 1)
            self._h_min = cfg.get("h_min", 1)
        except Exception:
            pass

        # Update spin/slider ranges
        w = self._roi_spins["roi_w"].value()
        h = self._roi_spins["roi_h"].value()

        self._set_spin_slider_range("roi_w",  self._w_min, self._sensor_w,           self._w_inc)
        self._set_spin_slider_range("roi_h",  self._h_min, self._sensor_h,           self._h_inc)
        self._set_spin_slider_range("roi_ox", 0,           self._sensor_w - w,        self._ox_inc)
        self._set_spin_slider_range("roi_oy", 0,           self._sensor_h - h,        self._oy_inc)

    def _set_spin_slider_range(self, key: str, mn: int, mx: int, step: int = 1) -> None:
        """Set range and step for both spin and slider."""
        mx = max(mn, mx)
        spin = self._roi_spins[key]
        slider = self._roi_sliders[key]

        spin.blockSignals(True)
        spin.setRange(mn, mx)
        spin.setSingleStep(step)
        spin.blockSignals(False)

        slider.blockSignals(True)
        slider.setRange(mn, mx)
        slider.setSingleStep(step)
        slider.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  ROI: bidirectional sync (spinboxes <-> sliders <-> overlay)
    # ------------------------------------------------------------------ #

    def _on_roi_spin_changed(self, key: str, value: int) -> None:
        """User edited a ROI spinbox — snap, clamp, sync slider + overlay."""
        if self._roi_sync_lock:
            return
        self._roi_sync_lock = True
        try:
            self._snap_and_clamp_roi_controls()
            self._sync_slider_from_spin(key)
            self._apply_roi_overlay_from_controls()
            self.value_changed.emit()
        finally:
            self._roi_sync_lock = False

    def _on_roi_slider_changed(self, key: str, value: int) -> None:
        """User dragged a ROI slider — snap, clamp, sync spin + overlay."""
        if self._roi_sync_lock:
            return
        self._roi_sync_lock = True
        try:
            # Copy slider value to spin
            self._roi_spins[key].blockSignals(True)
            self._roi_spins[key].setValue(value)
            self._roi_spins[key].blockSignals(False)
            self._snap_and_clamp_roi_controls()
            self._sync_spin_from_slider(key)
            self._apply_roi_overlay_from_controls()
            self.value_changed.emit()
        finally:
            self._roi_sync_lock = False

    def _on_roi_overlay_changed(self) -> None:
        """User dragged the ROI rectangle on the preview — update controls."""
        if self._roi_sync_lock:
            return
        self._roi_sync_lock = True
        try:
            self._apply_controls_from_roi_overlay()
            self._update_status_line()
            self.value_changed.emit()
        finally:
            self._roi_sync_lock = False

    def _snap_and_clamp_roi_controls(self) -> None:
        """Snap current spinbox values to valid increments and clamp offsets."""
        w = self._snap_down(self._roi_spins["roi_w"].value(),  self._w_inc, self._w_min, self._sensor_w)
        h = self._snap_down(self._roi_spins["roi_h"].value(),  self._h_inc, self._h_min, self._sensor_h)
        ox = self._snap_down(self._roi_spins["roi_ox"].value(), self._ox_inc, 0, self._sensor_w - w)
        oy = self._snap_down(self._roi_spins["roi_oy"].value(), self._oy_inc, 0, self._sensor_h - h)

        for key, val in [("roi_w", w), ("roi_h", h), ("roi_ox", ox), ("roi_oy", oy)]:
            self._roi_spins[key].blockSignals(True)
            self._roi_spins[key].setValue(val)
            self._roi_spins[key].blockSignals(False)

        # Update offset ranges (depend on current w/h)
        self._set_spin_slider_range("roi_ox", 0, self._sensor_w - w, self._ox_inc)
        self._set_spin_slider_range("roi_oy", 0, self._sensor_h - h, self._oy_inc)

    def _sync_slider_from_spin(self, key: str) -> None:
        """Copy all spin values to corresponding sliders."""
        for k in self._roi_spins:
            self._roi_sliders[k].blockSignals(True)
            self._roi_sliders[k].setValue(self._roi_spins[k].value())
            self._roi_sliders[k].blockSignals(False)

    def _sync_spin_from_slider(self, key: str) -> None:
        """Copy all slider values to corresponding spins."""
        for k in self._roi_sliders:
            self._roi_spins[k].blockSignals(True)
            self._roi_spins[k].setValue(self._roi_sliders[k].value())
            self._roi_spins[k].blockSignals(False)

    def _apply_roi_overlay_from_controls(self) -> None:
        """Move the pyqtgraph ROI rectangle to match the numeric controls."""
        w = self._roi_spins["roi_w"].value()
        h = self._roi_spins["roi_h"].value()
        ox = self._roi_spins["roi_ox"].value()
        oy = self._roi_spins["roi_oy"].value()

        self._roi_item.blockSignals(True)
        self._roi_item.setPos([ox, oy])
        self._roi_item.setSize([w, h])
        self._roi_item.blockSignals(False)

    def _apply_controls_from_roi_overlay(self) -> None:
        """Read the ROI rectangle position/size and update spinboxes + sliders."""
        pos = self._roi_item.pos()
        size = self._roi_item.size()
        ox = max(0, int(pos.x()))
        oy = max(0, int(pos.y()))
        w = max(1, int(size.x()))
        h = max(1, int(size.y()))

        # Snap to increments
        w = self._snap_down(w,  self._w_inc,  self._w_min, self._sensor_w)
        h = self._snap_down(h,  self._h_inc,  self._h_min, self._sensor_h)
        ox = self._snap_down(ox, self._ox_inc, 0,           self._sensor_w - w)
        oy = self._snap_down(oy, self._oy_inc, 0,           self._sensor_h - h)

        for key, val in [("roi_w", w), ("roi_h", h), ("roi_ox", ox), ("roi_oy", oy)]:
            self._roi_spins[key].blockSignals(True)
            self._roi_spins[key].setValue(val)
            self._roi_spins[key].blockSignals(False)
            self._roi_sliders[key].blockSignals(True)
            self._roi_sliders[key].setValue(val)
            self._roi_sliders[key].blockSignals(False)

        # Update offset ranges
        self._set_spin_slider_range("roi_ox", 0, self._sensor_w - w, self._ox_inc)
        self._set_spin_slider_range("roi_oy", 0, self._sensor_h - h, self._oy_inc)

    @staticmethod
    def _snap_down(val: int, inc: int, mn: int, mx: int) -> int:
        val = max(mn, min(val, mx))
        return val - ((val - mn) % inc) if inc > 0 else val

    # ------------------------------------------------------------------ #
    #  Preview
    # ------------------------------------------------------------------ #

    def _set_preview_ui(self, is_running: bool) -> None:
        """Helper to manage start/stop/record button states."""
        connected = getattr(self._camera, "is_connected", False)
        self._btn_start_preview.setEnabled(connected and not is_running)
        self._btn_stop_preview.setEnabled(is_running)
        self._btn_test_fps.setEnabled(connected)
        self._btn_benchmark.setEnabled(connected)
        self._btn_record.setEnabled(connected)

    def _on_fps_done(self) -> None:
        """Slot: restore UI and restart preview after fps test/benchmark (main thread)."""
        self._set_preview_ui(False)
        # Restart preview automatically — start_preview() is safe here because
        # camera is not previewing (stopped by test/benchmark) and this slot
        # runs in the main thread via signal.
        if self._camera.is_connected and not self._camera.is_previewing:
            QTimer.singleShot(100, self._on_start_preview)

    def _on_fps_result(self, msg: str) -> None:
        """Slot to display fps/benchmark result text (main thread)."""
        self._lbl_test_fps_result.setText(msg)
        self._status.setText(msg)

    def _on_start_preview(self) -> None:
        if not self._camera.is_connected:
            return
        self._btn_start_preview.setEnabled(False)  # prevent double clicks
        
        self._preview_frame_count = 0
        self._preview_fps_timer_start = time.perf_counter()
        self._preview_dropped = 0
        try:
            self._camera.start_preview(
                callback=self._on_preview_frame,
                exposure_us=self._spin_exposure.value(),
            )
            self._set_preview_ui(True)
            self._last_preview_ts_displayed = 0.0
            self._image_view.setLevels(0, 255)
            self._preview_timer.start(40)
            self._status.setText("Preview running")
        except Exception as exc:
            self._set_preview_ui(False)
            self._status.setText(f"Preview start failed: {exc}")

    def _on_stop_preview(self) -> None:
        try:
            self._camera.stop_preview()
        except Exception as exc:
            self._status.setText(f"Error stopping preview: {exc}")
        finally:
            self._preview_timer.stop()
            self._set_preview_ui(False)
            self._status.setText("Preview stopped")

    def _on_exposure_changed(self) -> None:
        val = self._spin_exposure.value()
        actual = self._camera.set_exposure_live(val)
        if actual is not None:
            self._status.setText(f"Exposure set: {actual:.0f} µs")

    def _on_gain_changed(self) -> None:
        val = self._spin_gain.value()
        actual = self._camera.set_gain_live(val)
        if actual is not None:
            self._status.setText(f"Gain set: {actual:.1f} dB")

    def _on_preview_frame(self, frame: np.ndarray) -> None:
        """Legacy callback — camera no longer calls this; kept for API compatibility."""

    def _on_preview_timer_tick(self) -> None:
        """QTimer tick (~25 fps): pull latest frame from camera buffer and render."""
        frame, ts = self._camera.get_latest_preview()
        if frame is None or ts <= self._last_preview_ts_displayed:
            return
        self._last_preview_ts_displayed = ts
        self._preview_frame_count += 1
        try:
            self._image_view.setImage(
                frame, autoRange=False, autoLevels=False,
                autoHistogramRange=False,
            )
        except Exception:
            self._preview_dropped += 1

    # ------------------------------------------------------------------ #
    #  Test FPS
    # ------------------------------------------------------------------ #

    def _on_test_fps(self) -> None:
        if not self._camera.is_connected:
            return
        roi = self._get_roi_tuple()
        self._lbl_test_fps_result.setText("Measuring…")
        self._btn_test_fps.setEnabled(False)

        exposure_us = self._spin_exposure.value()
        gain = self._spin_gain.value() if self._spin_gain.isEnabled() else None

        def _measure() -> None:
            try:
                measured = self._camera.test_fps(
                    roi=roi,
                    exposure_us=exposure_us,
                    gain=gain,
                    test_duration=1.0,
                )
                self._fps_result_signal.emit(f"Test FPS: {measured:.1f}")
                self._last_estimated_fps = measured
            except Exception as exc:
                self._fps_result_signal.emit(f"Test FPS failed: {exc}")
            finally:
                self._fps_done_signal.emit()

        t = threading.Thread(target=_measure, daemon=True, name="test-fps")
        t.start()

    def _on_benchmark(self) -> None:
        if not self._camera.is_connected:
            return
        roi = self._get_roi_tuple()
        self._lbl_test_fps_result.setText("Benchmarking (5s)…")
        self._btn_benchmark.setEnabled(False)
        self._btn_test_fps.setEnabled(False)

        exposure_us_b = self._spin_exposure.value()
        gain_b = self._spin_gain.value() if self._spin_gain.isEnabled() else None

        def _run_bench() -> None:
            try:
                result = self._camera.benchmark_fps(
                    duration_s=5.0,
                    roi=roi,
                    exposure_us=exposure_us_b,
                    gain=gain_b,
                )
                msg = (
                    f"Bench: {result['fps_effective']:.1f} fps  "
                    f"frames={result['frames']}  dropped={result['dropped_frames']}"
                )
                self._fps_result_signal.emit(msg)
            except Exception as exc:
                self._fps_result_signal.emit(f"Benchmark failed: {exc}")
            finally:
                self._fps_done_signal.emit()

        t = threading.Thread(target=_run_bench, daemon=True, name="benchmark")
        t.start()

    # ------------------------------------------------------------------ #
    #  Recording
    # ------------------------------------------------------------------ #

    def _on_record(self) -> None:
        if not self._camera.is_connected:
            return

        roi = self._get_roi_tuple()
        gain = self._spin_gain.value() if self._spin_gain.isEnabled() else None

        self._btn_record.setEnabled(False)
        self._btn_stop_record.setEnabled(True)
        self._btn_start_preview.setEnabled(False)
        self._btn_stop_preview.setEnabled(False)
        self._status.setText("Recording…")

        self._preview_timer.stop()
        self._camera.stop_preview()

        self._record_thread = QThread()
        self._record_worker = _RecordWorker(
            camera=self._camera,
            output_dir=self._edit_output_dir.text(),
            basename=self._edit_basename.text(),
            duration_s=self._spin_duration.value(),
            roi=roi,
            exposure_us=self._spin_exposure.value(),
            gain=gain,
            fps_hint=self._spin_fps_hint.value(),
            pixel_format="Mono8",
            rec_format=self._combo_format.currentText(),
        )
        self._record_worker.moveToThread(self._record_thread)
        self._record_thread.started.connect(self._record_worker.run)
        self._record_worker.finished.connect(self._on_record_done)
        self._record_worker.error.connect(self._on_record_error)
        self._record_worker.progress.connect(self._on_record_progress)

        self._record_worker.finished.connect(self._record_thread.quit)
        self._record_worker.error.connect(self._record_thread.quit)
        self._record_thread.finished.connect(self._record_worker.deleteLater)
        self._record_thread.finished.connect(
            lambda: setattr(self, "_record_thread", None)
        )

        self._record_thread.start()

    def _on_stop_record(self) -> None:
        self._camera.stop_record()

    def _on_sim_raw(self) -> None:
        """Run a simulated RAW recording (no camera needed)."""
        roi = self._get_roi_tuple()
        w, h = roi[0], roi[1]
        fps_target = self._spin_fps_hint.value()
        out_dir = self._edit_output_dir.text()
        basename = self._edit_basename.text()

        self._btn_sim_raw.setEnabled(False)
        self._status.setText("Simulating RAW (5s)…")

        def _run_sim() -> None:
            try:
                result = BaslerCamera.simulate_record_raw(
                    output_dir=out_dir,
                    basename=basename,
                    width=w,
                    height=h,
                    fps_target=fps_target,
                    duration_s=5.0,
                )
                fps_eff = result["fps_effective"]
                frames = result["frames_written"]
                dropped = result["dropped_frames"]
                fps_ratio = fps_eff / fps_target if fps_target > 0 else 0.0

                # Write qc.json
                reasons: list[str] = []
                if dropped > 0:
                    reasons.append(f"dropped_frames={dropped}")
                if fps_ratio < 0.95:
                    reasons.append(f"fps_ratio={fps_ratio:.3f} < 0.95")
                if dropped > 0.01 * frames:
                    reasons.append("dropped > 1% of frames")
                if fps_ratio < 0.90:
                    reasons.append(f"fps_ratio={fps_ratio:.3f} < 0.90")
                qc_pass = len(reasons) == 0
                qc = {
                    "pass": qc_pass,
                    "fps_target": fps_target,
                    "fps_effective": round(fps_eff, 2),
                    "fps_ratio": round(fps_ratio, 4),
                    "frames_written": frames,
                    "dropped_frames": dropped,
                    "reasons": reasons,
                }
                qc_path = os.path.join(out_dir, basename + "_qc.json")
                with open(qc_path, "w", encoding="utf-8") as f:
                    json.dump(qc, f, indent=2)

                if fps_ratio < 0.90:
                    tag = "FAIL"
                elif fps_ratio < 0.95:
                    tag = "WARN"
                else:
                    tag = "OK"

                msg = (
                    f"SIM done FPS={fps_eff:.1f} ratio={fps_ratio:.3f} "
                    f"frames={frames} {tag}\n"
                    f"Files: {result['raw_path']}"
                )
                QTimer.singleShot(0, lambda: self._status.setText(msg))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._status.setText(
                    f"❌ Sim failed: {exc}"
                ))
            finally:
                QTimer.singleShot(0, lambda: self._btn_sim_raw.setEnabled(True))

        t = threading.Thread(target=_run_sim, daemon=True, name="sim-raw")
        t.start()

    def _on_record_done(self, result: RecordResult) -> None:
        fps_str = (
            f"{result.fps_effective:.1f}" if result.fps_effective else "N/A"
        )
        self._status.setText(
            f"✅ Record done — {result.frames_written} frames, "
            f"fps_eff={fps_str}, dropped={result.dropped}\n"
            f"Video: {result.video_path}\n"
            f"Meta:  {result.meta_path}"
        )
        self._last_record_result = result

        # --- Write qc.json ---
        try:
            fps_target = self._spin_fps_hint.value()
            fps_eff = result.fps_effective or 0.0
            fps_ratio = fps_eff / fps_target if fps_target > 0 else 0.0
            reasons: list[str] = []
            if result.dropped > 0:
                reasons.append(f"dropped_frames={result.dropped}")
            if fps_ratio < 0.95:
                reasons.append(f"fps_ratio={fps_ratio:.3f} < 0.95")
            if result.dropped > 0.01 * result.frames_written:
                reasons.append("dropped > 1% of frames")
            if fps_ratio < 0.90:
                reasons.append(f"fps_ratio={fps_ratio:.3f} < 0.90")
            qc_pass = len(reasons) == 0
            qc = {
                "pass": qc_pass,
                "fps_target": fps_target,
                "fps_effective": round(fps_eff, 2),
                "fps_ratio": round(fps_ratio, 4),
                "frames_written": result.frames_written,
                "dropped_frames": result.dropped,
                "reasons": reasons,
            }
            qc_path = os.path.join(
                self._edit_output_dir.text(),
                self._edit_basename.text() + "_qc.json",
            )
            with open(qc_path, "w", encoding="utf-8") as f:
                json.dump(qc, f, indent=2)
        except Exception:
            pass

        self._btn_record.setEnabled(True)
        self._btn_stop_record.setEnabled(False)
        self._btn_start_preview.setEnabled(True)
        QTimer.singleShot(200, self._on_start_preview)

    def _on_record_error(self, err: str) -> None:
        self._status.setText(f"❌ Record error: {err}")
        self._btn_record.setEnabled(True)
        self._btn_stop_record.setEnabled(False)
        self._btn_start_preview.setEnabled(True)

    def _on_record_progress(self, frames: int, elapsed: float) -> None:
        fps_target = self._spin_fps_hint.value()
        fps_eff = frames / elapsed if elapsed > 0.5 else 0.0
        fps_ratio = fps_eff / fps_target if fps_target > 0 else 0.0
        pct = fps_ratio * 100

        # Health tag
        if fps_ratio < 0.90:
            tag = "FAIL"
        elif fps_ratio < 0.95:
            tag = "WARN"
        else:
            tag = "OK"

        dur = self._spin_duration.value()
        remaining = dur - elapsed if dur > 0 else 0.0
        rem_str = f" ~{max(0, remaining):.1f}s remaining" if dur > 0 else ""
        self._status.setText(
            f"Recording… FPS={fps_eff:.0f} ({pct:.0f}%) "
            f"frames={frames}{rem_str} {tag}"
        )

    # ------------------------------------------------------------------ #
    #  ROI helpers
    # ------------------------------------------------------------------ #

    def _get_roi_tuple(self) -> tuple[int, int, int, int]:
        """Read (w, h, offsetX, offsetY) from the numeric ROI controls (snapped)."""
        w = self._roi_spins["roi_w"].value()
        h = self._roi_spins["roi_h"].value()
        ox = self._roi_spins["roi_ox"].value()
        oy = self._roi_spins["roi_oy"].value()
        return w, h, ox, oy

    # ------------------------------------------------------------------ #
    #  Status line
    # ------------------------------------------------------------------ #

    def _update_status_line(self) -> None:
        if not PYPYLON_AVAILABLE:
            return

        elapsed = time.perf_counter() - self._preview_fps_timer_start
        if elapsed > 0.5 and self._preview_frame_count > 0:
            self._preview_fps = self._preview_frame_count / elapsed
            self._preview_frame_count = 0
            self._preview_fps_timer_start = time.perf_counter()

        roi = self._get_roi_tuple()

        if self._camera.is_previewing:
            self._status.setText(
                f"Preview — fps≈{self._preview_fps:.1f}  "
                f"dropped={self._preview_dropped}\n"
                f"ROI: W={roi[0]} H={roi[1]} OX={roi[2]} OY={roi[3]}"
            )

    def _render_info_text(self) -> None:
        """Build the info readout under the preview."""
        lines: list[str] = []

        # -- Connection / device --
        if self._camera.is_connected:
            lines.append(f"Device : connected  (sensor {self._sensor_w}×{self._sensor_h})")
        else:
            lines.append("Device : disconnected")

        # -- Preview --
        exp = self._spin_exposure.value()
        gain = self._spin_gain.value()
        if self._camera.is_previewing:
            lines.append(
                f"Preview: {self._sensor_w}×{self._sensor_h}  "
                f"fps≈{self._preview_fps:.1f}  dropped={self._preview_dropped}"
            )
        else:
            lines.append("Preview: stopped")
        lines.append(f"Exposure: {exp:.0f} µs   Gain: {gain:.1f} dB")

        # -- ROI --
        roi = self._get_roi_tuple()
        lines.append(f"Rec ROI: W={roi[0]}  H={roi[1]}  OX={roi[2]}  OY={roi[3]}")

        # -- Record target --
        dur = self._spin_duration.value()
        fps_hint = self._spin_fps_hint.value()
        lines.append(f"Target : {dur:.1f}s  fps_hint={fps_hint:.0f}")

        # -- Estimated FPS --
        if self._last_estimated_fps is not None:
            lines.append(f"Est FPS: {self._last_estimated_fps:.1f}  (from Test FPS)")

        # -- Last record --
        rr = self._last_record_result
        if rr is not None:
            fps_e = f"{rr.fps_effective:.1f}" if rr.fps_effective else "N/A"
            lines.append(f"Last rec: {rr.frames_written}fr  fps_eff={fps_e}  drop={rr.dropped}")
            lines.append(f"  video: {rr.video_path}")
            lines.append(f"  meta : {rr.meta_path}")

        self._info_text.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------ #
    #  Browse output dir
    # ------------------------------------------------------------------ #

    def _on_browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Select output folder", self._edit_output_dir.text()
        )
        if d:
            self._edit_output_dir.setText(d)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _set_all_enabled(self, enabled: bool) -> None:
        for w in (
            self._btn_connect, self._btn_start_preview,
            self._btn_stop_preview, self._spin_exposure, self._spin_gain,
            self._spin_fps_hint, self._btn_test_fps, self._spin_duration,
            self._edit_output_dir, self._btn_browse, self._edit_basename,
            self._btn_record, self._btn_stop_record,
        ):
            w.setEnabled(enabled)
        for spin in self._roi_spins.values():
            spin.setEnabled(enabled)
        for slider in self._roi_sliders.values():
            slider.setEnabled(enabled)

    # ------------------------------------------------------------------ #
    #  Cleanup on widget destroy
    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:
        self._camera.disconnect()
        super().closeEvent(event)

    def deleteLater(self) -> None:
        self._camera.disconnect()
        super().deleteLater()
