from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt, QObject, QEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QProgressBar,
    QFormLayout, QDoubleSpinBox, QCheckBox, QSpinBox,
    QToolButton, QHBoxLayout, QMenu, QComboBox, QScrollArea, QFrame,
    QSizePolicy, QAbstractSpinBox, QTabWidget
)

class NoWheelValueChangeFilter(QObject):
    """Event filter that blocks mouse wheel from changing values in scrollable panels."""
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return False


class PipelinePanel(QWidget):
    run_selected_clicked = pyqtSignal()
    run_batch_clicked = pyqtSignal()
    preview_gate_clicked = pyqtSignal()
    gate_report_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()

    measure_clicked = pyqtSignal()
    track_range_clicked = pyqtSignal()

    save_dataset_scale_clicked = pyqtSignal()
    auto_roi_clicked = pyqtSignal()
    
    
    # Emitted when a user asks to load a specific profile (str: profile_name)
    load_profile_requested = pyqtSignal(str)
    # Emitted when a user asks to save the current settings into a profile (str: profile_name)
    save_profile_requested = pyqtSignal(str)

    # Emitted whenever any user-editable parameter changes value
    value_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)



        # Preview Gate split-button (STRICT default) with popup policy menu
        self._preview_gate_policy = "STRICT"  # STRICT | ROBUST | CUSTOM

        self.btn_preview_gate = QToolButton()
        self.btn_preview_gate.setText("Preview Gate")
        self.btn_preview_gate.setToolTip("Evaluate tracking quality on a few frames before full run.")
        self.btn_preview_gate.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_preview_gate.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        from PyQt6.QtWidgets import QSizePolicy
        self.btn_preview_gate.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_preview_gate.setMinimumHeight(26)

        gate_menu = QMenu(self)
        act_strict = gate_menu.addAction("STRICT (pass_ratio = 1.0)")
        act_robust = gate_menu.addAction("ROBUST (pass_ratio = 0.85)")
        act_custom = gate_menu.addAction("CUSTOM (use panel thresholds)")

        def _set_policy(p: str) -> None:
            self._preview_gate_policy = p
            if p == "STRICT":
                self.btn_preview_gate.setText("Preview Gate \u25b8 STRICT")
            elif p == "ROBUST":
                self.btn_preview_gate.setText("Preview Gate \u25b8 ROBUST")
            else:
                self.btn_preview_gate.setText("Preview Gate \u25b8 CUSTOM")

        act_strict.triggered.connect(lambda: _set_policy("STRICT"))
        act_robust.triggered.connect(lambda: _set_policy("ROBUST"))
        act_custom.triggered.connect(lambda: _set_policy("CUSTOM"))

        self.btn_preview_gate.setMenu(gate_menu)
        _set_policy("STRICT")  # initialize label

        self.btn_preview_gate.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.btn_preview_gate.customContextMenuRequested.connect(
            lambda pos: gate_menu.exec(self.btn_preview_gate.mapToGlobal(pos))
        )

        self.btn_preview_gate.clicked.connect(self.preview_gate_clicked.emit)

        self.btn_gate_report = QPushButton("Report\u2026")
        self.btn_gate_report.setToolTip("View detailed report of the Preview Gate results.")
        self.btn_gate_report.setEnabled(False)
        self.btn_run = QPushButton("RUN")
        self.btn_run.setToolTip("Start processing the selected files.")
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setToolTip("Stop the current batch processing.")
        self.btn_reset = QPushButton("Reset OT Defaults")
        self.btn_reset.setToolTip("Reset all settings to their default values.")

        self.btn_gate_report.clicked.connect(self.gate_report_clicked.emit)
        self.btn_run.clicked.connect(self.run_batch_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_reset.clicked.connect(self.apply_ot_defaults)

        self._progress_label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setValue(0)

        # preprocess (keep, not used yet)
        self._normalize_strength = QDoubleSpinBox()
        self._normalize_strength.setRange(0.0, 5.0)
        self._normalize_strength.setSingleStep(0.1)
        self._normalize_strength.setValue(1.0)

        # ── Compute ───────────────────────────────────────────────

        # tracking params
        self._tracking_lbl = QLabel("Tracking: Radial Symmetry")
        self._tracking_lbl.setStyleSheet("color: #666; font-weight: bold;")

        self.btn_auto_roi = QPushButton("Auto-detect particle")
        self.btn_auto_roi.setToolTip("Automatically find and center the ROI on the most prominent particle.")
        self.auto_roi_on_load_cb = QCheckBox("Auto ROI on load")
        self.auto_roi_on_load_cb.setToolTip("If checked, automatically run Auto-detect when a new video is selected.")
        self.auto_roi_on_load_cb.setChecked(True)
        self.btn_auto_roi.clicked.connect(self.auto_roi_clicked.emit)

        self._roi_margin = QDoubleSpinBox()
        self._roi_margin.setRange(1.2, 3.0)
        self._roi_margin.setSingleStep(0.1)
        self._roi_margin.setValue(1.8)
        self._roi_margin.setToolTip("Multiplier for ROI size based on bead diameter. Smaller = faster tracking.")

        self._adaptive_roi = QCheckBox("Adaptive ROI (follow particle)")
        self._adaptive_roi.setToolTip("Automatically track particle center to maintain it within the ROI during motion.")
        self._adaptive_roi.setChecked(True)

        self._invert = QCheckBox("Invert particle (dark spot)")
        self._invert.setToolTip("Check if the particle appears darker than the background.")
        self._invert.setChecked(True)

        self._blur_sigma = QDoubleSpinBox()
        self._blur_sigma.setRange(0.0, 10.0)
        self._blur_sigma.setSingleStep(0.2)
        self._blur_sigma.setValue(1.2)
        self._blur_sigma.setToolTip("Gaussian blur sigma applied before tracking to reduce noise. 0 = no blur.")

        self._radial_grad_threshold = QDoubleSpinBox()
        self._radial_grad_threshold.setRange(0.0, 1000.0)
        self._radial_grad_threshold.setSingleStep(0.5)
        self._radial_grad_threshold.setValue(2.0)
        self._radial_grad_threshold.setToolTip("Threshold for the radial gradient. Ignores weak edges.")

        self._auto_polarity = QCheckBox("Auto polarity (detect bright/dark)")
        self._auto_polarity.setToolTip("Automatically determine the correct 'Invert' setting by scoring both.")
        self._auto_polarity.setChecked(True)

        # annulus refinement
        self._use_annulus = QCheckBox("Annulus refinement (RS)")
        self._use_annulus.setToolTip("Use an annular background region to improve Radial Symmetry tracking accuracy.")
        self._use_annulus.setChecked(True)

        self._annulus_auto = QCheckBox("Auto annulus (estimate size)")
        self._annulus_auto.setToolTip("Automatically estimate optimal inner and outer radii for the annulus.")
        self._annulus_auto.setChecked(True)

        self._annulus_r_inner = QDoubleSpinBox()
        self._annulus_r_inner.setRange(0.0, 1e6)
        self._annulus_r_inner.setDecimals(2)
        self._annulus_r_inner.setSingleStep(0.5)
        self._annulus_r_inner.setValue(0.0)
        self._annulus_r_inner.setToolTip("Inner radius of the background annulus in pixels (if not Auto).")

        self._annulus_r_outer = QDoubleSpinBox()
        self._annulus_r_outer.setRange(0.0, 1e6)
        self._annulus_r_outer.setDecimals(2)
        self._annulus_r_outer.setSingleStep(0.5)
        self._annulus_r_outer.setValue(0.0)
        self._annulus_r_outer.setToolTip("Outer radius of the background annulus in pixels (if not Auto).")

        self._annulus_profile_smooth = QSpinBox()
        self._annulus_profile_smooth.setRange(0, 999)
        self._annulus_profile_smooth.setValue(3)
        self._annulus_profile_smooth.setToolTip("Smoothing factor for the radial intensity profile.")

        # Preview Gate QC thresholds (applies to multi-frame gate)
        self._gate_sample_count = QSpinBox()
        self._gate_sample_count.setRange(1, 99)
        self._gate_sample_count.setValue(7)
        self._gate_sample_count.setToolTip("Number of frames to evaluate for the preview gate.")

        self._gate_pass_min_ratio = QDoubleSpinBox()
        self._gate_pass_min_ratio.setRange(0.0, 1.0)
        self._gate_pass_min_ratio.setDecimals(3)
        self._gate_pass_min_ratio.setSingleStep(0.05)
        self._gate_pass_min_ratio.setValue(1.0)
        self._gate_pass_min_ratio.setToolTip("Minimum ratio of frames that must pass QC to accept the particle.")

        self._gate_q_min = QDoubleSpinBox()
        self._gate_q_min.setRange(0.0, 1e12)
        self._gate_q_min.setDecimals(6)
        self._gate_q_min.setSingleStep(0.1)
        self._gate_q_min.setValue(0.0)
        self._gate_q_min.setToolTip("Minimum tracking quality score for a frame to pass the Preview Gate.")

        self._gate_jump_max = QDoubleSpinBox()
        self._gate_jump_max.setRange(0.0, 1e6)
        self._gate_jump_max.setDecimals(3)
        self._gate_jump_max.setSingleStep(1.0)
        self._gate_jump_max.setValue(50.0)
        self._gate_jump_max.setToolTip("Maximum allowed position jump between frames in pixels before failing QC.")

        # range
        self._start_frame = QSpinBox()
        self._start_frame.setRange(0, 10**9)
        self._start_frame.setValue(0)
        self._start_frame.setToolTip("First frame to process.")

        self._end_frame = QSpinBox()
        self._end_frame.setRange(0, 10**9)
        self._end_frame.setValue(0)
        self._end_frame.setToolTip("Last frame to process.")

        # scale
        self._fps_override = QDoubleSpinBox()
        self._fps_override.setRange(0.0, 1e6)
        self._fps_override.setDecimals(2)
        self._fps_override.setSingleStep(10.0)
        self._fps_override.setValue(0.0)
        self._fps_override.setToolTip("Override video FPS for OT calculations. 0 = use video metadata.")

        self._use_dataset_scale = QCheckBox("Use dataset scale (µm/px)")
        self._use_dataset_scale.setToolTip("Use the scale factor saved with this dataset, if available.")
        self._use_dataset_scale.setChecked(True)

        self._um_per_px = QDoubleSpinBox()
        self._um_per_px.setRange(0.0, 1e6)
        self._um_per_px.setDecimals(6)
        self._um_per_px.setSingleStep(0.000001)
        # Default scale for OT (µm/px) — requested baseline.
        self._um_per_px.setValue(0.066528)
        self._um_per_px.setToolTip("Manual pixel scale in micrometers per pixel.")

        self._scale_status = QLabel("Scale: not set (px only)")
        self._scale_status.setStyleSheet("color: #666;")

        self.btn_save_scale = QPushButton("Save current scale as dataset default")
        self.btn_save_scale.setToolTip("Save the above scale value to the current dataset's sidecar file.")
        self.btn_save_scale.clicked.connect(self.save_dataset_scale_clicked.emit)

        # ── Export ───────────────────────────────────────────────
        self._export_dataset_path: str | None = None
        self._export_paths: list[str] = []  # all selected paths for batch export

        export_box = QWidget()
        _exp_layout = QVBoxLayout(export_box)
        _exp_layout.setContentsMargins(0, 0, 0, 8)
        _exp_layout.setSpacing(6)

        _exp_header = QLabel("OT Dataset Export")
        _exp_header.setStyleSheet("font-weight: bold; color: #555;")
        _exp_layout.addWidget(_exp_header)

        _exp_sel_row = QHBoxLayout()
        self._btn_open_export_dataset = QPushButton("Open dataset (item.json)…")
        self._btn_open_export_dataset.setToolTip(
            "Select an item.json to browse its analysis outputs and export them."
        )
        self._btn_open_export_dataset.clicked.connect(self._on_open_export_dataset)
        _exp_sel_row.addWidget(self._btn_open_export_dataset)
        _exp_sel_row.addStretch(1)
        _exp_layout.addLayout(_exp_sel_row)

        self._export_status_lbl = QLabel("No dataset loaded.")
        self._export_status_lbl.setWordWrap(True)
        self._export_status_lbl.setStyleSheet("color: #666;")
        _exp_layout.addWidget(self._export_status_lbl)

        self._export_files_lbl = QLabel("")
        self._export_files_lbl.setWordWrap(True)
        self._export_files_lbl.setStyleSheet("color: #444; font-size: 10px;")
        _exp_layout.addWidget(self._export_files_lbl)

        # Dynamic checkboxes for discovered artifacts (id -> QCheckBox)
        self._export_artifact_checkboxes: dict[str, QCheckBox] = {}
        self._export_artifacts: list[dict] = []  # last discovery result for Export button
        self._export_artifacts_container = QWidget()
        self._export_artifacts_layout = QVBoxLayout(self._export_artifacts_container)
        self._export_artifacts_layout.setContentsMargins(0, 4, 0, 4)
        _exp_layout.addWidget(self._export_artifacts_container)

        _exp_bulk_row = QHBoxLayout()
        self._btn_export_select_all = QPushButton("Select All")
        self._btn_export_select_all.setToolTip("Check all visible export artifact checkboxes.")
        self._btn_export_select_all.clicked.connect(self._on_export_select_all)
        _exp_bulk_row.addWidget(self._btn_export_select_all)
        self._btn_export_clear_all = QPushButton("Clear All")
        self._btn_export_clear_all.setToolTip("Uncheck all visible export artifact checkboxes.")
        self._btn_export_clear_all.clicked.connect(self._on_export_clear_all)
        _exp_bulk_row.addWidget(self._btn_export_clear_all)
        _exp_bulk_row.addStretch(1)
        _exp_layout.addLayout(_exp_bulk_row)

        self._btn_export_all = QPushButton("EXPORT")
        self._btn_export_all.setToolTip(
            "Export selected artifacts to this dataset's exports/ folder."
        )
        self._btn_export_all.setEnabled(False)
        self._btn_export_all.clicked.connect(self._on_export_all_clicked)
        _exp_layout.addWidget(self._btn_export_all)

        _exp_layout.addStretch(1)
        
        # ── Postprocess ───────────────────────────────────────────────
        self._pp_enabled = QCheckBox("Enable OT-3.1 postprocess (QC + drift)")
        self._pp_enabled.setToolTip("Apply quality control and drift correction after tracking.")
        self._pp_enabled.setChecked(True)

        self._qc_enabled = QCheckBox("Track-loss flag (QC)")
        self._qc_enabled.setToolTip("Flag tracking results that fail quality control criteria.")
        self._qc_enabled.setChecked(True)

        self._qc_q_min = QDoubleSpinBox()
        self._qc_q_min.setRange(0.0, 1e12)
        self._qc_q_min.setDecimals(6)
        self._qc_q_min.setSingleStep(0.1)
        self._qc_q_min.setValue(0.0)
        self._qc_q_min.setToolTip("Minimum acceptable quality score for tracking.")

        self._qc_jump_max = QDoubleSpinBox()
        self._qc_jump_max.setRange(0.0, 1e6)
        self._qc_jump_max.setDecimals(3)
        self._qc_jump_max.setSingleStep(1.0)
        self._qc_jump_max.setValue(50.0)
        self._qc_jump_max.setToolTip("Maximum allowed position jump between frames in pixels before failing QC.")

        self._drift_mode = QComboBox()
        self._drift_mode.addItem("None (passthrough)", "none")
        self._drift_mode.addItem("Lowpass filter subtract", "lowpass_subtract")
        self._drift_mode.addItem("Linear detrend subtract", "detrend_linear")
        self._drift_mode.setCurrentIndex(1)  # Default: lowpass_subtract
        self._drift_mode.setToolTip("Method to remove low-frequency drift from the particle trajectory.")

        self._drift_window_s = QDoubleSpinBox()
        self._drift_window_s.setRange(0.0, 1e6)
        self._drift_window_s.setDecimals(3)
        self._drift_window_s.setSingleStep(0.1)
        self._drift_window_s.setValue(1.0)
        self._drift_window_s.setToolTip("Time window in seconds for the drift correction filter.")

        # Strategy Selector
        self._strategy_selector = QComboBox()
        self._strategy_selector.setToolTip("Calibration strategy used to compute stiffness and conversion factors.")

        self._stage_speed = QDoubleSpinBox()
        self._stage_speed.setRange(0.0, 1e9)
        self._stage_speed.setDecimals(6)
        self._stage_speed.setSingleStep(1.0)
        self._stage_speed.setValue(0.0)
        self._stage_speed.setToolTip("Stage speed in µm/s (used for Drag calibration).")

        self._drag_axis = QComboBox()
        self._drag_axis.addItem("x", "x")
        self._drag_axis.addItem("y", "y")
        self._drag_axis.setCurrentIndex(0)
        self._drag_axis.setToolTip("Axis along which the manual drag was performed.")

        self._viscosity = QDoubleSpinBox()
        self._viscosity.setRange(0.0, 10.0)
        self._viscosity.setDecimals(6)
        self._viscosity.setSingleStep(0.0005)
        self._viscosity.setValue(0.001)  # Pa·s
        self._viscosity.setToolTip("Dynamic viscosity of the medium in Pascal-seconds (Pa·s). Default is water.")

        self._temperature_c = QDoubleSpinBox()
        self._temperature_c.setRange(-10.0, 100.0)
        self._temperature_c.setDecimals(2)
        self._temperature_c.setSingleStep(0.5)
        self._temperature_c.setValue(25.0)
        self._temperature_c.setToolTip("Temperature in Celsius. Effects viscosity calculation if enabled.")

        self._bead_diameter_um = QDoubleSpinBox()
        self._bead_diameter_um.setRange(0.1, 100.0)
        self._bead_diameter_um.setDecimals(3)
        self._bead_diameter_um.setSingleStep(0.1)
        self._bead_diameter_um.setValue(1.0)  # DEFAULT as requested (most common)
        self._bead_diameter_um.setToolTip("Diameter of the trapped bead in micrometers.")

        # ── Tracking tab ──
        params_box = QWidget()
        self.params_box_layout = QFormLayout(params_box)
        params_box_layout = self.params_box_layout  # local alias for readability

        self._trk_advanced = QCheckBox("Advanced options")
        self._trk_advanced.setToolTip("Show experimental / advanced tracking options.")
        self._trk_advanced.setChecked(False)
        params_box_layout.addRow("", self._trk_advanced)

        params_box_layout.addRow("", self._tracking_lbl)
        params_box_layout.addRow("", self.btn_auto_roi)
        params_box_layout.addRow("", self.auto_roi_on_load_cb)
        params_box_layout.addRow("ROI margin", self._roi_margin)
        params_box_layout.addRow("", self._adaptive_roi)
        params_box_layout.addRow("Bead diameter (µm)", self._bead_diameter_um)
        
        # Advanced Tracking rows
        params_box_layout.addRow("Blur sigma", self._blur_sigma)
        params_box_layout.addRow("Radial grad threshold", self._radial_grad_threshold)
        
        # These are always hidden but we can still toggle their visibility if we wanted
        self._normalize_strength.setVisible(False)
        self._auto_polarity.setVisible(False)
        self._invert.setVisible(False)

        params_box_layout.addRow("", self._use_annulus)
        params_box_layout.addRow("", self._annulus_auto)
        params_box_layout.addRow("Annulus r_inner (px)", self._annulus_r_inner)
        params_box_layout.addRow("Annulus r_outer (px)", self._annulus_r_outer)
        params_box_layout.addRow("Annulus smooth (bins)", self._annulus_profile_smooth)

        params_box_layout.addRow("Gate samples", self._gate_sample_count)
        
        # Gate Advanced
        params_box_layout.addRow("Gate pass ratio", self._gate_pass_min_ratio)
        params_box_layout.addRow("Gate QC score min", self._gate_q_min)
        params_box_layout.addRow("Gate Max jump (px)", self._gate_jump_max)
        
        def _on_trk_advanced_toggled(checked: bool):
            self._set_row_visible(self._blur_sigma, checked)
            self._set_row_visible(self._radial_grad_threshold, checked)
            self._set_row_visible(self._annulus_r_inner, checked)
            self._set_row_visible(self._annulus_r_outer, checked)
            self._set_row_visible(self._annulus_profile_smooth, checked)
            
            self._set_row_visible(self._gate_pass_min_ratio, checked)
            self._set_row_visible(self._gate_q_min, checked)
            self._set_row_visible(self._gate_jump_max, checked)

        # Connection moved to end of __init__ (after apply_ot_defaults) to survive
        # the blanket toggled.disconnect() inside _wire_value_changed_signals
        _on_trk_advanced_toggled(False)  # set initial hidden state immediately

        params_box_layout.addRow("FPS Override (0=auto)", self._fps_override)
        params_box_layout.addRow("", self._use_dataset_scale)
        params_box_layout.addRow("Scale (µm/px)", self._um_per_px)
        params_box_layout.addRow("", self._scale_status)
        params_box_layout.addRow("", self.btn_save_scale)

        post_box = QWidget()
        self.post_box_layout = QFormLayout(post_box)
        
        # Advanced toggle
        self._pp_advanced = QCheckBox("Advanced options")
        self._pp_advanced.setToolTip("Show experimental / advanced postprocessing options.")
        self._pp_advanced.setChecked(False)
        self.post_box_layout.addRow("", self._pp_advanced)
        
        self.post_box_layout.addRow("", self._pp_enabled)
        self.post_box_layout.addRow("", self._qc_enabled)
        
        # Hide debug/advanced postprocessing controls
        self.post_box_layout.addRow("QC: Minimum score", self._qc_q_min)
        self.post_box_layout.addRow("QC: Maximum jump (px)", self._qc_jump_max)
        
        self._qc_q_min.setVisible(False)
        self._qc_jump_max.setVisible(False)
        self._set_row_visible(self._qc_q_min, False)
        self._set_row_visible(self._qc_jump_max, False)
        
        def _on_advanced_toggled(checked: bool):
            self._set_row_visible(self._qc_q_min, checked)
            self._set_row_visible(self._qc_jump_max, checked)
            self._set_row_visible(self._drift_window_s, checked)
            
        # Connection moved to end of __init__ (after apply_ot_defaults) to survive
        # the blanket toggled.disconnect() inside _wire_value_changed_signals
        _on_advanced_toggled(False)  # set initial hidden state immediately

        self.post_box_layout.addRow("Drift mode", self._drift_mode)
        self.post_box_layout.addRow("Drift window (old, s)", self._drift_window_s)
        self.post_box_layout.addRow("Calibration Strategy", self._strategy_selector)
        self.post_box_layout.addRow("Temperature (°C)", self._temperature_c)
        self.post_box_layout.addRow("Stage speed (µm/s)", self._stage_speed)
        self.post_box_layout.addRow("Drag axis", self._drag_axis)
        self.post_box_layout.addRow("Viscosity η (Pa·s)", self._viscosity)
        
        self._calibration_mode = "Brownian"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ══════════════════════════════════════════════════════════
        # TABS: replacing scrollable collapsibles
        # ══════════════════════════════════════════════════════════
        self.tabs = QTabWidget()
        
        tab_run = QWidget()
        tab_run_layout = QVBoxLayout(tab_run)
        tab_run_layout.setContentsMargins(8, 8, 8, 8)
        
        # ── Profile Management ──
        prof_box = QWidget()
        prof_layout = QVBoxLayout(prof_box)
        prof_layout.setContentsMargins(0, 0, 0, 10)
        
        prof_lbl = QLabel("OT Pipeline Profile")
        prof_lbl.setStyleSheet("font-weight: bold; color: #555;")
        
        row1 = QHBoxLayout()
        self._profile_combo = QComboBox()
        self._profile_combo.setToolTip("Select a processing profile.")
        self._profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row1.addWidget(self._profile_combo)
        
        row2 = QHBoxLayout()
        self.btn_save_profile = QPushButton("Save Profile")
        self.btn_save_profile.setToolTip("Save current settings to the active profile.")
        self.btn_save_profile_as = QPushButton("Save As...")
        self.btn_save_profile_as.setToolTip("Save current settings as a new profile.")
        row2.addWidget(self.btn_save_profile)
        row2.addWidget(self.btn_save_profile_as)
        row2.addStretch(1)

        prof_layout.addWidget(prof_lbl)
        prof_layout.addLayout(row1)
        prof_layout.addLayout(row2)
        tab_run_layout.addWidget(prof_box)

        # ── Frame range ──
        range_form = QWidget()
        range_layout = QFormLayout(range_form)
        range_layout.setContentsMargins(0, 0, 0, 4)
        range_layout.addRow("Start frame", self._start_frame)
        range_layout.addRow("End frame", self._end_frame)
        tab_run_layout.addWidget(range_form)

        sep_range = QFrame()
        sep_range.setFrameShape(QFrame.Shape.HLine)
        sep_range.setStyleSheet("color: #ddd;")
        tab_run_layout.addWidget(sep_range)

        # ── Action buttons ──
        tab_run_layout.addWidget(self.btn_preview_gate)
        tab_run_layout.addWidget(self.btn_gate_report)
        tab_run_layout.addWidget(self.btn_run)
        tab_run_layout.addWidget(self.btn_stop)
        tab_run_layout.addWidget(self.btn_reset)
        tab_run_layout.addWidget(self._progress_label)
        tab_run_layout.addWidget(self.progress)
        tab_run_layout.addStretch(1)

        tab_tracking = QWidget()
        tab_tracking_layout = QVBoxLayout(tab_tracking)
        tab_tracking_layout.setContentsMargins(8, 8, 8, 8)
        scroll_trk = QScrollArea()
        scroll_trk.setWidgetResizable(True)
        scroll_trk.setFrameShape(QFrame.Shape.NoFrame)
        scroll_trk.setWidget(params_box)
        tab_tracking_layout.addWidget(scroll_trk)

        tab_postprocess = QWidget()
        tab_postprocess_layout = QVBoxLayout(tab_postprocess)
        tab_postprocess_layout.setContentsMargins(8, 8, 8, 8)
        scroll_post = QScrollArea()
        scroll_post.setWidgetResizable(True)
        scroll_post.setFrameShape(QFrame.Shape.NoFrame)
        scroll_post.setWidget(post_box)
        tab_postprocess_layout.addWidget(scroll_post)
        
        tab_export = QWidget()
        tab_export_layout = QVBoxLayout(tab_export)
        tab_export_layout.setContentsMargins(8, 8, 8, 8)
        scroll_exp = QScrollArea()
        scroll_exp.setWidgetResizable(True)
        scroll_exp.setFrameShape(QFrame.Shape.NoFrame)
        scroll_exp.setWidget(export_box)
        tab_export_layout.addWidget(scroll_exp)

        tab_settings = QWidget()
        tab_settings_layout = QVBoxLayout(tab_settings)
        tab_settings_layout.setContentsMargins(8, 8, 8, 8)
        settings_box = QWidget()
        settings_box_layout = QFormLayout(settings_box)

        # Compute Backend
        self._compute_backend = QComboBox()
        self._compute_backend.addItems(["Auto", "CPU", "GPU"])
        self._compute_backend.setCurrentText("CPU")
        self._compute_backend.setEnabled(False)
        self._compute_backend.setToolTip("OT pipeline currently supports CPU only.")

        # Advanced Master Toggle
        self._master_advanced = QCheckBox("Advanced options")
        self._master_advanced.setToolTip("Show experimental / advanced options across all tabs.")
        self._master_advanced.setChecked(False)

        def _on_master_advanced_toggled(checked: bool):
            self._trk_advanced.setChecked(checked)
            self._pp_advanced.setChecked(checked)

        self._master_advanced.toggled.connect(_on_master_advanced_toggled)

        settings_box_layout.addRow("Compute backend", self._compute_backend)
        settings_box_layout.addRow("", self._master_advanced)

        scroll_set = QScrollArea()
        scroll_set.setWidgetResizable(True)
        scroll_set.setFrameShape(QFrame.Shape.NoFrame)
        scroll_set.setWidget(settings_box)
        tab_settings_layout.addWidget(scroll_set)

        self.tabs.addTab(tab_run, "Run")
        self.tabs.addTab(tab_tracking, "Tracking")
        self.tabs.addTab(tab_postprocess, "Postprocess")
        self.tabs.addTab(tab_export, "Export")
        self.tabs.addTab(tab_settings, "Settings")

        layout.addWidget(self.tabs, stretch=1)
        
        # ── Wheel Blocker ─────────────────────────────────────────
        self._wheel_blocker = NoWheelValueChangeFilter(self)
        for w in self.findChildren(QAbstractSpinBox):
            w.installEventFilter(self._wheel_blocker)
        for w in self.findChildren(QComboBox):
            w.installEventFilter(self._wheel_blocker)
            
        self.apply_ot_defaults()

        # One-time profile signal wiring (must NOT be inside apply_ot_defaults
        # to avoid duplicate connections on every "Reset OT Defaults" press)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_combo_changed)
        self.btn_save_profile.clicked.connect(self._on_save_profile_clicked)
        self.btn_save_profile_as.clicked.connect(self._on_save_profile_as_clicked)

        # One-time advanced-toggle wiring: placed here (AFTER apply_ot_defaults)
        # so _wire_value_changed_signals cannot destroy them.
        self._trk_advanced.toggled.connect(_on_trk_advanced_toggled)
        self._pp_advanced.toggled.connect(_on_advanced_toggled)

    def apply_ot_defaults(self) -> None:
        """Apply requested sensible defaults to the OT user parameters."""
        self._preview_gate_policy = "STRICT"
        self.btn_preview_gate.setText("Preview Gate \u25b8 STRICT")
        self._normalize_strength.setValue(1.0)
        
        # Tracking Defaults
        self.auto_roi_on_load_cb.setChecked(True)
        self._roi_margin.setValue(1.8)
        self._adaptive_roi.setChecked(True)
        self._invert.setChecked(True)
        self._blur_sigma.setValue(1.2)
        self._radial_grad_threshold.setValue(2.0)
        self._auto_polarity.setChecked(True)
        
        # Annulus Defaults
        self._use_annulus.setChecked(True)
        self._annulus_auto.setChecked(True)
        self._annulus_r_inner.setValue(0.0)
        self._annulus_r_outer.setValue(0.0)
        self._annulus_profile_smooth.setValue(3)
        
        # Gate Defaults
        self._gate_sample_count.setValue(7)
        self._gate_pass_min_ratio.setValue(1.0)
        self._gate_q_min.setValue(0.0)
        self._gate_jump_max.setValue(50.0)
        
        # Scale Defaults
        self._use_dataset_scale.setChecked(True)
        self._um_per_px.setValue(0.066528)
        
        # Postprocess Defaults
        self._pp_enabled.setChecked(True)
        self._qc_enabled.setChecked(True)
        self._qc_q_min.setValue(0.0)
        self._qc_jump_max.setValue(50.0)
        self._drift_mode.setCurrentIndex(1)  # lowpass_subtract
        self._drift_window_s.setValue(1.0)
        
        self.set_calibration_mode("Brownian")
        
        self._stage_speed.setValue(0.0)
        self._drag_axis.setCurrentIndex(0)
        self._viscosity.setValue(0.001)
        self._viscosity.setValue(0.001)
        self._temperature_c.setValue(25.0)
        self._bead_diameter_um.setValue(1.0)

        # Settings Defaults
        if hasattr(self, '_master_advanced'):
            self._master_advanced.setChecked(False)
        if hasattr(self, '_compute_backend'):
            self._compute_backend.setCurrentText("CPU")
        
        self._wire_value_changed_signals()

    # -------------------- Profile UI wiring --------------------

    def update_profile_list(self, profiles: list[str], active_profile: str = "") -> None:
        """Update the combo box block signalling to prevent load_profile_requested triggers."""
        was_blocked = self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        
        if not profiles:
            self._profile_combo.addItem("<No profiles found>")
            self._profile_combo.setEnabled(False)
            self.btn_save_profile.setEnabled(False)
        else:
            self._profile_combo.setEnabled(True)
            self.btn_save_profile.setEnabled(True)
            for p in profiles:
                self._profile_combo.addItem(p)
                
            if active_profile:
                idx = self._profile_combo.findText(active_profile)
                if idx >= 0:
                    self._profile_combo.setCurrentIndex(idx)
                    
        self._profile_combo.blockSignals(was_blocked)

    def _on_profile_combo_changed(self, idx: int) -> None:
        if idx < 0 or not self._profile_combo.isEnabled():
            return
        prof_name = self._profile_combo.currentText()
        if prof_name:
            self.load_profile_requested.emit(prof_name)
            
    def _on_save_profile_clicked(self) -> None:
        if not self._profile_combo.isEnabled(): return
        prof_name = self._profile_combo.currentText()
        if prof_name:
            self.save_profile_requested.emit(prof_name)
            
    def _on_save_profile_as_clicked(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        prof_name, ok = QInputDialog.getText(self, "Save Profile As", "New profile name:")
        if ok and prof_name.strip():
            self.save_profile_requested.emit(prof_name.strip())

    # -------------------- Per-video UI wiring --------------------

    def _wire_value_changed_signals(self) -> None:
        """Connect all interactive elements to emit value_changed."""
        def _emit(*args, **kwargs):
            self.value_changed.emit()
            
        # Hook up inputs (QDoubleSpinBox, QSpinBox)
        for w in self.findChildren(QAbstractSpinBox):
            if hasattr(w, "valueChanged"):
                try: w.valueChanged.disconnect() 
                except: pass
                w.valueChanged.connect(_emit)
                
        # Hook up checkboxes
        for w in self.findChildren(QCheckBox):
            if hasattr(w, "toggled"):
                try: w.toggled.disconnect()
                except: pass
                w.toggled.connect(_emit)
                
        # Hook up comboboxes
        for w in self.findChildren(QComboBox):
            if hasattr(w, "currentIndexChanged"):
                try: w.currentIndexChanged.disconnect()
                except: pass
                w.currentIndexChanged.connect(_emit)

    def dump_ot_params(self) -> dict:
        return {
            "tracking": self.get_tracking_params(),
            "postprocess": self.get_postprocess_params(),
            "scale": self.get_scale_params(),
            "frame_range": self.get_frame_range(),
            # add gate policy to save too
            "gate_policy": self._preview_gate_policy,
        }
        
    def load_ot_params(self, d: dict) -> None:
        # Block signals during loading to avoid loopbacks
        was_blocked = self.blockSignals(True)
        
        # Load from dict, mapping to controls appropriately.
        tp = d.get("tracking", {})
        self._roi_margin.setValue(tp.get("roi_margin", 1.8))
        self._adaptive_roi.setChecked(tp.get("adaptive_roi", True))
        self._invert.setChecked(tp.get("invert", True))
        self._blur_sigma.setValue(tp.get("blur_sigma", 1.2))
        self._radial_grad_threshold.setValue(tp.get("radial_grad_threshold", 2.0))
        self._auto_polarity.setChecked(tp.get("auto_polarity", True))
        self._use_annulus.setChecked(tp.get("annulus_enabled", True))
        self._annulus_auto.setChecked(tp.get("annulus_auto", True))
        self._annulus_r_inner.setValue(tp.get("annulus_r_inner_px") or 0.0)
        self._annulus_r_outer.setValue(tp.get("annulus_r_outer_px") or 0.0)
        self._annulus_profile_smooth.setValue(tp.get("annulus_profile_smooth", 3))
        self._fps_override.setValue(tp.get("fps_override", 0.0))

        pp = d.get("postprocess", {})
        self._pp_enabled.setChecked(pp.get("enabled", True))
        self._qc_enabled.setChecked(pp.get("qc_enabled", True))
        self._qc_q_min.setValue(pp.get("q_min", 0.0))
        self._qc_jump_max.setValue(pp.get("jump_max_px", 50.0))
        dt_mode = pp.get("drift_mode", "detrend_linear")
        idx = self._drift_mode.findData(dt_mode)
        if idx >= 0:
            self._drift_mode.setCurrentIndex(idx)
        self._drift_window_s.setValue(pp.get("drift_window_s", 1.0))
        self._temperature_c.setValue(pp.get("temperature_c", 25.0))
        self._bead_diameter_um.setValue(pp.get("bead_diameter_um", 1.0))
        
        if "stage_speed_um_s" in pp:
            self._stage_speed.setValue(pp.get("stage_speed_um_s", 0.0))
        if "drag_axis" in pp:
            idx = self._drag_axis.findData(pp.get("drag_axis", "x"))
            if idx >= 0: self._drag_axis.setCurrentIndex(idx)
        if "viscosity_pa_s" in pp:
            self._viscosity.setValue(pp.get("viscosity_pa_s", 0.001))

        sp = d.get("scale", {})
        self._use_dataset_scale.setChecked(sp.get("use_dataset_scale", True))
        self._um_per_px.setValue(sp.get("um_per_px", 0.066528))
        
        fr = d.get("frame_range", [0, 0])
        self._start_frame.setValue(fr[0])
        self._end_frame.setValue(fr[1])
        
        gp = d.get("gate_policy", "STRICT")
        self._preview_gate_policy = gp
        self.btn_preview_gate.setText(f"Preview Gate ▹ {gp}")

        self.blockSignals(was_blocked)
        # Manually trigger a UI refresh event for parents
        self.value_changed.emit()

    # -------------------- API pro Shell --------------------

    def get_preview_gate_params(self) -> dict:
        return {
            "sample_count": int(self._gate_sample_count.value()),
            "pass_min_ratio": float(self._gate_pass_min_ratio.value()),
            "q_min": float(self._gate_q_min.value()),
            "jump_max_px": float(self._gate_jump_max.value()),
        }

    def get_gate_policy(self) -> str:
        return str(self._preview_gate_policy)

    def set_batch_running(self, running: bool) -> None:
        """Toggle progress bar between indeterminate pulse and idle."""
        if running:
            self.progress.setRange(0, 0)  # indeterminate pulse
            self._progress_label.setText("Starting\u2026")
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self._progress_label.setText("Ready")
            
        # Disable buttons that shouldn't be clicked during run
        for b in [self.btn_save_scale]:
            if hasattr(self, b): # Just in case
                getattr(self, b).setEnabled(not running)
            else:
                # Direct access if known
                self.btn_save_scale.setEnabled(not running)

    def set_batch_progress(self, done: int, total: int, filename: str = "", pct: int = 0) -> None:
        """Update file counter label and progress bar value (pct = 0..100 within current video)."""
        if total <= 0:
            return
        label = f"File {done + 1} / {total}" if pct < 100 else f"File {done} / {total} ✅"
        if filename:
            label += f"  —  {filename}"
        if pct < 100:
            label += f"  ({pct}%)"
        self._progress_label.setText(label)
        self.progress.setRange(0, 100)
        self.progress.setValue(pct)

    def get_tracking_params(self) -> dict:
        # method UI is removed, keep RS as default
        use_ann = bool(self._use_annulus.isChecked())
        r_in = float(self._annulus_r_inner.value())
        r_out = float(self._annulus_r_outer.value())
        
        is_adv = bool(self._trk_advanced.isChecked())
            
        pms = {
            "method": "RADIAL_SYMMETRY",
            "compute_profile": "auto",
            "roi_margin": float(self._roi_margin.value()),
            "adaptive_roi": bool(self._adaptive_roi.isChecked()),
            "invert": bool(self._invert.isChecked()),
            "blur_sigma": float(self._blur_sigma.value()),
            "radial_grad_threshold": float(self._radial_grad_threshold.value()),
            "auto_polarity": bool(self._auto_polarity.isChecked()),
            "annulus_enabled": use_ann,
            "annulus_auto": (bool(self._annulus_auto.isChecked()) if use_ann else False),
            "annulus_r_inner_px": (None if (not use_ann or r_in <= 0) else r_in),
            "annulus_r_outer_px": (None if (not use_ann or r_out <= 0) else r_out),
            "annulus_profile_smooth": int(self._annulus_profile_smooth.value()),
            "fps_override": float(self._fps_override.value()),
        }
        
        # If Advanced is OFF, force safe defaults for hidden parameters
        if not is_adv:
            pms["blur_sigma"] = 1.2
            pms["radial_grad_threshold"] = 2.0
            if use_ann:
                pms["annulus_auto"] = True 

        return pms

    def get_postprocess_params(self) -> dict:
        mode = getattr(self, "_calibration_mode", "Brownian")
        is_adv = bool(self._master_advanced.isChecked()) if hasattr(self, '_master_advanced') else False
        
        params = {
            "enabled": bool(self._pp_enabled.isChecked()),
            "qc_enabled": bool(self._qc_enabled.isChecked()),
            "q_min": float(self._qc_q_min.value()),
            "jump_max_px": float(self._qc_jump_max.value()),
            "drift_mode": str(self._drift_mode.currentData()),
            "drift_window_s": float(self._drift_window_s.value()),
            "export_um_columns": True,
            "calibration_mode": mode,
            "strategy": str(self._strategy_selector.currentData()),
            "temperature_c": float(self._temperature_c.value()),
            "bead_diameter_um": float(self._bead_diameter_um.value()),
        }
        
        # If Advanced is OFF, force safe defaults for hidden parameters
        if not is_adv:
            params["q_min"] = 0.0
            params["jump_max_px"] = 50.0
            params["drift_window_s"] = 1.0

        if mode == "Drag":
            params.update({
                "stage_speed_um_s": float(self._stage_speed.value()),
                "drag_axis": str(self._drag_axis.currentData()),
                "viscosity_pa_s": float(self._viscosity.value()),
            })
        return params

    def get_strategy_params(self) -> dict:
        mode = getattr(self, "_calibration_mode", "Brownian")
        params = {
            "calibration_mode": mode,
            "strategy": str(self._strategy_selector.currentData()),
            "temperature_c": float(self._temperature_c.value()),
            "bead_diameter_um": float(self._bead_diameter_um.value()),
        }
        if mode == "Drag":
            params.update({
                "stage_speed_um_s": float(self._stage_speed.value()),
                "drag_axis": str(self._drag_axis.currentData()),
                "viscosity_pa_s": float(self._viscosity.value()),
            })
        return params

    def get_scale_params(self) -> dict:
        return {
            "use_dataset_scale": bool(self._use_dataset_scale.isChecked()),
            "um_per_px": float(self._um_per_px.value()),
        }

    def get_frame_range(self) -> tuple[int, int]:
        return int(self._start_frame.value()), int(self._end_frame.value())



    def set_scale_status(self, text: str) -> None:
        self._scale_status.setText(text)

    def set_um_per_px(self, value: float) -> None:
        try:
            self._um_per_px.setValue(float(value))
        except Exception:
            pass

    def set_end_frame(self, end_frame: int) -> None:
        self._end_frame.setValue(int(end_frame))

    def _set_row_visible(self, field: QWidget, visible: bool) -> None:
        field.setVisible(visible)
        # Check Tracking layout
        if hasattr(self, "params_box_layout") and self.params_box_layout is not None:
            label = self.params_box_layout.labelForField(field)
            if label:
                label.setVisible(visible)
        # Check Postprocess layout
        if hasattr(self, "post_box_layout") and self.post_box_layout is not None:
            label = self.post_box_layout.labelForField(field)
            if label:
                label.setVisible(visible)

    def _update_strategy_dropdown(self, mode: str) -> None:
        current_data = str(self._strategy_selector.currentData()) if self._strategy_selector.currentData() else ""

        self._strategy_selector.blockSignals(True)
        self._strategy_selector.clear()

        if mode == "Brownian":
            self._strategy_selector.addItem("PSD_Welch (Scipy/Hann)", "PSD_Welch")
            self._strategy_selector.addItem("PSD_ProcFFT (MATLAB)", "PSD_ProcFFT")
            
            idx = self._strategy_selector.findData(current_data)
            if idx >= 0:
                self._strategy_selector.setCurrentIndex(idx)
            else:
                self._strategy_selector.setCurrentIndex(0)
                import logging
                logging.getLogger(__name__).info(f"Strategy auto-switched to PSD_Welch for mode {mode}")
                
        elif mode == "Drag":
            self._strategy_selector.addItem("Drag (Constant Velocity)", "Drag_ConstantVelocity")
            
            idx = self._strategy_selector.findData(current_data)
            if idx >= 0:
                self._strategy_selector.setCurrentIndex(idx)
            else:
                self._strategy_selector.setCurrentIndex(0)
                import logging
                logging.getLogger(__name__).info(f"Strategy auto-switched to Drag_ConstantVelocity for mode {mode}")
                
        self._strategy_selector.blockSignals(False)

    def set_calibration_mode(self, mode: str) -> None:
        self._calibration_mode = str(mode)
        self._update_strategy_dropdown(mode)
        
        if mode == "Brownian":
            self._set_row_visible(self._stage_speed, False)
            self._set_row_visible(self._drag_axis, False)
            self._set_row_visible(self._viscosity, False)
            self._set_row_visible(self._bead_diameter_um, True)
        elif mode == "Drag":
            self._set_row_visible(self._stage_speed, True)
            self._set_row_visible(self._drag_axis, True)
            self._set_row_visible(self._viscosity, True)
            self._set_row_visible(self._bead_diameter_um, True)

    def is_auto_roi_on_load(self) -> bool:
        return self.auto_roi_on_load_cb.isChecked()

    # ── Export tab helpers ────────────────────────────────────────────────────

    def set_dataset_path(self, path_str: str) -> None:
        """Set the active dataset path (item.json or video). Refreshes export status."""
        self._export_dataset_path = str(path_str) if path_str else None
        self._refresh_export_status()

    def set_export_paths(self, paths: list) -> None:
        """Set the list of dataset paths to use when exporting (e.g. multi-selection)."""
        self._export_paths = [str(p) for p in paths] if paths else []

    def _on_open_export_dataset(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open OT dataset manifest",
            "",
            "Dataset manifest (item.json);;All files (*)",
        )
        if path_str:
            self._export_dataset_path = path_str
            self._refresh_export_status()

    def _refresh_export_status(self) -> None:
        from pathlib import Path as _Path

        p = self._export_dataset_path
        if not p:
            self._export_status_lbl.setText("No dataset loaded.")
            self._export_files_lbl.setText("")
            self._btn_export_all.setEnabled(False)
            self._refresh_export_artifact_checkboxes([])
            return

        path = _Path(p)

        # Accept both item.json directly and video paths inside the item folder
        item_json: _Path | None = None
        if path.name == "item.json":
            item_json = path
        else:
            for candidate in (
                path.parent / "item.json",
                path.parent.parent / "item.json",
            ):
                if candidate.is_file():
                    item_json = candidate
                    break

        if item_json is None:
            self._export_status_lbl.setText(f"No item.json found near:\n{p}")
            self._export_files_lbl.setText("")
            self._btn_export_all.setEnabled(False)
            self._refresh_export_artifact_checkboxes([])
            return

        try:
            from barakuda.devices.optical_tweezers.manifest import load_item_manifest
            from barakuda.devices.optical_tweezers.export import discover_analysis_artifacts

            m = load_item_manifest(item_json)

            lines: list[str] = [f"Item: {item_json.parent.name}"]
            file_lines: list[str] = []

            if m.analysis_dir is not None and m.analysis_dir.is_dir():
                try:
                    rel = m.analysis_dir.relative_to(m.item_root)
                except ValueError:
                    rel = m.analysis_dir
                lines.append(f"Analysis: {rel}")
                for f in sorted(m.analysis_dir.rglob("*")):
                    if f.is_file():
                        try:
                            file_lines.append(f"  {f.relative_to(m.item_root)}")
                        except Exception:
                            file_lines.append(f"  {f.name}")
            else:
                lines.append("No analysis folder found yet — run the pipeline first.")

            if m.exports_dir is not None and m.exports_dir.is_dir():
                try:
                    rel = m.exports_dir.relative_to(m.item_root)
                except ValueError:
                    rel = m.exports_dir
                lines.append(f"Exports: {rel}")

            self._export_status_lbl.setText("\n".join(lines))
            self._export_files_lbl.setText(
                "\n".join(file_lines) if file_lines else "  (no files yet)"
            )

            artifacts = discover_analysis_artifacts(m.item_root)
            self._export_artifacts = artifacts
            self._refresh_export_artifact_checkboxes(artifacts)

        except Exception as _e:
            self._export_status_lbl.setText(f"Error loading manifest:\n{_e!r}")
            self._export_files_lbl.setText("")
            self._btn_export_all.setEnabled(False)
            self._refresh_export_artifact_checkboxes([])

    def _refresh_export_artifact_checkboxes(self, artifacts: list[dict]) -> None:
        """Rebuild artifact checkboxes from discovery result, grouped by DATA / REPORTS / PLOTS."""
        while self._export_artifacts_layout.count():
            child = self._export_artifacts_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._export_artifact_checkboxes.clear()

        artifacts_by_id = {a["id"]: a for a in artifacts}
        group_style = "font-weight: bold; color: #555; font-size: 11px; margin-top: 6px;"

        groups = [
            ("DATA", ["trajectory_csv", "tracking_csv", "psd_csv"]),
            ("REPORTS", ["qc_report", "run_json"]),
            ("PLOTS", []),
        ]

        for group_label, artifact_ids in groups:
            group_artifacts = [(aid, artifacts_by_id[aid]) for aid in artifact_ids if aid in artifacts_by_id]
            if not group_artifacts:
                continue
            header = QLabel(group_label)
            header.setStyleSheet(group_style)
            self._export_artifacts_layout.addWidget(header)
            for aid, art in group_artifacts:
                cb = QCheckBox(art["label"])
                cb.setEnabled(True)
                cb.setChecked(True)
                cb.stateChanged.connect(self._update_export_button_state)
                self._export_artifacts_layout.addWidget(cb)
                self._export_artifact_checkboxes[art["id"]] = cb

        self._update_export_button_state()

    def _update_export_button_state(self) -> None:
        """Enable EXPORT only when at least one export artifact checkbox is checked."""
        has_any = bool(self._export_artifact_checkboxes)
        any_checked = any(cb.isChecked() for cb in self._export_artifact_checkboxes.values())
        self._btn_export_all.setEnabled(has_any and any_checked)

    def _on_export_select_all(self) -> None:
        """Check all currently visible export artifact checkboxes."""
        for cb in self._export_artifact_checkboxes.values():
            cb.setChecked(True)

    def _on_export_clear_all(self) -> None:
        """Uncheck all currently visible export artifact checkboxes."""
        for cb in self._export_artifact_checkboxes.values():
            cb.setChecked(False)

    def _on_export_all_clicked(self) -> None:
        from pathlib import Path as _Path
        import shutil as _shutil

        paths_to_export = (
            self._export_paths
            if self._export_paths
            else ([self._export_dataset_path] if self._export_dataset_path else [])
        )
        if not paths_to_export:
            return

        art_by_id = {a["id"]: a for a in self._export_artifacts}
        total_copied = 0
        export_dirs: list[str] = []
        try:
            for p in paths_to_export:
                path = _Path(p)
                item_json: _Path | None = None
                if path.name == "item.json":
                    item_json = path
                else:
                    for candidate in (
                        path.parent / "item.json",
                        path.parent.parent / "item.json",
                    ):
                        if candidate.is_file():
                            item_json = candidate
                            break

                if item_json is None:
                    continue

                item_root = item_json.parent
                exports_dir = item_root / "exports"
                exports_dir.mkdir(parents=True, exist_ok=True)

                for aid, cb in self._export_artifact_checkboxes.items():
                    if not cb.isChecked():
                        continue
                    art = art_by_id.get(aid)
                    if not art:
                        continue
                    src = item_root / art["path"]
                    if not src.is_file():
                        continue
                    dst = exports_dir / _Path(art["path"]).name
                    _shutil.copy2(src, dst)
                    total_copied += 1

                export_dirs.append(str(exports_dir))

            if export_dirs:
                self._export_status_lbl.setText(
                    f"Exported {total_copied} file(s) to:\n" + "\n".join(export_dirs)
                )
            else:
                self._export_status_lbl.setText("Export failed: no valid dataset path(s).")
        except Exception as _e:
            self._export_status_lbl.setText(f"Export error:\n{_e!r}")
