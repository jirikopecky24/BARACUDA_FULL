"""
AcquisitionPanel — self-contained Basler camera acquisition UI.

Embeds live preview (pyqtgraph ImageView) + draggable ROI + controls.
Fully import-guarded: shows a warning when pypylon is not available.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
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
    QTabWidget, QMessageBox, QStackedWidget,
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
# Motion integration (lazy — only imported if pyximc is available)
from barakuda.devices.acquisition.motion.recipes import ConstantVelocityDragRecipe
from barakuda.devices.acquisition.motion.stage_scale_audit import (
    ACQUISITION_DEFAULT_STAGE_UM_PER_UNIT,
    STANDA_8MT167_FULL_STEP_UM,
    XIMC_POSITION_UNITS_PER_FULL_STEP,
    build_stage_motion_audit_dict,
)
from barakuda.devices.acquisition.motion.motion_run import (
    run_record_and_motion,
    MotionRunResult,
    MotionRunError,
    format_record_motion_start_log,
    resolve_unique_run_target,
)
from barakuda.devices.acquisition.motion.metric_conversion import MetricMotionCommand
from barakuda.devices.acquisition.motion.metric_conversion import XimcMetricCalibration
from barakuda.core.run_protocol import (
    create_protocol_from_context,
    load_protocol,
    merge_protocol,
    save_protocol,
)
from barakuda.shell.widgets.run_protocol_dialog import RunProtocolDialog
from barakuda.shell.stage_service import get_stage_service
from barakuda.shell.stage_console_window import StageConsoleWindow, StageConsoleSnapshot
from .stage_scan_lifecycle import StageScanLifecycleGuard, StageScanToken
try:
    from barakuda.devices.acquisition.motion.ximc_stage import XimcStage, enumerate_ximc_devices
    _XIMC_AVAILABLE = True
except Exception:
    _XIMC_AVAILABLE = False
    XimcStage = None  # type: ignore
    enumerate_ximc_devices = lambda: []  # type: ignore


_LOG = logging.getLogger(__name__)


class _StageScanDispatchBridge(QObject):
    # payload: (token, devices, com_desc)
    ready = pyqtSignal(object, object, object)


_STAGE_SCAN_BRIDGE = _StageScanDispatchBridge()



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


class _NoScrollSlider(QSlider):
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
#  Worker: Record + Motion (synchronized run in background thread)
# ------------------------------------------------------------------ #

class _RecordMotionWorker(QObject):
    """Runs run_record_and_motion() in a QThread.

    Shares signal contract with _RecordWorker so _on_record_done /
    _on_record_error callbacks can be reused for the recording part.
    Stage-specific result is passed through the motion_finished signal.
    """

    # Emits (RecordResult, MotionRunResult)
    motion_finished = pyqtSignal(object, object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, float)
    log_msg = pyqtSignal(str)

    def __init__(
        self,
        camera: BaslerCamera,
        stage,                         # AbstractStage (typed loosely to avoid import cycles)
        recipe: ConstantVelocityDragRecipe,
        metric_command: MetricMotionCommand | None,
        metric_mapping_profile: XimcMetricCalibration | None,
        output_dir: str,
        basename: str,
        duration_s: float,
        roi: tuple,
        exposure_us: float,
        gain,
        fps_hint: float,
        pixel_format: str,
    ) -> None:
        super().__init__()
        self._cam = camera
        self._stage = stage
        self._recipe = recipe
        self._metric_command = metric_command
        self._metric_mapping_profile = metric_mapping_profile
        self._output_dir = output_dir
        self._basename = basename
        self._duration_s = duration_s
        self._roi = roi
        self._exposure_us = exposure_us
        self._gain = gain
        self._fps_hint = fps_hint
        self._pixel_format = pixel_format

    def _emit_log(self, msg: str) -> None:
        try:
            self.log_msg.emit(str(msg))
        except Exception:
            pass

    def run(self) -> None:
        try:
            result = run_record_and_motion(
                camera=self._cam,
                stage=self._stage,
                recipe=self._recipe,
                metric_command=self._metric_command,
                metric_mapping_profile=self._metric_mapping_profile,
                output_dir=self._output_dir,
                basename=self._basename,
                duration_s=self._duration_s,
                roi=self._roi,
                exposure_us=self._exposure_us,
                gain=self._gain,
                fps_hint=self._fps_hint,
                pixel_format=self._pixel_format,
                progress_callback=lambda f, t: self.progress.emit(f, t),
                log_fn=self._emit_log,
            )
            self.motion_finished.emit(result.record_result, result)
        except MotionRunError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(f"Unexpected error in Record+Motion worker: {exc}")


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
    _motion_log_signal = pyqtSignal(str)
    # Thread-safe signal for slow stage enumeration (XIMC + COM descriptions)
    _stage_list_ready_signal = pyqtSignal(object, object)  # (devices, com_desc)

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
        self._log_fn = None  # set via set_log_fn() from shell

        # Motion integration — stage instance and motion worker
        self._stage = None          # XimcStage or None (lazy connect)
        self._stage_svc = get_stage_service()
        self._stage_console_win: StageConsoleWindow | None = None
        self._motion_thread: QThread | None = None
        self._motion_worker: _RecordMotionWorker | None = None
        self._motion_elapsed_timer: QTimer | None = None
        self._motion_run_t0: float = 0.0
        self._stage_scan_guard = StageScanLifecycleGuard()
        self._panel_closing = False

        # Connect thread-safe fps signals to UI slots (always run in main thread)
        self._fps_done_signal.connect(self._on_fps_done)
        self._fps_result_signal.connect(self._on_fps_result)
        self._motion_log_signal.connect(self._on_motion_worker_log)
        _STAGE_SCAN_BRIDGE.ready.connect(self._on_stage_scan_ready)

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

        # Countdown timer state
        self._rec_start_time: float = 0.0
        self._rec_duration_s: float = 0.0

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
    #  Logging hook
    # ------------------------------------------------------------------ #

    def set_log_fn(self, fn) -> None:
        """Wire an external log function, e.g. log_panel.log, from the shell."""
        self._log_fn = fn

    def _log(self, msg: str) -> None:
        """Forward message to external log (if wired) and also append to info panel."""
        if self._log_fn is not None:
            try:
                self._log_fn(f"[ACQ] {msg}")
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    #  UI Construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.setMinimumSize(860, 560)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)

        # ---- LEFT: Live preview ----
        left = QWidget()
        left.setMinimumWidth(320)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)

        self._image_view = pg.ImageView()
        self._image_view.ui.roiBtn.hide()
        self._image_view.ui.menuBtn.hide()
        self._image_view.ui.histogram.hide()
        self._image_view.getView().invertY(True)
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
        right_scroll.setMinimumWidth(470)
        right_scroll.setMaximumWidth(780)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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

            slider = _NoScrollSlider(Qt.Orientation.Horizontal)
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
        self._edit_output_dir.setToolTip(
            "Base folder for acquisitions.\n"
            "Each run is saved into a subfolder named <basename>.\n"
            "Example: <output>/<basename>/<basename>.raw"
        )
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
        self._edit_basename.setToolTip(
            "Run name. A subfolder with this name is created under Output folder,\n"
            "and all files inside use this basename."
        )
        rec_form.addRow("Basename:", self._edit_basename)

        self._combo_format = QComboBox()
        self._combo_format.addItem("RAW (scientific, recommended)")
        self._combo_format.addItem("AVI (preview, ≤600 FPS)")
        self._combo_format.setCurrentIndex(0)
        self._combo_format.setToolTip(
            "RAW = raw binary frames, full fidelity, recommended for scientific acquisition.\n"
            "AVI = MJPG container, preview/compatibility only, unreliable above 600 FPS."
        )
        self._combo_format.currentIndexChanged.connect(self._on_format_changed)
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

        self._btn_open_protocol = QPushButton("Open Protocol")
        self._btn_open_protocol.setToolTip(
            "Open run protocol editor for the current acquisition run folder."
        )
        self._btn_open_protocol.clicked.connect(self._on_open_protocol)
        rec_btn_row.addWidget(self._btn_open_protocol)
        rec_form.addRow("", rec_btn_row)

        self._lbl_countdown = QLabel("")
        self._lbl_countdown.setStyleSheet("font-weight: bold; color: #cc4400;")
        self._lbl_countdown.setVisible(False)
        rec_form.addRow("", self._lbl_countdown)

        # -- Settings --
        grp_settings = QGroupBox("Settings")
        settings_form = QFormLayout(grp_settings)

        self._combo_pixel_format = QComboBox()
        self._combo_pixel_format.addItems(["Mono8", "Mono12"])
        self._combo_pixel_format.setCurrentText("Mono8")
        self._combo_pixel_format.setToolTip(
            "Pixel format for recording. Mono8 = 8-bit (smaller files),\n"
            "Mono12 = 12-bit (higher dynamic range, larger files)."
        )
        settings_form.addRow("Pixel format:", self._combo_pixel_format)

        right_layout.addWidget(grp_settings)

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
        tabs.setUsesScrollButtons(True)
        tabs.setElideMode(Qt.TextElideMode.ElideRight)

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

        # Tab 3: Motion
        tab_motion = self._build_motion_tab()
        tabs.addTab(tab_motion, "Motion")

        # Tab 4: Status
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
        try:
            self._splitter.setCollapsible(0, False)
            self._splitter.setCollapsible(1, False)
        except Exception:
            pass

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

        # -- Recording countdown timer (250 ms ticks, UI only) --
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(250)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)

        # Initial info render
        QTimer.singleShot(0, self._render_info_text)

    # ------------------------------------------------------------------ #
    #  Motion tab builder
    # ------------------------------------------------------------------ #

    def _build_motion_tab(self) -> QWidget:
        """Build the Motion configuration tab (protocol-based, metric UI)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # -- Stage connection group --
        grp_stage = QGroupBox("Stage (XIMC)")
        stage_form = QFormLayout(grp_stage)

        self._combo_stage_device = QComboBox()
        self._combo_stage_device.setMinimumWidth(320)
        self._combo_stage_device.setToolTip(
            "Select the COM/USB stage device used for motion control.\n"
            "If multiple ports are listed, choose the one matching your XILab device.\n"
            "Close XILab before connecting so Python can open the device."
        )
        stage_form.addRow("Device:", self._combo_stage_device)

        row_stage_btns = QHBoxLayout()
        self._btn_stage_refresh = QPushButton("Refresh list")
        self._btn_stage_refresh.setToolTip("Rescan available XIMC devices (USB and COM).")
        self._btn_stage_refresh.clicked.connect(
            lambda: self._refresh_stage_device_list(async_scan=True)
        )
        row_stage_btns.addWidget(self._btn_stage_refresh)

        self._btn_stage_connect = QPushButton("Connect Stage")
        self._btn_stage_connect.setToolTip(
            "Connect the selected stage device. XILab must be closed, otherwise open_device may fail."
        )
        self._btn_stage_connect.clicked.connect(self._on_stage_connect)
        row_stage_btns.addWidget(self._btn_stage_connect)

        self._btn_open_stage_console = QPushButton("Stage Console…")
        self._btn_open_stage_console.setToolTip(
            "Open Stage Console (Acquisition context)."
        )
        self._btn_open_stage_console.clicked.connect(self._open_stage_console)
        row_stage_btns.addWidget(self._btn_open_stage_console)
        stage_form.addRow("", row_stage_btns)

        self._lbl_stage_status = QLabel("Not connected")
        self._lbl_stage_status.setWordWrap(True)
        stage_form.addRow("Stage:", self._lbl_stage_status)

        self._spin_stage_um_per_unit = _NoScrollDoubleSpinBox()
        self._spin_stage_um_per_unit.setRange(0.0, 10000.0)
        self._spin_stage_um_per_unit.setValue(ACQUISITION_DEFAULT_STAGE_UM_PER_UNIT)
        self._spin_stage_um_per_unit.setDecimals(4)
        self._spin_stage_um_per_unit.setToolTip(
            "Micrometers per XIMC position unit (get_position float).\n"
            f"Standa full-step reference: {STANDA_8MT167_FULL_STEP_UM:.2f} µm/full-step.\n"
            f"Acquisition-chain default uses {int(XIMC_POSITION_UNITS_PER_FULL_STEP)} XIMC units per full-step "
            f"→ {ACQUISITION_DEFAULT_STAGE_UM_PER_UNIT:.4f} µm/unit.\n"
            "0 = unknown (omitted from *_stage.json).\n"
            "Validate: independently measure physical travel in µm for a known "
            "actual_travel_user (see *_stage.json / QC stage_motion_audit); "
            "measured_um / actual_travel_user should match this value."
        )
        stage_form.addRow("µm/unit:", self._spin_stage_um_per_unit)

        layout.addWidget(grp_stage)

        # -- Motion protocol group (architecture stable regardless of connection state) --
        grp_motion = QGroupBox("Motion")
        motion_outer = QVBoxLayout(grp_motion)
        motion_outer.setContentsMargins(10, 10, 10, 10)
        motion_outer.setSpacing(6)

        motion_form = QFormLayout()
        motion_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        motion_outer.addLayout(motion_form)

        self._check_motion_enable = QPushButton("Enable Motion")
        self._check_motion_enable.setCheckable(True)
        self._check_motion_enable.setChecked(False)
        self._check_motion_enable.setToolTip(
            "When enabled, Record button starts a synchronized Record+Motion run.\n"
            "Stage must be connected first."
        )
        self._check_motion_enable.toggled.connect(self._on_motion_enable_toggled)
        motion_form.addRow("", self._check_motion_enable)

        self._combo_motion_protocol = QComboBox()
        self._combo_motion_protocol.addItems([
            "Constant velocity drag",
            "Oscillatory drag (real-data)",
        ])
        self._combo_motion_protocol.setToolTip(
            "Select the motion protocol.\n"
            "Constant velocity drag is supported for Record+Motion.\n"
            "Oscillatory drag (real-data) is shown for the expected architecture, but is not wired yet."
        )
        self._combo_motion_protocol.currentIndexChanged.connect(self._update_motion_run_button)
        motion_form.addRow("Protocol:", self._combo_motion_protocol)

        self._combo_motion_axis = QComboBox()
        self._combo_motion_axis.addItems(["x", "y"])
        self._combo_motion_axis.setToolTip("Stage axis to drive during the drag run.")
        motion_form.addRow("Axis:", self._combo_motion_axis)

        self._combo_motion_direction = QComboBox()
        self._combo_motion_direction.addItems(["+1 (positive)", "-1 (negative)"])
        self._combo_motion_direction.setToolTip("Stage movement direction relative to positive axis.")
        motion_form.addRow("Direction:", self._combo_motion_direction)

        # Protocol-specific UI (stack)
        self._motion_protocol_stack = QStackedWidget()
        motion_outer.addWidget(self._motion_protocol_stack)

        # --- Protocol: Constant velocity drag (supported) ---
        cvw = QWidget()
        cv_form = QFormLayout(cvw)
        cv_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)

        self._spin_motion_travel_um = _NoScrollDoubleSpinBox()
        self._spin_motion_travel_um.setRange(0.1, 1e9)
        self._spin_motion_travel_um.setValue(200.0)
        self._spin_motion_travel_um.setDecimals(3)
        self._spin_motion_travel_um.setSuffix(" µm")
        self._spin_motion_travel_um.setToolTip(
            "Total travel distance in micrometers (µm).\n"
            "Backend converts this metric value to stage user units via stage µm/unit."
        )
        self._spin_motion_travel_um.valueChanged.connect(lambda _v: self._update_motion_run_button())
        cv_form.addRow("Travel (µm):", self._spin_motion_travel_um)

        self._spin_motion_speed_reg = _NoScrollDoubleSpinBox()
        self._spin_motion_speed_reg.setRange(0.0, 1e12)
        self._spin_motion_speed_reg.setValue(60.0)
        self._spin_motion_speed_reg.setDecimals(3)
        self._spin_motion_speed_reg.setSuffix(" reg")
        self._spin_motion_speed_reg.setToolTip(
            "XIMC firmware Speed register (not µm/s).\n"
            "Physical speed used in *_stage.json comes from measured Δposition/Δt, "
            "not from this register."
        )
        cv_form.addRow("Speed (XIMC Speed reg):", self._spin_motion_speed_reg)

        self._spin_motion_accel_um_s2 = _NoScrollDoubleSpinBox()
        self._spin_motion_accel_um_s2.setRange(0.0, 1e12)
        self._spin_motion_accel_um_s2.setValue(120.0)
        self._spin_motion_accel_um_s2.setDecimals(3)
        self._spin_motion_accel_um_s2.setSuffix(" reg")
        self._spin_motion_accel_um_s2.setToolTip(
            "XIMC raw acceleration register value (legacy backend path).\n"
            "This is not interpreted as µm/s² in the current runtime path."
        )
        cv_form.addRow("Accel (raw reg):", self._spin_motion_accel_um_s2)

        self._spin_motion_decel_um_s2 = _NoScrollDoubleSpinBox()
        self._spin_motion_decel_um_s2.setRange(0.0, 1e12)
        self._spin_motion_decel_um_s2.setValue(120.0)
        self._spin_motion_decel_um_s2.setDecimals(3)
        self._spin_motion_decel_um_s2.setSuffix(" reg")
        self._spin_motion_decel_um_s2.setToolTip(
            "XIMC raw deceleration register value (legacy backend path).\n"
            "This is not interpreted as µm/s² in the current runtime path."
        )
        cv_form.addRow("Decel (raw reg):", self._spin_motion_decel_um_s2)

        self._lbl_motion_semantics_note = QLabel(
            "Note: Travel is metric (µm). Speed/Accel/Decel currently use raw XIMC register values."
        )
        self._lbl_motion_semantics_note.setWordWrap(True)
        self._lbl_motion_semantics_note.setStyleSheet("color: #666;")
        cv_form.addRow("", self._lbl_motion_semantics_note)

        self._lbl_motion_actual_header = QLabel("Last measured motion (read-only):")
        self._lbl_motion_actual_header.setStyleSheet("color: #666; font-weight: bold;")
        cv_form.addRow("", self._lbl_motion_actual_header)

        self._lbl_motion_actual_travel_um = QLabel("not available yet")
        self._lbl_motion_actual_speed_um_s = QLabel("not available yet")
        self._lbl_motion_actual_duration_s = QLabel("not available yet")
        cv_form.addRow("Last actual travel (µm):", self._lbl_motion_actual_travel_um)
        cv_form.addRow("Last actual speed (µm/s):", self._lbl_motion_actual_speed_um_s)
        cv_form.addRow("Last motion duration (s):", self._lbl_motion_actual_duration_s)

        self._lbl_motion_actual_travel_user = QLabel("not available yet")
        self._lbl_motion_actual_speed_user = QLabel("not available yet")
        self._lbl_motion_commanded_travel_user = QLabel("not available yet")
        self._lbl_motion_travel_user_ratio = QLabel("not available yet")
        self._lbl_motion_actual_travel_user.setToolTip(
            "Encoder-based travel from XIMC position (same units as command). "
            "Compare to independent µm measurement to validate µm/unit."
        )
        self._lbl_motion_actual_speed_user.setToolTip(
            "actual_travel_user / duration — not the Speed register value."
        )
        self._lbl_motion_commanded_travel_user.setToolTip(
            "travel_user sent to the backend for this run (from Travel µm ÷ µm/unit)."
        )
        self._lbl_motion_travel_user_ratio.setToolTip(
            "actual_travel_user / commanded — expect ~1 if motion completed as requested."
        )
        cv_form.addRow("Last actual travel (user units):", self._lbl_motion_actual_travel_user)
        cv_form.addRow("Last actual speed (user units/s):", self._lbl_motion_actual_speed_user)
        cv_form.addRow("Commanded travel (user units):", self._lbl_motion_commanded_travel_user)
        cv_form.addRow("Actual / commanded travel:", self._lbl_motion_travel_user_ratio)

        self._motion_protocol_stack.addWidget(cvw)

        # --- Protocol: Oscillatory drag (real-data) (not wired yet) ---
        osw = QWidget()
        os_form = QFormLayout(osw)
        os_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)

        self._spin_osc_frequency_hz = _NoScrollDoubleSpinBox()
        self._spin_osc_frequency_hz.setRange(0.01, 1e6)
        self._spin_osc_frequency_hz.setValue(1.0)
        self._spin_osc_frequency_hz.setDecimals(3)
        self._spin_osc_frequency_hz.setSuffix(" Hz")
        self._spin_osc_frequency_hz.setEnabled(False)
        self._spin_osc_frequency_hz.setToolTip(
            "Oscillatory protocol is not wired for acquisition yet (real-data).\n"
            "This UI is present to preserve the expected protocol-based architecture."
        )
        os_form.addRow("Frequency:", self._spin_osc_frequency_hz)

        self._spin_osc_amplitude_um = _NoScrollDoubleSpinBox()
        self._spin_osc_amplitude_um.setRange(0.0, 1e9)
        self._spin_osc_amplitude_um.setValue(2.0)
        self._spin_osc_amplitude_um.setDecimals(3)
        self._spin_osc_amplitude_um.setSuffix(" µm")
        self._spin_osc_amplitude_um.setEnabled(False)
        self._spin_osc_amplitude_um.setToolTip(
            "Oscillatory protocol is not wired for acquisition yet (real-data).\n"
            "No command will be issued in this mode."
        )
        os_form.addRow("Amplitude:", self._spin_osc_amplitude_um)

        self._lbl_osc_note = QLabel(
            "Oscillatory drag (real-data) is not implemented in Acquisition yet.\n"
            "Select Constant velocity drag to run Record+Motion."
        )
        self._lbl_osc_note.setStyleSheet("color: #666;")
        self._lbl_osc_note.setWordWrap(True)
        os_form.addRow("", self._lbl_osc_note)

        self._motion_protocol_stack.addWidget(osw)

        def _sync_protocol_stack() -> None:
            idx = int(self._combo_motion_protocol.currentIndex())
            self._motion_protocol_stack.setCurrentIndex(0 if idx == 0 else 1)
            self._update_motion_run_button()

        self._combo_motion_protocol.currentIndexChanged.connect(lambda _i: _sync_protocol_stack())
        _sync_protocol_stack()

        self._spin_motion_pre_delay = _NoScrollDoubleSpinBox()
        self._spin_motion_pre_delay.setRange(0.0, 60.0)
        self._spin_motion_pre_delay.setValue(2.0)
        self._spin_motion_pre_delay.setDecimals(1)
        self._spin_motion_pre_delay.setSuffix(" s")
        self._spin_motion_pre_delay.setToolTip(
            "Hold time after recording starts before stage begins moving.\n"
            "Used to establish Brownian baseline window."
        )
        motion_form.addRow("Pre-delay:", self._spin_motion_pre_delay)

        self._spin_motion_post_delay = _NoScrollDoubleSpinBox()
        self._spin_motion_post_delay.setRange(0.0, 60.0)
        self._spin_motion_post_delay.setValue(2.0)
        self._spin_motion_post_delay.setDecimals(1)
        self._spin_motion_post_delay.setSuffix(" s")
        self._spin_motion_post_delay.setToolTip(
            "Hold time after stage stops before recording ends.\n"
            "Allows bead to relax back to equilibrium."
        )
        motion_form.addRow("Post-delay:", self._spin_motion_post_delay)

        self._spin_motion_sign_x = _NoScrollSpinBox()
        self._spin_motion_sign_x.setRange(-1, 1)
        self._spin_motion_sign_x.setValue(1)
        self._spin_motion_sign_x.setSingleStep(2)
        self._spin_motion_sign_x.setToolTip(
            "+1 = positive stage X motion → positive image X direction.\n"
            "-1 = inverted (stage moves right, image appears to move left)."
        )
        motion_form.addRow("Sign stage→image X:", self._spin_motion_sign_x)

        self._spin_motion_sign_y = _NoScrollSpinBox()
        self._spin_motion_sign_y.setRange(-1, 1)
        self._spin_motion_sign_y.setValue(1)
        self._spin_motion_sign_y.setSingleStep(2)
        self._spin_motion_sign_y.setToolTip(
            "+1 = positive stage Y motion → positive image Y direction.\n"
            "-1 = inverted."
        )
        motion_form.addRow("Sign stage→image Y:", self._spin_motion_sign_y)

        layout.addWidget(grp_motion)

        # -- Record+Motion button --
        self._btn_record_motion = QPushButton("⏺ Record + Motion")
        self._btn_record_motion.setToolTip(
            "Start synchronized recording + stage motion run.\n"
            "Motion must be enabled and stage must be connected."
        )
        self._btn_record_motion.setEnabled(False)
        self._btn_record_motion.clicked.connect(self._on_record_motion)
        layout.addWidget(self._btn_record_motion)

        self._lbl_motion_run_status = QLabel("")
        self._lbl_motion_run_status.setWordWrap(True)
        self._lbl_motion_run_status.setStyleSheet("color: #888;")
        layout.addWidget(self._lbl_motion_run_status)

        layout.addStretch(1)
        # Stage enumeration can be slow on Windows (PowerShell CIM queries).
        # Never block UI thread during panel construction — start async scan instead.
        self._update_motion_run_button()
        self._refresh_stage_device_list(async_scan=True)
        return tab

    def _update_motion_actual_metric_labels(
        self,
        *,
        actual_travel_um: float | None = None,
        actual_speed_um_s: float | None = None,
        actual_duration_s: float | None = None,
        actual_travel_user: float | None = None,
        actual_speed_user_s: float | None = None,
        travel_user_commanded: float | None = None,
    ) -> None:
        self._lbl_motion_actual_travel_um.setText(
            f"{float(actual_travel_um):.3f}" if actual_travel_um is not None else "not available yet"
        )
        self._lbl_motion_actual_speed_um_s.setText(
            f"{float(actual_speed_um_s):.3f}" if actual_speed_um_s is not None else "not available yet"
        )
        self._lbl_motion_actual_duration_s.setText(
            f"{float(actual_duration_s):.4f}" if actual_duration_s is not None else "not available yet"
        )
        if not hasattr(self, "_lbl_motion_actual_travel_user"):
            return
        self._lbl_motion_actual_travel_user.setText(
            f"{float(actual_travel_user):.6f}"
            if actual_travel_user is not None
            else "not available yet"
        )
        self._lbl_motion_actual_speed_user.setText(
            f"{float(actual_speed_user_s):.6f}"
            if actual_speed_user_s is not None
            else "not available yet"
        )
        self._lbl_motion_commanded_travel_user.setText(
            f"{float(travel_user_commanded):.6f}"
            if travel_user_commanded is not None
            else "not available yet"
        )
        ratio_txt = "not available yet"
        if (
            actual_travel_user is not None
            and travel_user_commanded is not None
            and abs(float(travel_user_commanded)) > 1e-15
        ):
            ratio_txt = f"{float(actual_travel_user) / float(travel_user_commanded):.6f}"
        elif actual_travel_user is not None and travel_user_commanded is not None:
            ratio_txt = "n/a (commanded travel ~0)"
        self._lbl_motion_travel_user_ratio.setText(ratio_txt)

    def _open_stage_console(self) -> None:
        if self._stage_console_win is None:
            self._stage_console_win = StageConsoleWindow(
                snapshot_provider=self._stage_console_snapshot,
                parent=self,
            )
        self._stage_console_win.show()
        self._stage_console_win.raise_()
        self._stage_console_win.activateWindow()

    def _stage_console_snapshot(self) -> StageConsoleSnapshot:
        lease = self._stage_svc.lease_state()
        tel = self._stage_svc.get_telemetry()
        owner = lease.owner or "none"
        state_parts: list[str] = []
        if lease.run_active:
            state_parts.append("Monitor-only (acquisition active)")
        elif lease.owner != "stage_console":
            state_parts.append("Monitor-only")
        else:
            state_parts.append("Control enabled")
        if lease.busy:
            state_parts.append("busy")
        if lease.stage_um_per_unit is None or (lease.stage_um_per_unit is not None and lease.stage_um_per_unit <= 0):
            state_parts.append("µm/unit unknown")

        speed_note = ""
        if lease.run_active:
            speed_note = "paused during acquisition"
        elif tel.speed_um_s is not None and tel.speed_is_derived:
            speed_note = "derived"
        elif tel.speed_um_s is None:
            speed_note = "N/A"

        return StageConsoleSnapshot(
            connected=lease.connected,
            state_text=", ".join(state_parts) if state_parts else "—",
            owner_text=owner,
            position_um=tel.position_um,
            speed_um_s=tel.speed_um_s,
            speed_note=speed_note,
            encoder=tel.encoder,
            stage_state=tel.state,
        )

    def _refresh_stage_device_list(self, *, async_scan: bool = False) -> None:
        """Populate the device combo with XIMC URIs (COM / USB).

        On Windows, querying friendly COM port descriptions via PowerShell can be
        slow (seconds). If async_scan=True, the scan runs in a background thread
        and the combo updates via a Qt signal.
        """
        self._combo_stage_device.clear()
        if not _XIMC_AVAILABLE:
            self._combo_stage_device.addItem(
                "(install with: pip install libximc in the barakuda environment)", None
            )
            return

        if async_scan:
            if self._panel_closing:
                self._log("[XIMC scan] skipped: panel is closing.")
                return
            self._combo_stage_device.addItem("Scanning devices…", None)

            token = self._stage_scan_guard.start_request()
            if token is None:
                self._log("[XIMC scan] skipped: panel is closing.")
                return
            guard = self._stage_scan_guard
            self._log(
                f"[XIMC scan] started request_id={token.request_id} generation={token.generation}"
            )

            def _scan(scan_token: StageScanToken) -> None:
                try:
                    devices = enumerate_ximc_devices()
                except Exception:
                    devices = []
                ok, reason = guard.should_publish(scan_token)
                if not ok:
                    _LOG.info(
                        "XIMC scan request_id=%s cancelled before COM description lookup (%s).",
                        scan_token.request_id,
                        reason,
                    )
                    return
                try:
                    com_desc = AcquisitionPanel._get_windows_com_descriptions()
                except Exception:
                    com_desc = {}
                ok, reason = guard.should_publish(scan_token)
                if not ok:
                    _LOG.info(
                        "XIMC scan request_id=%s finished but result discarded before UI dispatch (%s).",
                        scan_token.request_id,
                        reason,
                    )
                    return
                _STAGE_SCAN_BRIDGE.ready.emit(scan_token, devices, com_desc)

            threading.Thread(
                target=_scan,
                args=(token,),
                daemon=True,
                name="ximc-scan",
            ).start()
            return

        # Synchronous path (kept for explicit Refresh button if needed)
        try:
            devices = enumerate_ximc_devices()
        except Exception:
            devices = []
        try:
            com_desc = self._get_windows_com_descriptions()
        except Exception:
            com_desc = {}
        self._on_stage_list_ready(devices, com_desc)

    def _on_stage_scan_ready(self, token: StageScanToken, devices, com_desc) -> None:
        ok, reason = self._stage_scan_guard.should_publish(token)
        if not ok:
            if reason in {"panel_closing", "generation_mismatch"}:
                self._log(
                    f"[XIMC scan] finished request_id={token.request_id} but result discarded ({reason})."
                )
            return
        self._log(
            f"[XIMC scan] finished request_id={token.request_id}, applying device list update."
        )
        self._on_stage_list_ready(devices, com_desc)

    def _on_stage_list_ready(self, devices, com_desc) -> None:
        """UI-thread slot: populate the stage device combo."""
        # If user already disconnected the panel, widgets may be gone.
        if not hasattr(self, "_combo_stage_device"):
            return
        self._combo_stage_device.clear()

        def _sort_key(info):
            try:
                dev_id = getattr(info, "device_id", "") or ""
            except Exception:
                dev_id = ""
            m = re.search(r"COM(\d+)", dev_id, re.I)
            return (0, int(m.group(1))) if m else (1, dev_id)

        try:
            devices_sorted = sorted(list(devices or []), key=_sort_key)
        except Exception:
            devices_sorted = list(devices or [])

        if not devices_sorted:
            self._combo_stage_device.addItem("(no device found - click Refresh list)", None)
            return

        com_desc = com_desc or {}
        for d in devices_sorted:
            dev_id = getattr(d, "device_id", None)
            if not dev_id:
                continue
            short = str(dev_id)
            if "COM" in short.upper():
                m = re.search(r"COM\d+", short, re.I)
                if m:
                    com = m.group(0).upper()
                    desc = com_desc.get(com)
                    short = f"{com} — {desc}" if desc else com
            self._combo_stage_device.addItem(f"{short}  —  {dev_id}", dev_id)

    @staticmethod
    def _get_windows_com_descriptions() -> dict[str, str]:
        """Best-effort mapping: COMx -> friendly device description.

        Uses Win32_SerialPort via PowerShell. This works even when XILab is running
        (no need to open the device).
        """
        try:
            cmd = (
                "Get-CimInstance Win32_SerialPort | "
                "Select-Object DeviceID, Description | "
                "ConvertTo-Json -Compress"
            )
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", cmd],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if not out:
                return {}
            data = json.loads(out)
            rows = data if isinstance(data, list) else [data]
            result: dict[str, str] = {}
            for r in rows:
                dev = str((r or {}).get("DeviceID") or "").upper().strip()
                desc = str((r or {}).get("Description") or "").strip()
                if dev.startswith("COM") and desc:
                    result[dev] = desc
            return result
        except Exception:
            return {}

    def _on_motion_enable_toggled(self, enabled: bool) -> None:
        self._check_motion_enable.setText(
            "Motion ENABLED" if enabled else "Enable Motion"
        )
        self._check_motion_enable.setStyleSheet(
            "QPushButton { color: #00cc55; font-weight: bold; }"
            if enabled else ""
        )
        self._update_motion_run_button()

    def _update_motion_run_button(self) -> None:
        # During initial UI construction, the Record+Motion button may not exist yet.
        if not hasattr(self, "_btn_record_motion"):
            return
        protocol_ok = True
        if hasattr(self, "_combo_motion_protocol"):
            protocol_ok = self._combo_motion_protocol.currentIndex() == 0

        scale_ok = True
        try:
            um_per_unit = float(self._spin_stage_um_per_unit.value())
            scale_ok = um_per_unit > 0
        except Exception:
            scale_ok = False

        enabled = (
            self._check_motion_enable.isChecked()
            and protocol_ok
            and scale_ok
            and self._stage is not None
            and self._camera.is_connected
        )
        self._btn_record_motion.setEnabled(enabled)
        self._btn_record_motion.setToolTip(
            "Start synchronized recording + stage motion run.\n"
            "Motion must be enabled and stage must be connected."
        )

    def _load_metric_mapping_profile(self) -> tuple[XimcMetricCalibration | None, str | None]:
        # Optional environment-based mapping profile (legacy/internal path).
        try:
            sp = float(os.environ["BARAKUDA_XIMC_SPEED_REG_PER_UM_S"])
            ap = float(os.environ["BARAKUDA_XIMC_ACCEL_REG_PER_UM_S2"])
            dp = float(os.environ["BARAKUDA_XIMC_DECEL_REG_PER_UM_S2"])
            vid = str(os.environ.get("BARAKUDA_XIMC_MAPPING_VALIDATION_ID", "env_profile"))
            if sp <= 0 or ap <= 0 or dp <= 0:
                return None, "mapping coefficients must be > 0"
            return XimcMetricCalibration(
                speed_reg_per_um_s=sp,
                accel_reg_per_um_s2=ap,
                decel_reg_per_um_s2=dp,
                validation_id=vid,
            ), None
        except Exception:
            return None, "metric mapping profile not set"

    # ------------------------------------------------------------------ #
    #  Stage connect
    # ------------------------------------------------------------------ #

    def _on_stage_connect(self) -> None:
        if self._stage is not None:
            # Disconnect
            try:
                self._stage_svc.disconnect()
            except Exception:
                pass
            self._stage = None
            self._btn_stage_connect.setText("Connect Stage")
            self._lbl_stage_status.setText("Not connected")
            self._update_motion_run_button()
            self._log("Stage disconnected.")
            return

        if not _XIMC_AVAILABLE:
            self._lbl_stage_status.setText(
                "Missing dependency: libximc. In the barakuda environment run: pip install libximc"
            )
            return

        uri = self._combo_stage_device.currentData()
        if not uri:
            self._lbl_stage_status.setText(
                "Select a device from the list or click Refresh list."
            )
            return

        um_per_unit = self._spin_stage_um_per_unit.value()
        try:
            self._stage_svc.connect_ximc(uri=uri, stage_um_per_unit=um_per_unit if um_per_unit > 0 else None)
            self._stage = self._stage_svc.stage
            self._btn_stage_connect.setText("Disconnect Stage")
            self._lbl_stage_status.setText(f"Connected: {uri}")
            self._log(f"Stage connected: {uri}")
        except Exception as exc:
            hint = (
                "Tip: close XILab because it may lock the COM port.\n"
                "If needed, select a different COM port from the list."
            )
            self._lbl_stage_status.setText(f"Connect failed: {exc}\n\n{hint}")
            self._log(f"Stage connect failed: {exc}")

        self._update_motion_run_button()

    # ------------------------------------------------------------------ #
    #  Record + Motion run
    # ------------------------------------------------------------------ #

    def _get_motion_recipe(self) -> ConstantVelocityDragRecipe:
        # Only constant velocity drag is wired for acquisition runs in the MVP.
        if hasattr(self, "_combo_motion_protocol") and self._combo_motion_protocol.currentIndex() != 0:
            raise MotionRunError("Selected protocol is not implemented for Acquisition Record+Motion yet.")
        direction_text = self._combo_motion_direction.currentText()
        direction = 1 if "+1" in direction_text else -1
        um_per_unit = float(self._spin_stage_um_per_unit.value())
        if not (um_per_unit > 0):
            raise MotionRunError("Stage scale (µm/unit) must be known (>0) for metric motion commands.")
        travel_um = float(self._spin_motion_travel_um.value()) if hasattr(self, "_spin_motion_travel_um") else 0.0
        travel_user = float(travel_um) / float(um_per_unit)
        return ConstantVelocityDragRecipe(
            axis=self._combo_motion_axis.currentText(),
            direction=direction,
            travel=travel_user,
            # UI core motion inputs are primary in this panel.
            speed=float(self._spin_motion_speed_reg.value()),
            accel=float(self._spin_motion_accel_um_s2.value()),
            decel=float(self._spin_motion_decel_um_s2.value()),
            pre_delay_s=self._spin_motion_pre_delay.value(),
            post_delay_s=self._spin_motion_post_delay.value(),
            sign_stage_to_image_x=self._spin_motion_sign_x.value(),
            sign_stage_to_image_y=self._spin_motion_sign_y.value(),
        )

    def _on_record_motion(self) -> None:
        if not self._camera.is_connected:
            self._lbl_motion_run_status.setText("Camera not connected.")
            return
        if self._stage is None:
            self._lbl_motion_run_status.setText("Stage not connected.")
            return

        # Acquisition must own the lease during Record+Motion (Phase 3 policy).
        ok, reason = self._stage_svc.request_lease("acquisition", force=True)
        if not ok:
            self._lbl_motion_run_status.setText(reason)
            return
        self._stage_svc.set_run_active(True)

        try:
            recipe = self._get_motion_recipe()
        except MotionRunError as exc:
            self._lbl_motion_run_status.setText(str(exc))
            return
        errors = recipe.validate()
        if errors:
            self._lbl_motion_run_status.setText(f"Recipe error: {'; '.join(errors)}")
            return

        # Metric intent for active command path.
        stage_um_per_unit = self._stage.get_stage_um_per_unit() if self._stage is not None else None
        metric_command: MetricMotionCommand | None = None
        metric_mapping_profile: XimcMetricCalibration | None = None
        if stage_um_per_unit is not None and stage_um_per_unit > 0:
            travel_um = float(self._spin_motion_travel_um.value()) if hasattr(self, "_spin_motion_travel_um") else float(recipe.travel) * float(stage_um_per_unit)
            metric_command = MetricMotionCommand(
                axis=recipe.axis,
                direction=int(recipe.direction),
                travel_um=travel_um,
                # UI keeps speed/accel/decel as primary controls; they are applied
                # directly through recipe/backend fields in this cleanup phase.
                speed_um_s=None,
                accel_um_s2=None,
                decel_um_s2=None,
                pre_delay_s=float(recipe.pre_delay_s),
                post_delay_s=float(recipe.post_delay_s),
            )

            metric_mapping_profile, _ = self._load_metric_mapping_profile()

        requested_roi = self._get_roi_tuple()
        roi = self._sync_roi_to_camera(requested_roi)
        gain = self._spin_gain.value() if self._spin_gain.isEnabled() else None
        requested_basename = self._edit_basename.text().strip()
        resolved_basename, resolved_output_dir = resolve_unique_run_target(
            self._edit_output_dir.text(),
            requested_basename,
        )
        if resolved_basename != (requested_basename or "acquisition_run"):
            self._log(
                f"[OUTPUT-ISOLATION] basename collision resolved: "
                f"{requested_basename!r} -> {resolved_basename!r}"
            )

        self._btn_record_motion.setEnabled(False)
        self._btn_record.setEnabled(False)
        self._btn_start_preview.setEnabled(False)
        self._btn_stop_preview.setEnabled(False)
        self._lbl_motion_run_status.setText("Record+Motion running… 0 s")
        self._lbl_motion_run_status.setStyleSheet("color: #cc4400; font-weight: bold;")
        # Do NOT stop _preview_timer here.  During Record+Motion the camera
        # recording grab loop (record_raw) feeds the shared preview buffer at a
        # throttled rate, so the render timer can keep showing live frames.

        # Elapsed-time heartbeat — updates every second so user sees the app is alive
        self._motion_run_t0 = time.perf_counter()
        self._motion_elapsed_timer = QTimer(self)
        self._motion_elapsed_timer.timeout.connect(self._on_motion_elapsed_tick)
        self._motion_elapsed_timer.start(1000)

        self._log(
            format_record_motion_start_log(
                recipe=recipe,
                metric_command=metric_command,
                metric_mapping_profile=metric_mapping_profile,
                stage_um_per_unit=stage_um_per_unit,
            )
        )

        self._motion_thread = QThread()
        self._motion_worker = _RecordMotionWorker(
            camera=self._camera,
            stage=self._stage,
            recipe=recipe,
            metric_command=metric_command,
            metric_mapping_profile=metric_mapping_profile,
            output_dir=str(resolved_output_dir),
            basename=resolved_basename,
            duration_s=self._spin_duration.value(),
            roi=roi,
            exposure_us=self._spin_exposure.value(),
            gain=gain,
            fps_hint=self._spin_fps_hint.value(),
            pixel_format="Mono8",
        )
        self._motion_worker.moveToThread(self._motion_thread)
        self._motion_thread.started.connect(self._motion_worker.run)
        self._motion_worker.motion_finished.connect(self._on_record_motion_done)
        self._motion_worker.error.connect(self._on_record_motion_error)
        self._motion_worker.progress.connect(self._on_record_progress)
        self._motion_worker.log_msg.connect(
            self._motion_log_signal.emit,
            Qt.ConnectionType.QueuedConnection,
        )

        self._motion_worker.motion_finished.connect(self._motion_thread.quit)
        self._motion_worker.error.connect(self._motion_thread.quit)
        self._motion_thread.finished.connect(self._motion_worker.deleteLater)
        self._motion_thread.finished.connect(
            lambda: setattr(self, "_motion_thread", None)
        )
        self._motion_thread.start()

    def _on_record_motion_done(
        self, record_result: RecordResult, motion_result: MotionRunResult
    ) -> None:
        if self._panel_closing:
            self._stage_svc.set_run_active(False)
            self._stage_svc.release_lease("acquisition")
            self._stop_motion_elapsed_timer()
            return
        self._stage_svc.set_run_active(False)
        self._stage_svc.release_lease("acquisition")
        self._log("[MOTION-LIFECYCLE] done_slot_enter")
        timing_meta = dict(record_result.meta or {})
        timing_source = str(timing_meta.get("timing_source") or "estimated")
        fps_str = (
            f"{record_result.fps_effective:.1f}"
            if record_result.fps_effective else "N/A"
        )
        self._log(
            f"Record+Motion done — frames={record_result.frames_written}  "
            f"fps_eff={fps_str}  dropped={record_result.dropped}  "
            f"timing_source={timing_source}  "
            f"motion_start={motion_result.motion_start_s:.3f}s  "
            f"motion_stop={motion_result.motion_stop_s:.3f}s"
            if motion_result.motion_stop_s is not None else
            f"Record+Motion done — frames={record_result.frames_written}  "
            f"fps_eff={fps_str}  dropped={record_result.dropped}  "
            f"timing_source={timing_source}  "
            f"motion_start={motion_result.motion_start_s:.3f}s  motion_stop=N/A"
        )

        # Write QC
        qc_path: str | None = None
        try:
            fps_target = self._spin_fps_hint.value()
            fps_eff = record_result.fps_effective or 0.0
            fps_ratio = fps_eff / fps_target if fps_target > 0 else 0.0
            reasons: list[str] = []
            if record_result.dropped > 0:
                reasons.append(f"dropped_frames={record_result.dropped}")
            if fps_ratio < 0.95:
                reasons.append(f"fps_ratio={fps_ratio:.3f} < 0.95")
            qc = {
                "pass": len(reasons) == 0,
                "fps_target": fps_target,
                "fps_effective": round(fps_eff, 2),
                "fps_ratio": round(fps_ratio, 4),
                "frames_written": record_result.frames_written,
                "dropped_frames": record_result.dropped,
                "reasons": reasons,
                "motion_mode": "constant_velocity_drag",
                "motion_start_s": motion_result.motion_start_s,
                "motion_stop_s": motion_result.motion_stop_s,
            }
            try:
                stage_meta_path = Path(motion_result.stage_json_path)
                if stage_meta_path.is_file():
                    stage_meta = json.loads(stage_meta_path.read_text(encoding="utf-8"))
                    qc["stage_motion_audit"] = build_stage_motion_audit_dict(stage_meta)
            except Exception:
                pass
            run_dir = Path(record_result.video_path).resolve().parent
            run_basename = Path(record_result.video_path).stem
            qc_path = os.path.join(str(run_dir), run_basename + "_qc.json")
            with open(qc_path, "w", encoding="utf-8") as f:
                json.dump(qc, f, indent=2)
        except Exception:
            pass
        self._update_run_protocol_from_acquisition(
            record_result=record_result,
            qc_path=Path(qc_path) if qc_path else None,
            motion_result=motion_result,
        )
        try:
            stage_meta = self._load_json_file(Path(motion_result.stage_json_path))
            actual_metric = stage_meta.get("actual_metric")
            if not isinstance(actual_metric, dict):
                actual_metric = {}
            cmd_tu = stage_meta.get("travel_user_commanded_raw")
            if cmd_tu is None:
                cmd_tu = stage_meta.get("travel_user_commanded")
            self._update_motion_actual_metric_labels(
                actual_travel_um=(
                    float(actual_metric["actual_travel_um"])
                    if actual_metric.get("actual_travel_um") is not None
                    else None
                ),
                actual_speed_um_s=(
                    float(actual_metric["actual_speed_um_s"])
                    if actual_metric.get("actual_speed_um_s") is not None
                    else None
                ),
                actual_duration_s=(
                    float(actual_metric["actual_motion_duration_s"])
                    if actual_metric.get("actual_motion_duration_s") is not None
                    else None
                ),
                actual_travel_user=(
                    float(stage_meta["actual_travel_user"])
                    if stage_meta.get("actual_travel_user") is not None
                    else None
                ),
                actual_speed_user_s=(
                    float(stage_meta["actual_speed_user_s"])
                    if stage_meta.get("actual_speed_user_s") is not None
                    else None
                ),
                travel_user_commanded=float(cmd_tu) if cmd_tu is not None else None,
            )
        except Exception:
            self._update_motion_actual_metric_labels()

        self._stop_motion_elapsed_timer()
        self._lbl_motion_run_status.setText(
            f"Done — {record_result.frames_written} frames  "
            f"stage.json + stage_trace.csv saved to the output folder"
        )
        self._lbl_motion_run_status.setStyleSheet("color: #00cc55;")
        self._btn_record_motion.setEnabled(True)
        self._btn_record.setEnabled(True)
        self._btn_start_preview.setEnabled(True)
        if not self._panel_closing:
            QTimer.singleShot(200, self._on_start_preview)

    def _on_record_motion_error(self, err: str) -> None:
        if self._panel_closing:
            self._stage_svc.set_run_active(False)
            self._stage_svc.release_lease("acquisition")
            self._stop_motion_elapsed_timer()
            return
        self._stage_svc.set_run_active(False)
        self._stage_svc.release_lease("acquisition")
        self._stop_motion_elapsed_timer()
        self._log(f"Record+Motion FAILED — {err}")
        self._lbl_motion_run_status.setText(f"FAILED: {err}")
        self._lbl_motion_run_status.setStyleSheet("color: #cc3333; font-weight: bold;")
        self._btn_record_motion.setEnabled(True)
        self._btn_record.setEnabled(True)
        self._btn_start_preview.setEnabled(True)

    def _on_motion_elapsed_tick(self) -> None:
        if self._panel_closing:
            return
        elapsed = int(time.perf_counter() - self._motion_run_t0)
        self._lbl_motion_run_status.setText(f"Record+Motion running… {elapsed} s")

    def _on_motion_worker_log(self, msg: str) -> None:
        if self._panel_closing:
            return
        self._log(msg)

    def _stop_motion_elapsed_timer(self) -> None:
        if self._motion_elapsed_timer is not None:
            self._motion_elapsed_timer.stop()
            self._motion_elapsed_timer = None

    def _get_run_output_dir(self) -> Path:
        """Per-run output directory: <output_dir>/<basename>/ (created)."""
        base = Path(self._edit_output_dir.text())
        bn = self._edit_basename.text().strip()
        run_dir = base / (bn or "acquisition_run")
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    # ------------------------------------------------------------------ #

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
            self._update_motion_run_button()
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
        requested_roi = self._get_roi_tuple()
        roi = self._sync_roi_to_camera(requested_roi)
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
        requested_roi = self._get_roi_tuple()
        roi = self._sync_roi_to_camera(requested_roi)
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

    _AVI_FPS_WARN_THRESHOLD = 600.0

    def _on_format_changed(self, _index: int) -> None:
        """Warn the user if AVI is selected while target FPS exceeds the safe threshold."""
        fmt = self._combo_format.currentText()
        fps = self._spin_fps_hint.value()
        if "AVI" in fmt and fps > self._AVI_FPS_WARN_THRESHOLD:
            QMessageBox.warning(
                self,
                "High FPS AVI Warning",
                (
                    f"AVI recording is not reliable above ~{self._AVI_FPS_WARN_THRESHOLD:.0f} FPS.\n\n"
                    "For scientific acquisition use RAW format.\n\n"
                    "AVI is intended only for preview or compatibility\n"
                    "and may produce invalid timestamps at high frame rates."
                ),
            )

    def _on_record(self) -> None:
        if not self._camera.is_connected:
            return

        requested_roi = self._get_roi_tuple()
        roi = self._sync_roi_to_camera(requested_roi)
        gain = self._spin_gain.value() if self._spin_gain.isEnabled() else None

        self._btn_record.setEnabled(False)
        self._btn_stop_record.setEnabled(True)
        self._btn_start_preview.setEnabled(False)
        self._btn_stop_preview.setEnabled(False)
        self._status.setText("Recording…")

        rec_fmt = self._combo_format.currentText().split()[0]  # "RAW" or "AVI"
        dur_s = self._spin_duration.value()
        fps_h = self._spin_fps_hint.value()
        dur_str = f"{dur_s:.1f}s" if dur_s > 0 else "unlimited"
        out_path = str(self._get_run_output_dir())
        bn = self._edit_basename.text()
        self._log(
            f"Recording requested — format={rec_fmt}  duration={dur_str}  "
            f"requestedROI={requested_roi[0]}×{requested_roi[1]}+{requested_roi[2]}+{requested_roi[3]}  "
            f"recordROI={roi[0]}×{roi[1]}+{roi[2]}+{roi[3]}  fps_hint={fps_h:.0f}  "
            f"out={out_path}\\{bn}"
        )
        if rec_fmt == "AVI" and fps_h > self._AVI_FPS_WARN_THRESHOLD:
            self._log(
                f"AVI selected above recommended FPS (>{self._AVI_FPS_WARN_THRESHOLD:.0f}). "
                "AVI timestamps may be unreliable. "
                "RAW format is recommended for scientific acquisition."
            )

        # Start UI countdown
        self._rec_start_time = time.perf_counter()
        self._rec_duration_s = dur_s
        self._lbl_countdown.setVisible(True)
        self._on_countdown_tick()   # immediate first update
        self._countdown_timer.start()

        # Do NOT stop _preview_timer here.  record_raw() feeds the shared
        # preview buffer (_latest_preview_frame) at ~10 fps via the throttled
        # path in the grab loop, so the render timer keeps displaying live
        # frames while recording runs.  The timer is naturally reset by
        # _on_start_preview() once recording finishes.

        self._record_thread = QThread()
        self._record_worker = _RecordWorker(
            camera=self._camera,
            output_dir=str(self._get_run_output_dir()),
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

    def _on_countdown_tick(self) -> None:
        """Update the countdown label every 250 ms (UI only, no effect on recording)."""
        if self._rec_duration_s <= 0:
            self._lbl_countdown.setText("⏺ REC running…")
            return
        elapsed = time.perf_counter() - self._rec_start_time
        remaining = max(0.0, self._rec_duration_s - elapsed)
        self._lbl_countdown.setText(f"⏺ REC: {remaining:.1f} s remaining")

    def _on_sim_raw(self) -> None:
        """Run a simulated RAW recording (no camera needed)."""
        roi = self._get_roi_tuple()
        w, h = roi[0], roi[1]
        fps_target = self._spin_fps_hint.value()
        out_dir = str(self._get_run_output_dir())
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
        self._countdown_timer.stop()
        self._lbl_countdown.setText("✅ REC complete")

        fps_str = (
            f"{result.fps_effective:.1f}" if result.fps_effective else "N/A"
        )
        meta = result.meta or {}
        timing_source = str(meta.get("timing_source") or "estimated")
        timing_detail = str(meta.get("timing_source_detail") or "")
        elapsed_time_s = meta.get("elapsed_time_s")
        req_roi = self._roi_from_meta(meta.get("requested_roi"))
        rec_roi = self._roi_from_meta(meta.get("record_roi"))
        roi_line = ""
        if req_roi is not None and rec_roi is not None:
            roi_line = (
                f"\nRequested ROI: {req_roi[0]}×{req_roi[1]}+{req_roi[2]}+{req_roi[3]}"
                f"\nRecorded ROI:  {rec_roi[0]}×{rec_roi[1]}+{rec_roi[2]}+{rec_roi[3]}"
            )
        elif rec_roi is not None:
            roi_line = f"\nRecorded ROI:  {rec_roi[0]}×{rec_roi[1]}+{rec_roi[2]}+{rec_roi[3]}"
        self._status.setText(
            f"✅ Record done — {result.frames_written} frames, "
            f"fps_eff={fps_str}, dropped={result.dropped}\n"
            f"Timing: {timing_source} ({timing_detail})"
            + (f", elapsed={float(elapsed_time_s):.6f}s" if elapsed_time_s is not None else "")
            + "\n"
            f"Video: {result.video_path}\n"
            f"Meta:  {result.meta_path}"
            f"{roi_line}"
        )
        self._log(
            f"Recording done — frames={result.frames_written}  fps_eff={fps_str}"
            f"  dropped={result.dropped}  timing_source={timing_source}"
            f"  video={result.video_path}"
        )
        if req_roi is not None and rec_roi is not None:
            self._log(
                "Recording ROI chain — "
                f"requested={req_roi[0]}x{req_roi[1]}+{req_roi[2]}+{req_roi[3]} "
                f"recorded={rec_roi[0]}x{rec_roi[1]}+{rec_roi[2]}+{rec_roi[3]}"
            )
        self._last_record_result = result

        # --- Write qc.json ---
        qc_path: str | None = None
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
                str(self._get_run_output_dir()),
                self._edit_basename.text() + "_qc.json",
            )
            with open(qc_path, "w", encoding="utf-8") as f:
                json.dump(qc, f, indent=2)
        except Exception:
            pass
        self._update_run_protocol_from_acquisition(
            record_result=result,
            qc_path=Path(qc_path) if qc_path else None,
            motion_result=None,
        )

        self._btn_record.setEnabled(True)
        self._btn_stop_record.setEnabled(False)
        self._btn_start_preview.setEnabled(True)
        QTimer.singleShot(200, self._on_start_preview)

    def _on_record_error(self, err: str) -> None:
        self._countdown_timer.stop()
        self._lbl_countdown.setText("❌ REC stopped")
        self._status.setText(f"❌ Record error: {err}")
        self._log(f"Recording FAILED — {err}")
        self._btn_record.setEnabled(True)
        self._btn_stop_record.setEnabled(False)
        self._btn_start_preview.setEnabled(True)

    def _on_record_progress(self, frames: int, elapsed: float) -> None:
        fps_target = self._spin_fps_hint.value()
        fps_eff_est = frames / elapsed if elapsed > 0.5 else 0.0
        fps_ratio = fps_eff_est / fps_target if fps_target > 0 else 0.0
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
            f"Recording… FPS~{fps_eff_est:.0f} ({pct:.0f}%) "
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

    def _sync_roi_to_camera(self, roi: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """Snap ROI using the same current constraints as the camera-facing UI controls."""
        w = self._snap_down(int(roi[0]), self._w_inc, self._w_min, self._sensor_w)
        h = self._snap_down(int(roi[1]), self._h_inc, self._h_min, self._sensor_h)
        ox = self._snap_down(int(roi[2]), self._ox_inc, 0, self._sensor_w - w)
        oy = self._snap_down(int(roi[3]), self._oy_inc, 0, self._sensor_h - h)
        snapped = (w, h, ox, oy)

        self._set_roi_tuple(snapped)
        if snapped != roi:
            self._log(
                "ROI snapped for record — "
                f"requested={roi[0]}x{roi[1]}+{roi[2]}+{roi[3]} "
                f"snapped={snapped[0]}x{snapped[1]}+{snapped[2]}+{snapped[3]}"
            )
        self._update_status_line()
        self._render_info_text()
        return snapped

    def _set_roi_tuple(self, roi: tuple[int, int, int, int]) -> None:
        w, h, ox, oy = roi
        self._roi_sync_lock = True
        try:
            for key, val in [("roi_w", w), ("roi_h", h), ("roi_ox", ox), ("roi_oy", oy)]:
                self._roi_spins[key].blockSignals(True)
                self._roi_spins[key].setValue(int(val))
                self._roi_spins[key].blockSignals(False)
                self._roi_sliders[key].blockSignals(True)
                self._roi_sliders[key].setValue(int(val))
                self._roi_sliders[key].blockSignals(False)
            self._snap_and_clamp_roi_controls()
            self._sync_slider_from_spin("roi_w")
            self._apply_roi_overlay_from_controls()
        finally:
            self._roi_sync_lock = False

    @staticmethod
    def _roi_from_meta(payload) -> tuple[int, int, int, int] | None:
        if not isinstance(payload, dict):
            return None
        try:
            return (
                int(payload["w"]),
                int(payload["h"]),
                int(payload["x"]),
                int(payload["y"]),
            )
        except Exception:
            return None

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
            rr_meta = rr.meta or {}
            timing_source = str(rr_meta.get("timing_source") or "estimated")
            lines.append(
                f"Last rec: {rr.frames_written}fr  fps_eff={fps_e}  drop={rr.dropped}  timing={timing_source}"
            )
            lines.append(f"  video: {rr.video_path}")
            lines.append(f"  meta : {rr.meta_path}")
            meta = rr.meta or {}
            req_roi = self._roi_from_meta(meta.get("requested_roi"))
            rec_roi = self._roi_from_meta(meta.get("record_roi"))
            if req_roi is not None:
                lines.append(f"  reqROI: {req_roi[0]}x{req_roi[1]}+{req_roi[2]}+{req_roi[3]}")
            if rec_roi is not None:
                lines.append(f"  recROI: {rec_roi[0]}x{rec_roi[1]}+{rec_roi[2]}+{rec_roi[3]}")

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

    def _on_open_protocol(self) -> None:
        run_dir = self._get_run_output_dir()
        dlg = RunProtocolDialog(run_folder=run_dir, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_json_file(path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _try_git_revision() -> tuple[str | None, str | None]:
        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            branch = None
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            commit = None
        return branch, commit

    def _update_run_protocol_from_acquisition(
        self,
        *,
        record_result: RecordResult,
        qc_path: Path | None,
        motion_result: MotionRunResult | None,
    ) -> None:
        run_dir = Path(record_result.video_path).resolve().parent
        basename = Path(record_result.video_path).stem
        meta_path = Path(record_result.meta_path)
        meta = dict(record_result.meta or {})
        if not meta and meta_path.is_file():
            meta = self._load_json_file(meta_path)

        stage_meta: dict = {}
        if motion_result is not None and motion_result.stage_json_path.is_file():
            stage_meta = self._load_json_file(Path(motion_result.stage_json_path))

        recording_mode = str(
            meta.get("format") or Path(record_result.video_path).suffix.lstrip(".")
        ).lower()
        fps_hint = meta.get("fps_target_hint", self._spin_fps_hint.value())
        timestamps_present = bool(meta.get("timestamps_path"))
        if not timestamps_present:
            timestamps_present = (run_dir / f"{basename}_timestamps.csv").is_file()
        selected_timestamps_path = meta.get("timestamps_path")
        if not selected_timestamps_path:
            maybe_ts = run_dir / f"{basename}_timestamps.csv"
            if maybe_ts.is_file():
                selected_timestamps_path = str(maybe_ts.resolve())

        branch, commit = self._try_git_revision()
        updates: dict = {
            "identity": {
                "run_id": basename,
                "source_type": recording_mode,
                "acquired_in_barakuda": True,
                "imported_external": False,
                "git_branch": branch,
                "git_commit": commit,
            },
            "acquisition": {
                "output_folder": str(run_dir),
                "basename": basename,
                "recording_mode": recording_mode,
                "fps_hint": fps_hint,
                "frame_count": meta.get("frame_count", meta.get("frames_written")),
                "t_first_s": meta.get("t_first_s"),
                "t_last_s": meta.get("t_last_s"),
                "elapsed_time_s": meta.get("elapsed_time_s", meta.get("duration_s")),
                "effective_fps": meta.get("effective_fps", meta.get("fps_effective")),
                "timing_source": meta.get("timing_source", "estimated"),
                "timing_source_detail": meta.get("timing_source_detail"),
                "timestamp_validation_pass": meta.get("timestamp_validation_pass"),
                "timestamp_validation_message": meta.get("timestamp_validation_message"),
                "exposure_us": meta.get("exposure_us"),
                "gain": meta.get("gain"),
                "pixel_format": meta.get("pixel_format"),
                "roi": meta.get("record_roi") or meta.get("requested_roi"),
                "timestamps_present": timestamps_present,
                "camera_dropped_frames": meta.get("dropped_frames"),
            },
        }

        if qc_path is not None:
            updates["provenance"] = {
                **dict(updates.get("provenance") or {}),
                "selected_qc_path": str(qc_path.resolve()),
            }
        updates["provenance"] = {
            **dict(updates.get("provenance") or {}),
            "selected_timestamps_path": selected_timestamps_path,
            "selected_sidecar_paths": {
                "meta_path": str(meta_path.resolve()) if meta_path.is_file() else None,
                "timestamps_path": selected_timestamps_path,
                "qc_path": str(qc_path.resolve()) if qc_path is not None else None,
            },
            "used_fallbacks": {},
        }

        if stage_meta:
            metric_provenance = stage_meta.get("metric_provenance")
            if not isinstance(metric_provenance, dict):
                metric_provenance = {}
            actual_metric = stage_meta.get("actual_metric")
            if not isinstance(actual_metric, dict):
                actual_metric = {}

            updates["motion"] = {
                "protocol_type": stage_meta.get("mode"),
                "axis": stage_meta.get("axis"),
                "direction": stage_meta.get("direction"),
                # Raw XIMC register command values (primary semantics for speed/accel/decel).
                "speed_raw_reg": stage_meta.get("speed_reg_commanded_raw", stage_meta.get("speed_user_s_commanded")),
                "accel_raw_reg": stage_meta.get("accel_reg_commanded_raw", stage_meta.get("accel_user_s2_commanded")),
                "decel_raw_reg": stage_meta.get("decel_reg_commanded_raw", stage_meta.get("decel_user_s2_commanded")),
                "speed_reg_readback_raw": stage_meta.get("speed_reg_readback_raw"),
                # Legacy compatibility aliases.
                "speed": stage_meta.get("speed_user_s_commanded"),
                "accel": stage_meta.get("accel_user_s2_commanded"),
                "decel": stage_meta.get("decel_user_s2_commanded"),
                "pre_delay_s": stage_meta.get("pre_delay_s"),
                "post_delay_s": stage_meta.get("post_delay_s"),
                "stage_um_per_unit": stage_meta.get("stage_um_per_unit"),
                "sign_stage_to_image_x": stage_meta.get("sign_stage_to_image_x"),
                "sign_stage_to_image_y": stage_meta.get("sign_stage_to_image_y"),
                "commanded_travel_user": stage_meta.get("travel_user_commanded"),
                "actual_speed_user_s": stage_meta.get("actual_speed_user_s"),
                "actual_speed_um_s": actual_metric.get("actual_speed_um_s"),
                "pre_motion_status_flags": stage_meta.get("pre_motion_status_flags"),
                "pre_motion_gpio_flags": stage_meta.get("pre_motion_gpio_flags"),
                "pre_motion_alarm_nonfatal_allowed": stage_meta.get("pre_motion_alarm_nonfatal_allowed"),
                "speed_effect_suspect": stage_meta.get("speed_effect_suspect"),
                "speed_control_validation_status": stage_meta.get("speed_control_validation_status"),
                "speed_control_validation_reasons": stage_meta.get("speed_control_validation_reasons"),
            }
            updates["provenance"] = {
                **dict(updates.get("provenance") or {}),
                "stage_um_per_unit_source": metric_provenance.get(
                    "stage_um_per_unit_source"
                ),
                "selected_stage_meta_path": str(
                    Path(motion_result.stage_json_path).resolve()
                ),
                "selected_stage_trace_path": str(
                    Path(motion_result.stage_trace_path).resolve()
                ),
                "selected_sidecar_paths": {
                    **dict((updates.get("provenance") or {}).get("selected_sidecar_paths") or {}),
                    "stage_meta_path": str(Path(motion_result.stage_json_path).resolve()),
                    "stage_trace_path": str(Path(motion_result.stage_trace_path).resolve()),
                },
            }

        try:
            existing = load_protocol(run_dir)
        except Exception:
            existing = create_protocol_from_context()
        try:
            merged = merge_protocol(existing, updates, allow_manual_overwrite=False)
            saved_path = save_protocol(merged, run_dir)
            self._log(f"Run protocol updated: {saved_path}")
        except Exception as exc:
            self._log(f"Run protocol update skipped: {exc}")

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

    def _mark_panel_closing(self) -> None:
        if self._panel_closing:
            return
        self._panel_closing = True
        self._stage_scan_guard.cancel_all()
        try:
            _STAGE_SCAN_BRIDGE.ready.disconnect(self._on_stage_scan_ready)
        except Exception:
            pass
        self._log("[XIMC scan] cancelled: panel closing/destruction.")

    def closeEvent(self, event) -> None:
        self._mark_panel_closing()
        self._camera.disconnect()
        super().closeEvent(event)

    def deleteLater(self) -> None:
        self._mark_panel_closing()
        self._camera.disconnect()
        super().deleteLater()
