from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QProgressBar,
    QFormLayout, QDoubleSpinBox, QCheckBox, QSpinBox,
    QToolButton, QHBoxLayout, QMenu, QComboBox
)


class PipelinePanel(QWidget):
    run_selected_clicked = pyqtSignal()
    run_batch_clicked = pyqtSignal()
    preview_gate_clicked = pyqtSignal()
    gate_report_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()

    measure_clicked = pyqtSignal()
    track_range_clicked = pyqtSignal()

    save_dataset_scale_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)



        # Preview Gate split-button (STRICT default) with popup policy menu
        self._preview_gate_policy = "STRICT"  # STRICT | ROBUST | CUSTOM

        self.btn_preview_gate = QToolButton()
        self.btn_preview_gate.setText("Preview Gate")
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
        self.btn_gate_report.setEnabled(False)
        self.btn_run = QPushButton("RUN")
        self.btn_stop = QPushButton("STOP")

        self.btn_gate_report.clicked.connect(self.gate_report_clicked.emit)
        self.btn_run.clicked.connect(self.run_batch_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)

        self._progress_label = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setValue(0)

        # preprocess (keep, not used yet)
        self._normalize_strength = QDoubleSpinBox()
        self._normalize_strength.setRange(0.0, 5.0)
        self._normalize_strength.setSingleStep(0.1)
        self._normalize_strength.setValue(1.0)

        # tracking params
        # Adaptive ROI is critical for kmitající částice (drift + Brownian motion).
        self._adaptive_roi = QCheckBox("Adaptive ROI (follow particle)")
        self._adaptive_roi.setChecked(True)

        self._invert = QCheckBox("Invert particle (dark spot)")
        self._invert.setChecked(True)

        self._blur_sigma = QDoubleSpinBox()
        self._blur_sigma.setRange(0.0, 10.0)
        self._blur_sigma.setSingleStep(0.2)
        self._blur_sigma.setValue(1.2)

        self._radial_grad_threshold = QDoubleSpinBox()
        self._radial_grad_threshold.setRange(0.0, 1000.0)
        self._radial_grad_threshold.setSingleStep(0.5)
        self._radial_grad_threshold.setValue(2.0)

        self._auto_polarity = QCheckBox("Auto polarity (try invert True/False)")
        self._auto_polarity.setChecked(True)

        # annulus refinement
        self._use_annulus = QCheckBox("Use annulus refinement (RS)")
        self._use_annulus.setChecked(True)

        self._annulus_auto = QCheckBox("Auto annulus (estimate ring)")
        self._annulus_auto.setChecked(True)

        self._annulus_r_inner = QDoubleSpinBox()
        self._annulus_r_inner.setRange(0.0, 1e6)
        self._annulus_r_inner.setDecimals(2)
        self._annulus_r_inner.setSingleStep(0.5)
        self._annulus_r_inner.setValue(0.0)

        self._annulus_r_outer = QDoubleSpinBox()
        self._annulus_r_outer.setRange(0.0, 1e6)
        self._annulus_r_outer.setDecimals(2)
        self._annulus_r_outer.setSingleStep(0.5)
        self._annulus_r_outer.setValue(0.0)

        self._annulus_profile_smooth = QSpinBox()
        self._annulus_profile_smooth.setRange(0, 999)
        self._annulus_profile_smooth.setValue(3)

        # Preview Gate QC thresholds (applies to multi-frame gate)
        self._gate_sample_count = QSpinBox()
        self._gate_sample_count.setRange(1, 99)
        self._gate_sample_count.setValue(7)

        self._gate_pass_min_ratio = QDoubleSpinBox()
        self._gate_pass_min_ratio.setRange(0.0, 1.0)
        self._gate_pass_min_ratio.setDecimals(3)
        self._gate_pass_min_ratio.setSingleStep(0.05)
        self._gate_pass_min_ratio.setValue(1.0)

        self._gate_q_min = QDoubleSpinBox()
        self._gate_q_min.setRange(0.0, 1e12)
        self._gate_q_min.setDecimals(6)
        self._gate_q_min.setSingleStep(0.1)
        self._gate_q_min.setValue(0.0)

        self._gate_jump_max = QDoubleSpinBox()
        self._gate_jump_max.setRange(0.0, 1e6)
        self._gate_jump_max.setDecimals(3)
        self._gate_jump_max.setSingleStep(1.0)
        self._gate_jump_max.setValue(50.0)

        # range
        self._start_frame = QSpinBox()
        self._start_frame.setRange(0, 10**9)
        self._start_frame.setValue(0)

        self._end_frame = QSpinBox()
        self._end_frame.setRange(0, 10**9)
        self._end_frame.setValue(0)

        # scale
        self._use_dataset_scale = QCheckBox("Use dataset scale (µm/px)")
        self._use_dataset_scale.setChecked(True)

        self._um_per_px = QDoubleSpinBox()
        self._um_per_px.setRange(0.0, 1e6)
        self._um_per_px.setDecimals(6)
        self._um_per_px.setSingleStep(0.000001)
        # Default scale for OT (µm/px) — requested baseline.
        self._um_per_px.setValue(0.066528)

        self._scale_status = QLabel("Scale: not set (px only)")
        self._scale_status.setStyleSheet("color: #666;")

        self.btn_save_scale = QPushButton("Save current scale as dataset default")
        self.btn_save_scale.clicked.connect(self.save_dataset_scale_clicked.emit)

        # OT-3.1 postprocess (QC + drift)
        self._pp_enabled = QCheckBox("Enable OT-3.1 postprocess (QC + drift)")
        self._pp_enabled.setChecked(True)

        self._qc_enabled = QCheckBox("Track-loss flag (QC)")
        self._qc_enabled.setChecked(True)

        self._qc_q_min = QDoubleSpinBox()
        self._qc_q_min.setRange(0.0, 1e12)
        self._qc_q_min.setDecimals(6)
        self._qc_q_min.setSingleStep(0.1)
        self._qc_q_min.setValue(0.0)

        self._qc_jump_max = QDoubleSpinBox()
        self._qc_jump_max.setRange(0.0, 1e6)
        self._qc_jump_max.setDecimals(3)
        self._qc_jump_max.setSingleStep(1.0)
        self._qc_jump_max.setValue(50.0)

        self._drift_mode = QComboBox()
        self._drift_mode.addItem("None (passthrough)", "none")
        self._drift_mode.addItem("Lowpass filter subtract", "lowpass_subtract")
        self._drift_mode.addItem("Linear detrend subtract", "detrend_linear")
        self._drift_mode.setCurrentIndex(1)  # Default: lowpass_subtract

        self._drift_window_s = QDoubleSpinBox()
        self._drift_window_s.setRange(0.0, 1e6)
        self._drift_window_s.setDecimals(3)
        self._drift_window_s.setSingleStep(0.1)
        self._drift_window_s.setValue(1.0)

        # Strategy Selector
        self._strategy_selector = QComboBox()
        self._strategy_selector.addItem("PSD_Welch (Scipy/Hann)", "PSD_Welch")
        self._strategy_selector.addItem("PSD_ProcFFT (MATLAB)", "PSD_ProcFFT")
        self._strategy_selector.addItem("Drag (Constant Velocity)", "Drag_ConstantVelocity")
        self._strategy_selector.addItem("Piezo Oscillation (Coming soon...)", "Piezo_Oscillation")
        
        # Disable the Piezo option
        model = self._strategy_selector.model()
        if hasattr(model, 'item'): 
            item = model.item(3)
            if item:
                item.setEnabled(False)
        self._strategy_selector.setCurrentIndex(0)

        self._stage_speed = QDoubleSpinBox()
        self._stage_speed.setRange(0.0, 1e9)
        self._stage_speed.setDecimals(6)
        self._stage_speed.setSingleStep(1.0)
        self._stage_speed.setValue(0.0)

        self._drag_axis = QComboBox()
        self._drag_axis.addItem("x", "x")
        self._drag_axis.addItem("y", "y")
        self._drag_axis.setCurrentIndex(0)

        self._viscosity = QDoubleSpinBox()
        self._viscosity.setRange(0.0, 10.0)
        self._viscosity.setDecimals(6)
        self._viscosity.setSingleStep(0.0005)
        self._viscosity.setValue(0.001)  # Pa·s

        self._temperature_c = QDoubleSpinBox()
        self._temperature_c.setRange(-10.0, 100.0)
        self._temperature_c.setDecimals(2)
        self._temperature_c.setSingleStep(0.5)
        self._temperature_c.setValue(25.0)

        self._bead_diameter_um = QDoubleSpinBox()
        self._bead_diameter_um.setRange(0.1, 100.0)
        self._bead_diameter_um.setDecimals(3)
        self._bead_diameter_um.setSingleStep(0.1)
        self._bead_diameter_um.setValue(1.0)  # DEFAULT as requested (most common)

        params_box = QWidget()
        params_box_layout = QFormLayout(params_box)

        params_box_layout.addRow("Normalize strength", self._normalize_strength)
        params_box_layout.addRow("", self._adaptive_roi)
        params_box_layout.addRow("Blur sigma", self._blur_sigma)
        params_box_layout.addRow("Radial grad threshold", self._radial_grad_threshold)
        params_box_layout.addRow("", self._auto_polarity)
        params_box_layout.addRow("", self._invert)

        params_box_layout.addRow("", self._use_annulus)
        params_box_layout.addRow("", self._annulus_auto)
        params_box_layout.addRow("Annulus r_inner (px)", self._annulus_r_inner)
        params_box_layout.addRow("Annulus r_outer (px)", self._annulus_r_outer)
        params_box_layout.addRow("Annulus smooth (bins)", self._annulus_profile_smooth)

        params_box_layout.addRow("Gate samples", self._gate_sample_count)
        params_box_layout.addRow("Gate pass min ratio", self._gate_pass_min_ratio)
        params_box_layout.addRow("Gate q_min", self._gate_q_min)
        params_box_layout.addRow("Gate jump_max (px)", self._gate_jump_max)

        params_box_layout.addRow("Start frame", self._start_frame)
        params_box_layout.addRow("End frame", self._end_frame)

        params_box_layout.addRow("", self._use_dataset_scale)
        params_box_layout.addRow("Scale (µm/px)", self._um_per_px)
        params_box_layout.addRow("", self._scale_status)
        params_box_layout.addRow("", self.btn_save_scale)

        post_box = QWidget()
        post_box_layout = QFormLayout(post_box)
        post_box_layout.addRow("", self._pp_enabled)
        post_box_layout.addRow("", self._qc_enabled)
        post_box_layout.addRow("QC q_min", self._qc_q_min)
        post_box_layout.addRow("QC jump_max (px)", self._qc_jump_max)
        post_box_layout.addRow("Drift mode", self._drift_mode)
        post_box_layout.addRow("Drift window (old, s)", self._drift_window_s)
        post_box_layout.addRow("Calibration Strategy", self._strategy_selector)
        post_box_layout.addRow("Stage speed (µm/s)", self._stage_speed)
        post_box_layout.addRow("Drag axis", self._drag_axis)
        post_box_layout.addRow("Viscosity η (Pa·s)", self._viscosity)
        post_box_layout.addRow("Temperature (°C)", self._temperature_c)
        post_box_layout.addRow("Bead diameter (µm)", self._bead_diameter_um)

        def _collapsible(title_text: str, inner: QWidget, expanded: bool) -> QWidget:
            wrap = QWidget()
            v = QVBoxLayout(wrap)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)

            btn = QToolButton()
            btn.setCheckable(True)
            btn.setChecked(bool(expanded))

            def _sync_text(checked: bool) -> None:
                btn.setText(("▾ " if checked else "▸ ") + title_text)

            _sync_text(bool(expanded))
            inner.setVisible(bool(expanded))

            def _on_toggle(checked: bool) -> None:
                inner.setVisible(bool(checked))
                _sync_text(bool(checked))

            btn.toggled.connect(_on_toggle)

            v.addWidget(btn)
            v.addWidget(inner)
            return wrap

        self._tracking_method = "RADIAL_SYMMETRY"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 8)  # top margin 0 => starts at preview edge
        layout.setSpacing(6)
        layout.addWidget(_collapsible("Parameters", params_box, expanded=False))
        layout.addWidget(_collapsible("Postprocess", post_box, expanded=False))
        layout.addStretch(1)
        layout.addWidget(self.btn_preview_gate)
        layout.addWidget(self.btn_gate_report)
        layout.addWidget(self.btn_run)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self._progress_label)
        layout.addWidget(self.progress)

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
        # method UI zatím nemáme → držíme RS jako default
        use_ann = bool(self._use_annulus.isChecked())
        r_in = float(self._annulus_r_inner.value())
        r_out = float(self._annulus_r_outer.value())
        return {
            "method": str(self._tracking_method),
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
        }

    def get_postprocess_params(self) -> dict:
        return {
            "enabled": bool(self._pp_enabled.isChecked()),
            "qc_enabled": bool(self._qc_enabled.isChecked()),
            "q_min": float(self._qc_q_min.value()),
            "jump_max_px": float(self._qc_jump_max.value()),
            "drift_mode": str(self._drift_mode.currentData()),
            "drift_window_s": float(self._drift_window_s.value()),
            "export_um_columns": True,
            "strategy": str(self._strategy_selector.currentData()),
            "stage_speed_um_s": float(self._stage_speed.value()),
            "drag_axis": str(self._drag_axis.currentData()),
            "viscosity_pa_s": float(self._viscosity.value()),
            "temperature_c": float(self._temperature_c.value()),
            "bead_diameter_um": float(self._bead_diameter_um.value()),
        }

    def get_strategy_params(self) -> dict:
        return {
            "strategy": str(self._strategy_selector.currentData()),
            "temperature_c": float(self._temperature_c.value()),
            "bead_diameter_um": float(self._bead_diameter_um.value()),
            "viscosity_pa_s": float(self._viscosity.value()),
            "stage_speed_um_s": float(self._stage_speed.value()),
            "drag_axis": str(self._drag_axis.currentData()),
        }

    def get_scale_params(self) -> dict:
        return {
            "use_dataset_scale": bool(self._use_dataset_scale.isChecked()),
            "um_per_px": float(self._um_per_px.value()),
        }

    def get_frame_range(self) -> tuple[int, int]:
        return int(self._start_frame.value()), int(self._end_frame.value())

    def set_batch_running(self, running: bool) -> None:
        for b in [
            self.btn_save_scale,
        ]:
            b.setEnabled(not running)

    def set_scale_status(self, text: str) -> None:
        self._scale_status.setText(text)

    def set_um_per_px(self, value: float) -> None:
        try:
            self._um_per_px.setValue(float(value))
        except Exception:
            pass

    def set_end_frame(self, end_frame: int) -> None:
        self._end_frame.setValue(int(end_frame))

    def set_tracking_method(self, method: str) -> None:
        self._tracking_method = str(method)
