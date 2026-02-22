from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFormLayout,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton,
)
from barakuda.devices.base import DeviceSpec
from barakuda.devices.afm.core.afm_v2_pipeline import _HAS_CELLPOSE


class AfmPanel(QWidget):
    run_batch_clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        title = QLabel("AFM — Cellpose V2 Segmentation")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        # Cellpose availability warning
        if not _HAS_CELLPOSE:
            warn = QLabel("⚠ Cellpose is NOT installed. Segmentation will fail.\nInstall via: pip install cellpose")
            warn.setStyleSheet("color: #d32f2f; font-weight: 600; padding: 6px;")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        self.btn_preview = QPushButton("Preview AFM")
        layout.addWidget(self.btn_preview)

        # ── Preprocessing ─────────────────────────────────────────
        form_pre = QFormLayout()
        form_pre.addRow(QLabel("— Preprocessing —"))

        self.cb_invert = QCheckBox("Invert (bacteria are dark)")
        self.cb_invert.setChecked(False)
        form_pre.addRow(self.cb_invert)

        self.sp_clip_low = QDoubleSpinBox()
        self.sp_clip_low.setRange(0.0, 49.0)
        self.sp_clip_low.setDecimals(1)
        self.sp_clip_low.setSingleStep(0.5)
        self.sp_clip_low.setValue(1.0)
        form_pre.addRow("Clip percentile low", self.sp_clip_low)

        self.sp_clip_high = QDoubleSpinBox()
        self.sp_clip_high.setRange(51.0, 100.0)
        self.sp_clip_high.setDecimals(1)
        self.sp_clip_high.setSingleStep(0.5)
        self.sp_clip_high.setValue(99.0)
        form_pre.addRow("Clip percentile high", self.sp_clip_high)

        layout.addLayout(form_pre)

        # ── Cellpose Segmentation ─────────────────────────────────
        form_cp = QFormLayout()
        form_cp.addRow(QLabel("— Cellpose Segmentation —"))

        self.sp_cp_diam = QDoubleSpinBox()
        self.sp_cp_diam.setRange(0.0, 500.0)
        self.sp_cp_diam.setValue(0.0)
        self.sp_cp_diam.setSpecialValueText("Auto")
        form_cp.addRow("Diameter (px)", self.sp_cp_diam)

        self.sp_cp_flow = QDoubleSpinBox()
        self.sp_cp_flow.setRange(0.0, 3.0)
        self.sp_cp_flow.setSingleStep(0.1)
        self.sp_cp_flow.setDecimals(2)
        self.sp_cp_flow.setValue(0.4)
        form_cp.addRow("Flow threshold", self.sp_cp_flow)

        self.sp_cp_prob = QDoubleSpinBox()
        self.sp_cp_prob.setRange(-6.0, 6.0)
        self.sp_cp_prob.setSingleStep(0.1)
        self.sp_cp_prob.setDecimals(2)
        self.sp_cp_prob.setValue(-0.5)
        form_cp.addRow("Cellprob threshold", self.sp_cp_prob)

        layout.addLayout(form_cp)

        # ── Rod Filter ────────────────────────────────────────────
        form_rod = QFormLayout()
        form_rod.addRow(QLabel("— Rod Filter —"))

        self.cb_rods_only = QCheckBox("Rods only (long bacteria)")
        self.cb_rods_only.setChecked(True)
        form_rod.addRow(self.cb_rods_only)

        self.sp_rods_min_major = QDoubleSpinBox()
        self.sp_rods_min_major.setRange(0.0, 500.0)
        self.sp_rods_min_major.setDecimals(1)
        self.sp_rods_min_major.setValue(12.0)
        form_rod.addRow("Min major axis (px)", self.sp_rods_min_major)

        self.sp_rods_min_ar = QDoubleSpinBox()
        self.sp_rods_min_ar.setRange(1.0, 10.0)
        self.sp_rods_min_ar.setDecimals(2)
        self.sp_rods_min_ar.setSingleStep(0.1)
        self.sp_rods_min_ar.setValue(1.8)
        form_rod.addRow("Min aspect ratio", self.sp_rods_min_ar)

        self.sp_rods_min_ecc = QDoubleSpinBox()
        self.sp_rods_min_ecc.setRange(0.0, 1.0)
        self.sp_rods_min_ecc.setDecimals(2)
        self.sp_rods_min_ecc.setSingleStep(0.05)
        self.sp_rods_min_ecc.setValue(0.65)
        form_rod.addRow("Min eccentricity", self.sp_rods_min_ecc)

        self.sp_min_area = QSpinBox()
        self.sp_min_area.setRange(1, 100_000)
        self.sp_min_area.setValue(8)
        form_rod.addRow("Min area (px)", self.sp_min_area)

        layout.addLayout(form_rod)

        # ── Overlay ───────────────────────────────────────────────
        form_ov = QFormLayout()
        form_ov.addRow(QLabel("— Overlay —"))

        self.sp_ellipse_thick = QSpinBox()
        self.sp_ellipse_thick.setRange(1, 3)
        self.sp_ellipse_thick.setSingleStep(1)
        self.sp_ellipse_thick.setValue(2)
        form_ov.addRow("Ellipse thickness (px)", self.sp_ellipse_thick)

        layout.addLayout(form_ov)

        # ── Export ────────────────────────────────────────────────
        self.cb_export_legacy = QCheckBox("Export legacy objects.csv")
        self.cb_export_legacy.setChecked(False)
        layout.addWidget(self.cb_export_legacy)

        # ── Actions ───────────────────────────────────────────────
        layout.addSpacing(8)
        layout.addWidget(QLabel("ROI z Preview se použije jako výpočetní oblast."))

        self.btn_reset = QPushButton("Reset AFM defaults")
        self.btn_reset.clicked.connect(self.apply_afm_defaults)
        layout.addWidget(self.btn_reset)

        self.btn_run = QPushButton("Spustit AFM Batch")
        self.btn_run.clicked.connect(self.run_batch_clicked.emit)
        layout.addWidget(self.btn_run)

        layout.addStretch(1)

        # Apply defaults + tooltips on init
        self.apply_afm_defaults()
        self.apply_afm_tooltips()

    # ── Defaults (high recall) ────────────────────────────────────
    def apply_afm_defaults(self):
        # Preprocessing
        self.cb_invert.setChecked(False)
        self.sp_clip_low.setValue(1.0)
        self.sp_clip_high.setValue(99.0)

        # Cellpose
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

        # Export
        self.cb_export_legacy.setChecked(False)

    # ── Tooltips ──────────────────────────────────────────────────
    def apply_afm_tooltips(self):
        self.cb_invert.setToolTip(
            "Invert intensity.\n"
            "Use if bacteria appear DARK relative to background."
        )
        self.sp_clip_low.setToolTip(
            "Clip percentile low.\n"
            "Pixels below this percentile are clipped (removes noise floor).\n"
            "Default 1.0."
        )
        self.sp_clip_high.setToolTip(
            "Clip percentile high.\n"
            "Pixels above this percentile are clipped (removes outlier peaks).\n"
            "Default 99.0."
        )
        self.sp_cp_diam.setToolTip(
            "Cellpose Diameter [px].\n"
            "Approximate size of bacteria.\n"
            "0 = Auto (slower but adaptive).\n"
            "Set manually if you know the size."
        )
        self.sp_cp_flow.setToolTip(
            "Flow threshold.\n"
            "Controls mask boundary strictness.\n"
            "Lower = stricter, Higher = more generous.\n"
            "Default 0.4."
        )
        self.sp_cp_prob.setToolTip(
            "Cellprob threshold.\n"
            "Lower = more sensitive (larger masks), Higher = stricter.\n"
            "Default -0.5 (high recall)."
        )
        self.cb_rods_only.setToolTip(
            "Rods only.\n"
            "Filters output to keep only elongated rod-like shapes.\n"
            "Required for ellipse overlay and rod properties export."
        )
        self.sp_rods_min_major.setToolTip(
            "Min major axis [px].\n"
            "Removes objects shorter than this."
        )
        self.sp_rods_min_ar.setToolTip(
            "Min aspect ratio (Major/Minor).\n"
            "Removes round objects (AR ~ 1). Rods typically > 1.8."
        )
        self.sp_rods_min_ecc.setToolTip(
            "Min eccentricity [0–1].\n"
            "Removes round objects. Rods ecc ~ 0.85+."
        )
        self.sp_min_area.setToolTip(
            "Min area [px²].\n"
            "Removes tiny noise detections."
        )
        self.sp_ellipse_thick.setToolTip(
            "Ellipse thickness [px].\n"
            "Yellow ellipse outline thickness in overlay.\n"
            "1 = thin, 2 = recommended, 3 = thick."
        )
        self.cb_export_legacy.setToolTip(
            "Export legacy objects.csv alongside rods_props.csv.\n"
            "Default OFF."
        )

    # ── Parameter collection ──────────────────────────────────────
    def get_afm_params(self) -> dict:
        return {
            "invert": bool(self.cb_invert.isChecked()),
            "clip_p_low": float(self.sp_clip_low.value()),
            "clip_p_high": float(self.sp_clip_high.value()),
            "cp_diameter": float(self.sp_cp_diam.value()),
            "cp_flow_threshold": float(self.sp_cp_flow.value()),
            "cp_cellprob_threshold": float(self.sp_cp_prob.value()),
            "rods_only": bool(self.cb_rods_only.isChecked()),
            "rods_min_major_axis_px": float(self.sp_rods_min_major.value()),
            "rods_min_aspect_ratio": float(self.sp_rods_min_ar.value()),
            "rods_min_eccentricity": float(self.sp_rods_min_ecc.value()),
            "rods_min_area_px": int(self.sp_min_area.value()),
            "ellipse_thickness_px": int(self.sp_ellipse_thick.value()),
            "export_legacy_csv": bool(self.cb_export_legacy.isChecked()),
        }


def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="afm",
        display_name="AFM",
        create_panel=lambda: AfmPanel(),
    )
