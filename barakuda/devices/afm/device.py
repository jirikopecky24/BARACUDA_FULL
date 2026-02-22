from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, QObject, QEvent, QLocale
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFormLayout, QHBoxLayout,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton, QComboBox,
    QScrollArea, QFrame, QSizePolicy, QAbstractSpinBox
)
from barakuda.devices.base import DeviceSpec
from barakuda.devices.afm.core.afm_v2_pipeline import _HAS_CELLPOSE


class NoWheelValueChangeFilter(QObject):
    """Event filter that blocks mouse wheel from changing values in scrollable panels."""
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return False


class AfmPanel(QWidget):
    run_batch_clicked = pyqtSignal()

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

        # ── Data (read-only) ──────────────────────────────────────
        form_data = QFormLayout()
        lbl_data = QLabel("— Data —")
        lbl_data.setStyleSheet("font-weight: 600; margin-top: 4px;")
        form_data.addRow(lbl_data)

        self.lbl_channel = QLabel("–")
        self.lbl_channel.setStyleSheet("color: #555;")
        form_data.addRow("Channel:", self.lbl_channel)

        self.lbl_scale = QLabel("unknown")
        self.lbl_scale.setStyleSheet("color: #b71c1c; font-weight: 600;")
        form_data.addRow("Scale:", self.lbl_scale)

        scroll_layout.addLayout(form_data)

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

        self.btn_preview = QPushButton("Preview AFM")
        actions.addWidget(self.btn_preview)

        self.btn_reset = QPushButton("Reset AFM defaults")
        self.btn_reset.clicked.connect(self.apply_afm_defaults)
        actions.addWidget(self.btn_reset)

        self.btn_run = QPushButton("Spustit AFM Batch")
        self.btn_run.clicked.connect(self.run_batch_clicked.emit)
        actions.addWidget(self.btn_run)

        layout.addLayout(actions)

        # Apply defaults + tooltips on init
        self.apply_afm_defaults()
        self.apply_afm_tooltips()

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

        um_per_px = meta.get("afm_um_per_px", 0.0)
        um_source = meta.get("afm_um_per_px_source", "unknown")

        if um_per_px and float(um_per_px) > 0:
            self.lbl_scale.setText(f"{float(um_per_px):.4f} µm/px ({um_source})")
            self.lbl_scale.setStyleSheet("color: #2e7d32; font-weight: 600;")
        else:
            self.lbl_scale.setText("unknown")
            self.lbl_scale.setStyleSheet("color: #b71c1c; font-weight: 600;")

    # ── Defaults (high recall) ────────────────────────────────────
    def apply_afm_defaults(self):
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

    # ── Parameter collection ──────────────────────────────────────
    def get_afm_params(self) -> dict:
        return {
            "invert": bool(self.cb_invert.isChecked()),
            "clip_p_low": float(self.sp_clip_low.value()),
            "clip_p_high": float(self.sp_clip_high.value()),
            "cp_model": str(self.cb_cp_model.currentText()),
            "cp_diameter": float(self.sp_cp_diam.value()),
            "cp_flow_threshold": float(self.sp_cp_flow.value()),
            "cp_cellprob_threshold": float(self.sp_cp_prob.value()),
            "rods_only": bool(self.cb_rods_only.isChecked()),
            "rods_min_major_axis_px": float(self.sp_rods_min_major.value()),
            "rods_min_aspect_ratio": float(self.sp_rods_min_ar.value()),
            "rods_min_eccentricity": float(self.sp_rods_min_ecc.value()),
            "rods_min_area_px": int(self.sp_min_area.value()),
            "ellipse_thickness_px": int(self.sp_ellipse_thick.value()),
        }


def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="afm",
        display_name="AFM",
        create_panel=lambda: AfmPanel(),
    )
