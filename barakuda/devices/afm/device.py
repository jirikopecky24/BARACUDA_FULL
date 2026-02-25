from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, QObject, QEvent, QLocale, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFormLayout, QHBoxLayout,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton, QComboBox,
    QScrollArea, QFrame, QSizePolicy, QAbstractSpinBox
)
from barakuda.devices.base import DeviceSpec
from barakuda.devices.afm.core.afm_v2_pipeline import _HAS_CELLPOSE
from barakuda.devices.afm.core.compute import resolve_device


class NoWheelValueChangeFilter(QObject):
    """Event filter that blocks mouse wheel from changing values in scrollable panels."""
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return False


class AfmPanel(QWidget):
    run_batch_clicked = pyqtSignal()
    auto_preview_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Use Czech locale for all spinboxes to ensure ',' is used for decimals
        self._loc = QLocale(QLocale.Language.Czech, QLocale.Country.CzechRepublic)

        # ══════════════════════════════════════════════════════════
        # FIXED TOP: title + warning
        # ══════════════════════════════════════════════════════════
        top_bar = QVBoxLayout()
        top_bar.setContentsMargins(8, 6, 8, 2)

        title = QLabel("AFM — Cellpose V2 Rod-Fit Pipeline")
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        top_bar.addWidget(title)

        if not _HAS_CELLPOSE:
            warn = QLabel(
                "⚠ Cellpose is NOT installed. Segmentation will fail.\n"
                "Install via: pip install cellpose"
            )
            warn.setStyleSheet("color: #d32f2f; font-weight: 600; padding: 6px;")
            warn.setWordWrap(True)
            top_bar.addWidget(warn)

        layout.addLayout(top_bar)

        # ══════════════════════════════════════════════════════════
        # SCROLLABLE: all parameter sections
        # ══════════════════════════════════════════════════════════
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(8, 4, 8, 4)

        # ── Data ──────────────────────────────────────────────────
        form_data = QFormLayout()
        lbl_data = QLabel("— Data —")
        lbl_data.setStyleSheet("font-weight: 600; margin-top: 4px;")
        form_data.addRow(lbl_data)

        self.lbl_channel = QLabel("Channel: unknown")
        self.lbl_channel.setStyleSheet("color: #555;")

        self.lbl_scale = QLabel("Scale: unknown")
        self.lbl_scale.setStyleSheet("color: #b71c1c; font-weight: 600;")

        self.lbl_status = QLabel("Status: idle")
        self.lbl_status.setStyleSheet("color: #0277bd; font-weight: 600; font-size: 11px;")
        
        from PyQt6.QtWidgets import QProgressBar
        self.pb_preview = QProgressBar()
        self.pb_preview.setRange(0, 100)
        self.pb_preview.setValue(0)
        self.pb_preview.setVisible(False)

        form_data.addRow(self.lbl_channel)
        form_data.addRow(self.lbl_scale)
        form_data.addRow(self.lbl_status)
        form_data.addRow(self.pb_preview)

        scroll_layout.addLayout(form_data)

        # ── Compute ───────────────────────────────────────────────
        form_comp = QFormLayout()
        lbl_comp = QLabel("— Compute —")
        lbl_comp.setStyleSheet("font-weight: 600; margin-top: 4px;")
        form_comp.addRow(lbl_comp)

        self.cb_profile = QComboBox()
        self.cb_profile.addItems(["Auto", "GPU (force)", "CPU (force)"])
        self.cb_profile.setCurrentText("Auto")
        self.cb_profile.currentTextChanged.connect(self._on_profile_changed)
        form_comp.addRow("Compute Profile", self.cb_profile)

        self.lbl_dev_info = QLabel("Device: ?\nTorch: ?\nCellpose: ?")
        self.lbl_dev_info.setStyleSheet("color: #666; font-size: 11px;")
        self.lbl_dev_info.setWordWrap(True)
        form_comp.addRow(self.lbl_dev_info)

        self.chk_fast_preview = QCheckBox("Fast Preview (CPU recommended)")
        self.chk_fast_preview.setChecked(True)
        self.chk_fast_preview.stateChanged.connect(self._on_fast_preview_changed)
        form_comp.addRow(self.chk_fast_preview)

        self.cb_downscale = QComboBox()
        self.cb_downscale.addItems(["1.0", "0.75", "0.5", "0.33"])
        self.cb_downscale.setCurrentText("0.5")
        form_comp.addRow("Preview downscale", self.cb_downscale)

        scroll_layout.addLayout(form_comp)

        # ── Preprocessing ─────────────────────────────────────────
        form_pre = QFormLayout()
        lbl_pre = QLabel("— Preprocessing —")
        lbl_pre.setStyleSheet("font-weight: 600; margin-top: 4px;")
        form_pre.addRow(lbl_pre)

        self.cb_invert = QCheckBox("Invert (bacteria are dark)")
        self.cb_invert.setChecked(False)
        form_pre.addRow(self.cb_invert)

        self.sp_clip_low = QDoubleSpinBox()
        self.sp_clip_low.setLocale(self._loc)
        self.sp_clip_low.setRange(0.0, 50.0)
        self.sp_clip_low.setDecimals(1)
        self.sp_clip_low.setSingleStep(0.5)
        self.sp_clip_low.setValue(1.0)
        form_pre.addRow("Clip percentile low", self.sp_clip_low)

        self.sp_clip_high = QDoubleSpinBox()
        self.sp_clip_high.setLocale(self._loc)
        self.sp_clip_high.setRange(50.0, 100.0)
        self.sp_clip_high.setDecimals(1)
        self.sp_clip_high.setSingleStep(0.5)
        self.sp_clip_high.setValue(99.0)
        form_pre.addRow("Clip percentile high", self.sp_clip_high)

        scroll_layout.addLayout(form_pre)

        # ── Cellpose Segmentation ─────────────────────────────────
        form_cp = QFormLayout()
        lbl_cp = QLabel("— Cellpose Segmentation —")
        lbl_cp.setStyleSheet("font-weight: 600; margin-top: 4px;")
        form_cp.addRow(lbl_cp)

        self.cb_cp_model = QComboBox()
        self.cb_cp_model.addItems(["cyto3", "cyto2", "cyto", "nuclei"])
        self.cb_cp_model.setCurrentText("cyto3")
        form_cp.addRow("Model", self.cb_cp_model)

        self.sp_cp_diam = QDoubleSpinBox()
        self.sp_cp_diam.setLocale(self._loc)
        self.sp_cp_diam.setRange(0.0, 200.0)
        self.sp_cp_diam.setDecimals(1)
        self.sp_cp_diam.setSingleStep(1.0)
        self.sp_cp_diam.setValue(0.0)
        self.sp_cp_diam.setSpecialValueText("Auto")
        form_cp.addRow("Diameter (px)", self.sp_cp_diam)

        self.sp_cp_flow = QDoubleSpinBox()
        self.sp_cp_flow.setLocale(self._loc)
        self.sp_cp_flow.setRange(0.0, 1.0)
        self.sp_cp_flow.setSingleStep(0.05)
        self.sp_cp_flow.setDecimals(2)
        self.sp_cp_flow.setValue(0.4)
        form_cp.addRow("Flow threshold", self.sp_cp_flow)

        self.sp_cp_prob = QDoubleSpinBox()
        self.sp_cp_prob.setLocale(self._loc)
        self.sp_cp_prob.setRange(-6.0, 6.0)
        self.sp_cp_prob.setSingleStep(0.10)
        self.sp_cp_prob.setDecimals(2)
        self.sp_cp_prob.setValue(-0.5)
        form_cp.addRow("Cellprob threshold", self.sp_cp_prob)

        scroll_layout.addLayout(form_cp)

        # ── Rod Geometry Filter ───────────────────────────────────
        form_rod = QFormLayout()
        lbl_rod = QLabel("— Rod Geometry Filter —")
        lbl_rod.setStyleSheet("font-weight: 600; margin-top: 4px;")
        form_rod.addRow(lbl_rod)

        self.cb_rods_only = QCheckBox("Rods only")
        self.cb_rods_only.setChecked(True)
        form_rod.addRow(self.cb_rods_only)

        self.sp_rods_min_major = QDoubleSpinBox()
        self.sp_rods_min_major.setLocale(self._loc)
        self.sp_rods_min_major.setRange(1.0, 500.0)
        self.sp_rods_min_major.setDecimals(0)
        self.sp_rods_min_major.setSingleStep(1.0)
        self.sp_rods_min_major.setValue(12.0)
        form_rod.addRow("Min major axis (px)", self.sp_rods_min_major)

        self.sp_rods_min_ar = QDoubleSpinBox()
        self.sp_rods_min_ar.setLocale(self._loc)
        self.sp_rods_min_ar.setRange(1.0, 20.0)
        self.sp_rods_min_ar.setDecimals(2)
        self.sp_rods_min_ar.setSingleStep(0.10)
        self.sp_rods_min_ar.setValue(1.8)
        form_rod.addRow("Min aspect ratio", self.sp_rods_min_ar)

        self.sp_rods_min_ecc = QDoubleSpinBox()
        self.sp_rods_min_ecc.setLocale(self._loc)
        self.sp_rods_min_ecc.setRange(0.0, 0.99)
        self.sp_rods_min_ecc.setDecimals(2)
        self.sp_rods_min_ecc.setSingleStep(0.05)
        self.sp_rods_min_ecc.setValue(0.65)
        form_rod.addRow("Min eccentricity", self.sp_rods_min_ecc)

        self.sp_min_area = QSpinBox()
        self.sp_min_area.setLocale(self._loc)
        self.sp_min_area.setRange(1, 100_000)
        self.sp_min_area.setSingleStep(1)
        self.sp_min_area.setValue(8)
        form_rod.addRow("Min area (px)", self.sp_min_area)

        preset_row = QHBoxLayout()
        self.btn_preset_recall = QPushButton("High Recall")
        self.btn_preset_recall.setToolTip("min_major=10, min_ar=1.6, min_ecc=0.60, min_area=6")
        self.btn_preset_recall.clicked.connect(self._apply_preset_high_recall)
        preset_row.addWidget(self.btn_preset_recall)

        self.btn_preset_nature = QPushButton("Nature Overlay")
        self.btn_preset_nature.setToolTip("min_major=12, min_ar=1.8, min_ecc=0.65, min_area=8")
        self.btn_preset_nature.clicked.connect(self._apply_preset_nature)
        preset_row.addWidget(self.btn_preset_nature)
        form_rod.addRow(preset_row)

        scroll_layout.addLayout(form_rod)

        # ── Overlay ───────────────────────────────────────────────
        form_ov = QFormLayout()
        lbl_ov = QLabel("— Overlay —")
        lbl_ov.setStyleSheet("font-weight: 600; margin-top: 4px;")
        form_ov.addRow(lbl_ov)

        self.sp_ellipse_thick = QSpinBox()
        self.sp_ellipse_thick.setLocale(self._loc)
        self.sp_ellipse_thick.setRange(1, 10)
        self.sp_ellipse_thick.setSingleStep(1)
        self.sp_ellipse_thick.setValue(2)
        form_ov.addRow("Ellipse thickness (px)", self.sp_ellipse_thick)

        self.sp_ellipse_alpha = QDoubleSpinBox()
        self.sp_ellipse_alpha.setLocale(self._loc)
        self.sp_ellipse_alpha.setRange(0.20, 1.00)
        self.sp_ellipse_alpha.setDecimals(2)
        self.sp_ellipse_alpha.setSingleStep(0.05)
        self.sp_ellipse_alpha.setValue(0.60)
        form_ov.addRow("Ellipse alpha", self.sp_ellipse_alpha)

        ov_info = QLabel("Overlay renders ellipse fit from rod_table (no boundaries).")
        ov_info.setStyleSheet("color: #888; font-size: 11px; font-style: italic;")
        ov_info.setWordWrap(True)
        form_ov.addRow(ov_info)

        scroll_layout.addLayout(form_ov)
        scroll_layout.addStretch(1)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)   # scroll eats all vertical space

        # ══════════════════════════════════════════════════════════
        # FIXED BOTTOM: action buttons (never scroll away)
        # ══════════════════════════════════════════════════════════
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ccc;")
        layout.addWidget(sep)

        actions = QVBoxLayout()
        actions.setContentsMargins(8, 4, 8, 6)

        roi_hint = QLabel("ROI z Preview se použije jako výpočetní oblast.")
        roi_hint.setStyleSheet("color: #888; font-size: 11px;")
        roi_hint.setWordWrap(True)
        actions.addWidget(roi_hint)

        self.chk_auto_preview = QCheckBox("Auto Preview")
        self.chk_auto_preview.setChecked(True)
        self.chk_auto_preview.setToolTip(
            "Automatically run preview after any AFM parameter change.\n"
            "Uses 500 ms debounce to avoid redundant runs."
        )
        actions.addWidget(self.chk_auto_preview)

        self.btn_preview = QPushButton("Preview AFM")
        actions.addWidget(self.btn_preview)

        self.btn_cancel = QPushButton("Cancel Preview")
        self.btn_cancel.setEnabled(False)
        actions.addWidget(self.btn_cancel)

        self.btn_reset = QPushButton("Reset AFM defaults")
        self.btn_reset.clicked.connect(self.apply_afm_defaults)
        actions.addWidget(self.btn_reset)

        self.btn_run = QPushButton("Spustit AFM Batch")
        self.btn_run.clicked.connect(self.run_batch_clicked.emit)
        actions.addWidget(self.btn_run)

        layout.addLayout(actions)

        self._applying_defaults = True
        self._auto_preview_armed = False  # armed after 1st manual Preview
        self.apply_afm_defaults()
        self.apply_afm_tooltips()
        self._on_profile_changed() # Trigger initial hardware check
        self._applying_defaults = False

        # ── Debounce timer for auto-preview ───────────────────────
        self._auto_preview_timer = QTimer(self)
        self._auto_preview_timer.setSingleShot(True)
        self._auto_preview_timer.setInterval(500)
        self._auto_preview_timer.timeout.connect(self._fire_auto_preview)

        # Connect all AFM parameter widgets to debounce trigger
        for sb in (self.sp_clip_low, self.sp_clip_high,
                   self.sp_cp_diam, self.sp_cp_flow, self.sp_cp_prob,
                   self.sp_rods_min_major, self.sp_rods_min_ar,
                   self.sp_rods_min_ecc,
                   self.sp_ellipse_alpha):
            sb.valueChanged.connect(self._schedule_auto_preview)
        for sb_int in (self.sp_min_area, self.sp_ellipse_thick):
            sb_int.valueChanged.connect(self._schedule_auto_preview)
        for cb in (self.cb_invert, self.cb_rods_only):
            cb.stateChanged.connect(self._schedule_auto_preview)
        self.cb_cp_model.currentIndexChanged.connect(self._schedule_auto_preview)

        # ── Wheel Blocker ─────────────────────────────────────────
        self._wheel_blocker = NoWheelValueChangeFilter(self)
        for w in self.findChildren(QAbstractSpinBox):
            w.installEventFilter(self._wheel_blocker)
        for w in self.findChildren(QComboBox):
            w.installEventFilter(self._wheel_blocker)

    # ── Update Data section from loader metadata ──────────────────
    def update_loader_info(self, meta: dict | None) -> None:
        """Update the read-only Data section from loader metadata.

        Called by preview/batch after loading an .spm file.
        """
        if meta is None:
            self.lbl_channel.setText("–")
            self.lbl_scale.setText("unknown")
            self.lbl_scale.setStyleSheet("color: #b71c1c; font-weight: 600;")
            return

        ch = meta.get("selected_channel", "–")
        self.lbl_channel.setText(str(ch))

        um_per_px = float(meta.get("afm_um_per_px", 0.0))
        um_source = meta.get("afm_um_per_px_source", "unknown")
        px_to_nm = float(meta.get("pixel_to_nm", 0.0))
        px_source = meta.get("pixel_to_nm_source", "unknown")

        if um_per_px > 0 and px_to_nm > 0:
            self.lbl_scale.setText(f"{um_per_px:.6f} µm/px ({px_to_nm:.4f} nm/px, src={um_source})")
            self.lbl_scale.setStyleSheet("color: #2e7d32; font-weight: 600;")
        elif um_per_px > 0:
            self.lbl_scale.setText(f"{um_per_px:.6f} µm/px (src={um_source})")
            self.lbl_scale.setStyleSheet("color: #2e7d32; font-weight: 600;")
        elif px_to_nm > 0:
            self.lbl_scale.setText(f"{px_to_nm:.4f} nm/px (src={px_source})")
            self.lbl_scale.setStyleSheet("color: #2e7d32; font-weight: 600;")
        else:
            self.lbl_scale.setText("unknown")
            self.lbl_scale.setStyleSheet("color: #b71c1c; font-weight: 600;")

    # ── UI State Helpers ──────────────────────────────────────────
    def set_preview_progress(self, pct: int, text: str | None = None) -> None:
        pct = max(0, min(100, pct))
        self.pb_preview.setVisible(True)
        self.pb_preview.setValue(pct)
        if text:
            self.lbl_status.setText(f"Status: {text}")

    def reset_preview_progress(self) -> None:
        self.pb_preview.setValue(0)
        self.pb_preview.setVisible(False)
        self.lbl_status.setText("Status: idle")

    def set_preview_state(self, is_running: bool) -> None:
        """Called by MainWindow to toggle running state UI (disables Preview button)."""
        self.btn_preview.setEnabled(not is_running)
        self.btn_cancel.setEnabled(is_running)
        if is_running:
            self.btn_preview.setText("Preview AFM (running...)")
            self.btn_run.setEnabled(False)
            self.lbl_status.setText("Preview running... (Cellpose)")
            self.lbl_status.setStyleSheet("color: #e65100; font-weight: 600; font-size: 11px;")
        else:
            self.btn_preview.setEnabled(True)
            self.btn_preview.setText("Preview AFM")
            self.btn_cancel.setEnabled(False)
            self.btn_run.setEnabled(True)

    def set_status_message(self, text: str, is_error: bool = False):
        self.lbl_status.setText(text)
        if is_error:
            self.lbl_status.setStyleSheet("color: #d32f2f; font-weight: 600; font-size: 11px;")
        else:
            self.lbl_status.setStyleSheet("color: #2e7d32; font-weight: 600; font-size: 11px;")

    def _on_fast_preview_changed(self, state: int):
        self.cb_downscale.setEnabled(self.chk_fast_preview.isChecked())

    def _on_profile_changed(self, text: str = ""):
        txt = self.cb_profile.currentText()
        if "GPU" in txt:
            prof = "gpu"
        elif "CPU" in txt:
            prof = "cpu"
        else:
            prof = "auto"

        try:
            info = resolve_device(prof)
            dev = info.get("device", "unknown")
            t_ver = info.get("torch_version", "?")
            c_ver = info.get("cellpose_version", "?")
            gpu_n = info.get("gpu_name", "")
            
            if dev == "cuda" and gpu_n and gpu_n != "unknown":
                dev_str = f"cuda ({gpu_n})"
            else:
                dev_str = dev
                
            self.lbl_dev_info.setText(f"Device: {dev_str}\nTorch: {t_ver}\nCellpose: {c_ver}")
            
            # auto-apply sensible view defaults if the user switches compute engines
            if prof == "cpu" or dev == "cpu":
                self.chk_fast_preview.setChecked(True)
                self.cb_downscale.setCurrentText("0.5")
            else:
                self.chk_fast_preview.setChecked(False)
                self.cb_downscale.setCurrentText("1.0")

        except Exception as e:
            self.lbl_dev_info.setText(f"Device: Error\n{e}")
            self.lbl_dev_info.setStyleSheet("color: #d32f2f; font-size: 11px;")

    # ── Defaults (high recall) ────────────────────────────────────
    def apply_afm_defaults(self):
        # Compute default
        self.cb_profile.setCurrentText("Auto")
        # Preprocessing
        self.cb_invert.setChecked(False)
        self.sp_clip_low.setValue(1.0)
        self.sp_clip_high.setValue(99.0)

        # Cellpose
        self.cb_cp_model.setCurrentText("cyto3")
        self.sp_cp_diam.setValue(0.0)       # auto
        self.sp_cp_flow.setValue(0.4)
        self.sp_cp_prob.setValue(-0.5)

        # Rod filter (high recall)
        self.cb_rods_only.setChecked(True)
        self.sp_rods_min_major.setValue(12.0)
        self.sp_rods_min_ar.setValue(1.8)
        self.sp_rods_min_ecc.setValue(0.65)
        self.sp_min_area.setValue(8)

        # Overlay
        self.sp_ellipse_thick.setValue(2)
        self.sp_ellipse_alpha.setValue(0.60)

    # ── Tooltips ──────────────────────────────────────────────────
    def apply_afm_tooltips(self):
        self.cb_invert.setToolTip(
            "Invert intensity.\n"
            "Use if bacteria appear DARK relative to background."
        )
        self.sp_clip_low.setToolTip(
            "Clip percentile low.\n"
            "Pixels below this percentile are clipped.\nDefault 1.0."
        )
        self.sp_clip_high.setToolTip(
            "Clip percentile high.\n"
            "Pixels above this percentile are clipped.\nDefault 99.0."
        )
        self.cb_cp_model.setToolTip(
            "Cellpose model.\n"
            "cyto3 = general cells/bacteria (recommended).\n"
            "cyto2 / cyto = older models.\n"
            "nuclei = for nuclei detection."
        )
        self.sp_cp_diam.setToolTip(
            "Cellpose Diameter [px].\n"
            "0 = Auto (slower but adaptive).\n"
            "Set manually if you know the cell size."
        )
        self.sp_cp_flow.setToolTip(
            "Flow threshold.\n"
            "Controls mask boundary strictness.\n"
            "Lower = stricter, Higher = more generous.\nDefault 0.4."
        )
        self.sp_cp_prob.setToolTip(
            "Cellprob threshold.\n"
            "Lower = more sensitive (larger masks).\n"
            "Default -0.5 (high recall)."
        )
        self.cb_rods_only.setToolTip(
            "Rods only.\n"
            "Filters output to keep only elongated rod-like shapes.\n"
            "Required for ellipse overlay and rod export."
        )
        self.sp_rods_min_major.setToolTip("Min major axis [px].\nRemoves short objects.")
        self.sp_rods_min_ar.setToolTip("Min aspect ratio (Major/Minor).\nRods typically > 1.8.")
        self.sp_rods_min_ecc.setToolTip("Min eccentricity [0–1].\nRods ecc ~ 0.85+.")
        self.sp_min_area.setToolTip("Min area [px²].\nRemoves tiny noise.")
        self.sp_ellipse_thick.setToolTip(
            "Ellipse thickness [px].\n1 = thin, 2 = recommended, 3 = thick."
        )
        self.sp_ellipse_alpha.setToolTip(
            "Ellipse alpha [0.2–1.0].\n"
            "0.6 = semi-transparent (Nature-grade).\n"
            "1.0 = fully opaque (legacy)."
        )

    # ── Parameter collection ──────────────────────────────────────
    def get_afm_params(self) -> dict:
        diam_val = float(self.sp_cp_diam.value())
        if diam_val == 0.0:
            cp_diam_mode = "auto"
            cp_diam_px = None
        else:
            cp_diam_mode = "fixed"
            cp_diam_px = int(diam_val)
            
        prof_txt = self.cb_profile.currentText()
        if "GPU" in prof_txt:
            prof = "gpu"
        elif "CPU" in prof_txt:
            prof = "cpu"
        else:
            prof = "auto"

        return {
            "compute_profile": prof,
            "preview_fast_mode": bool(self.chk_fast_preview.isChecked()),
            "preview_downscale": float(self.cb_downscale.currentText()),
            "invert": bool(self.cb_invert.isChecked()),
            "clip_p_low": float(self.sp_clip_low.value()),
            "clip_p_high": float(self.sp_clip_high.value()),
            "cp_model": str(self.cb_cp_model.currentText()),
            "cp_diameter_mode": cp_diam_mode,
            "cp_diameter_px": cp_diam_px,
            "cp_flow_threshold": float(self.sp_cp_flow.value()),
            "cp_cellprob_threshold": float(self.sp_cp_prob.value()),
            "rods_only": bool(self.cb_rods_only.isChecked()),
            "rods_min_major_axis_px": float(self.sp_rods_min_major.value()),
            "rods_min_aspect_ratio": float(self.sp_rods_min_ar.value()),
            "rods_min_eccentricity": float(self.sp_rods_min_ecc.value()),
            "rods_min_area_px": int(self.sp_min_area.value()),
            "ellipse_thickness_px": int(self.sp_ellipse_thick.value()),
            "ellipse_alpha": float(self.sp_ellipse_alpha.value()),
        }

    # ── Preset helpers ─────────────────────────────────────────────
    def _apply_preset_high_recall(self):
        self._applying_defaults = True
        self.sp_rods_min_major.setValue(10.0)
        self.sp_rods_min_ar.setValue(1.60)
        self.sp_rods_min_ecc.setValue(0.60)
        self.sp_min_area.setValue(6)
        self._applying_defaults = False
        self._schedule_auto_preview()

    def _apply_preset_nature(self):
        self._applying_defaults = True
        self.sp_rods_min_major.setValue(12.0)
        self.sp_rods_min_ar.setValue(1.80)
        self.sp_rods_min_ecc.setValue(0.65)
        self.sp_min_area.setValue(8)
        self._applying_defaults = False
        self._schedule_auto_preview()

    # ── Auto-preview debounce ─────────────────────────────────────
    def _schedule_auto_preview(self, *_args) -> None:
        """Restart debounce timer; will fire auto_preview_requested after 500 ms idle."""
        if getattr(self, "_applying_defaults", False):
            return
        if not self.chk_auto_preview.isChecked():
            return
        if not getattr(self, "_auto_preview_armed", False):
            return
        self._auto_preview_timer.stop()
        self._auto_preview_timer.start()

    def _fire_auto_preview(self) -> None:
        """Called when debounce timer expires — emit the signal."""
        if self.chk_auto_preview.isChecked() and self._auto_preview_armed:
            self.auto_preview_requested.emit()

    def arm_auto_preview(self) -> None:
        """Call after first manual Preview to enable auto-preview."""
        self._auto_preview_armed = True

    def disarm_auto_preview(self) -> None:
        """Call on dataset change to reset auto-preview armed state."""
        self._auto_preview_armed = False
        self._auto_preview_timer.stop()


def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="afm",
        display_name="AFM",
        create_panel=lambda: AfmPanel(),
    )
