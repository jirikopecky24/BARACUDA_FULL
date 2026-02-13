from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QProgressBar,
    QGroupBox, QFormLayout, QDoubleSpinBox, QCheckBox, QSpinBox,
    QToolButton, QHBoxLayout
)


class PipelinePanel(QWidget):
    run_selected_clicked = pyqtSignal()
    run_batch_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    manage_runs_clicked = pyqtSignal()

    measure_clicked = pyqtSignal()
    track_range_clicked = pyqtSignal()

    save_dataset_scale_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        title = QLabel("Pipeline")
        title.setStyleSheet("font-weight: 600;")

        self.btn_run_selected = QPushButton("Run Selected")
        self.btn_run_batch = QPushButton("Run Batch (Selected)")
        self.btn_stop = QPushButton("STOP")
        self.btn_manage_runs = QPushButton("Manage Runs…")

        self.btn_measure = QPushButton("Measure (current frame)")
        self.btn_track_range = QPushButton("Track Video (range)")

        self.btn_run_selected.clicked.connect(self.run_selected_clicked.emit)
        self.btn_run_batch.clicked.connect(self.run_batch_clicked.emit)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_manage_runs.clicked.connect(self.manage_runs_clicked.emit)
        self.btn_measure.clicked.connect(self.measure_clicked.emit)
        self.btn_track_range.clicked.connect(self.track_range_clicked.emit)

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

        self._drift_enabled = QCheckBox("Drift correction")
        self._drift_enabled.setChecked(True)

        self._drift_window_s = QDoubleSpinBox()
        self._drift_window_s.setRange(0.0, 1e6)
        self._drift_window_s.setDecimals(3)
        self._drift_window_s.setSingleStep(0.1)
        self._drift_window_s.setValue(1.0)

        params_box = QGroupBox("Params")
        form = QFormLayout(params_box)

        form.addRow("Normalize strength", self._normalize_strength)
        form.addRow("", self._adaptive_roi)
        form.addRow("Blur sigma", self._blur_sigma)
        form.addRow("Radial grad threshold", self._radial_grad_threshold)
        form.addRow("", self._auto_polarity)
        form.addRow("", self._invert)

        form.addRow("", self._use_annulus)
        form.addRow("", self._annulus_auto)
        form.addRow("Annulus r_inner (px)", self._annulus_r_inner)
        form.addRow("Annulus r_outer (px)", self._annulus_r_outer)
        form.addRow("Annulus smooth (bins)", self._annulus_profile_smooth)

        form.addRow("Start frame", self._start_frame)
        form.addRow("End frame", self._end_frame)

        form.addRow("", self._use_dataset_scale)
        form.addRow("Scale (µm/px)", self._um_per_px)
        form.addRow("", self._scale_status)
        form.addRow("", self.btn_save_scale)

        post_box = QGroupBox("Postprocess (OT-3.1)")
        post_form = QFormLayout(post_box)
        post_form.addRow("", self._pp_enabled)
        post_form.addRow("", self._qc_enabled)
        post_form.addRow("QC q_min", self._qc_q_min)
        post_form.addRow("QC jump_max (px)", self._qc_jump_max)
        post_form.addRow("", self._drift_enabled)
        post_form.addRow("Drift window (s)", self._drift_window_s)

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
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(title)
        layout.addWidget(_collapsible("Params", params_box, expanded=True))
        layout.addWidget(_collapsible("Postprocess (OT-3.1)", post_box, expanded=False))
        layout.addWidget(self.btn_measure)
        layout.addWidget(self.btn_track_range)
        layout.addWidget(self.btn_run_selected)
        layout.addWidget(self.btn_run_batch)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.progress)
        layout.addWidget(self.btn_manage_runs)

    # -------------------- API pro Shell --------------------

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
            "drift_enabled": bool(self._drift_enabled.isChecked()),
            "drift_window_s": float(self._drift_window_s.value()),
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
            self.btn_measure, self.btn_track_range,
            self.btn_run_selected, self.btn_run_batch,
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
