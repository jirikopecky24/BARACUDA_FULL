from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton
from barakuda.devices.base import DeviceSpec


class AfmPanel(QWidget):
    run_batch_clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        title = QLabel("AFM — Bacteria Segmentation")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        form = QFormLayout()

        self.cb_separate = QCheckBox("Separate touching objects (watershed)")
        self.cb_separate.setChecked(True)
        form.addRow(self.cb_separate)

        self.cb_use_contours = QCheckBox("Contour-first mode (closed outlines)")
        self.cb_use_contours.setChecked(True)
        layout.addWidget(self.cb_use_contours)

        self.cb_invert = QCheckBox("Invert (bacteria are dark)")
        self.cb_invert.setChecked(False)
        form.addRow(self.cb_invert)

        self.sp_bg = QDoubleSpinBox()
        self.sp_bg.setRange(0.1, 1000.0)
        self.sp_bg.setDecimals(2)
        self.sp_bg.setValue(12.0)
        form.addRow("Background sigma", self.sp_bg)

        self.sp_smooth = QDoubleSpinBox()
        self.sp_smooth.setRange(0.0, 50.0)
        self.sp_smooth.setDecimals(2)
        self.sp_smooth.setValue(1.0)
        form.addRow("Smooth sigma", self.sp_smooth)

        self.sp_edge_sigma = QDoubleSpinBox()
        self.sp_edge_sigma.setRange(0.2, 10.0)
        self.sp_edge_sigma.setDecimals(2)
        self.sp_edge_sigma.setValue(1.2)
        form.addRow("Edge sigma", self.sp_edge_sigma)

        self.sp_canny_low = QDoubleSpinBox()
        self.sp_canny_low.setRange(0.0, 1.0)
        self.sp_canny_low.setDecimals(3)
        self.sp_canny_low.setValue(0.05)
        form.addRow("Canny low (0..1)", self.sp_canny_low)

        self.sp_canny_high = QDoubleSpinBox()
        self.sp_canny_high.setRange(0.0, 1.0)
        self.sp_canny_high.setDecimals(3)
        self.sp_canny_high.setValue(0.20)
        form.addRow("Canny high (0..1)", self.sp_canny_high)

        self.sp_edge_dilate = QSpinBox()
        self.sp_edge_dilate.setRange(0, 10)
        self.sp_edge_dilate.setValue(1)
        form.addRow("Edge dilate (px)", self.sp_edge_dilate)

        self.sp_close_radius = QSpinBox()
        self.sp_close_radius.setRange(0, 20)
        self.sp_close_radius.setValue(2)
        form.addRow("Close radius (px)", self.sp_close_radius)

        self.sp_min_perim = QSpinBox()
        self.sp_min_perim.setRange(0, 10000)
        self.sp_min_perim.setValue(60)
        form.addRow("Min perimeter (px)", self.sp_min_perim)

        self.sp_min_ecc = QDoubleSpinBox()
        self.sp_min_ecc.setRange(0.0, 0.999)
        self.sp_min_ecc.setDecimals(2)
        self.sp_min_ecc.setValue(0.70)
        form.addRow("Min eccentricity", self.sp_min_ecc)

        self.sp_min_sol = QDoubleSpinBox()
        self.sp_min_sol.setRange(0.0, 1.0)
        self.sp_min_sol.setDecimals(2)
        self.sp_min_sol.setValue(0.50)
        form.addRow("Min solidity", self.sp_min_sol)

        self.sp_fill_holes = QSpinBox()
        self.sp_fill_holes.setRange(0, 50000)
        self.sp_fill_holes.setValue(300)
        form.addRow("Fill holes area (px)", self.sp_fill_holes)

        self.sp_log_sigma = QDoubleSpinBox()
        self.sp_log_sigma.setRange(0.5, 10.0)
        self.sp_log_sigma.setDecimals(2)
        self.sp_log_sigma.setValue(2.0)
        form.addRow("LoG sigma", self.sp_log_sigma)

        self.sp_peak_dist = QSpinBox()
        self.sp_peak_dist.setRange(1, 50)
        self.sp_peak_dist.setValue(6)
        form.addRow("Peak min distance (px)", self.sp_peak_dist)

        self.sp_low_factor = QDoubleSpinBox()
        self.sp_low_factor.setRange(0.10, 1.00)
        self.sp_low_factor.setDecimals(2)
        self.sp_low_factor.setSingleStep(0.05)
        self.sp_low_factor.setValue(0.45)
        form.addRow("Low mask factor", self.sp_low_factor)

        self.sp_min_area = QSpinBox()
        self.sp_min_area.setRange(1, 10_000_000)
        self.sp_min_area.setValue(120)
        form.addRow("Min area (px)", self.sp_min_area)

        self.sp_close = QSpinBox()
        self.sp_close.setRange(0, 50)
        self.sp_close.setValue(2)
        form.addRow("Closing radius (px)", self.sp_close)

        self.sp_holes = QSpinBox()
        self.sp_holes.setRange(0, 10_000_000)
        self.sp_holes.setValue(240)
        form.addRow("Fill holes area (px)", self.sp_holes)

        self.sp_bins = QSpinBox()
        self.sp_bins.setRange(5, 200)
        self.sp_bins.setValue(20)
        form.addRow("Area bins (freq)", self.sp_bins)

        layout.addLayout(form)
        layout.addWidget(QLabel("ROI z Preview se použije jako výpočetní oblast."))
        
        self.btn_run = QPushButton("Spustit AFM Batch")
        self.btn_run.clicked.connect(self.run_batch_clicked.emit)
        layout.addWidget(self.btn_run)
        
        layout.addStretch(1)

    def get_afm_params(self) -> dict:
        return {
            "use_contours": bool(self.cb_use_contours.isChecked()),
            "separate": bool(self.cb_separate.isChecked()),
            "invert": bool(self.cb_invert.isChecked()),
            "bg_sigma": float(self.sp_bg.value()),
            "smooth_sigma": float(self.sp_smooth.value()),
            "edge_sigma": float(self.sp_edge_sigma.value()),
            "canny_low": float(self.sp_canny_low.value()),
            "canny_high": float(self.sp_canny_high.value()),
            "edge_dilate_px": int(self.sp_edge_dilate.value()),
            "close_radius_px": int(self.sp_close_radius.value()),
            "fill_holes_area_px": int(self.sp_fill_holes.value()),
            "min_perimeter_px": int(self.sp_min_perim.value()),
            "min_eccentricity": float(self.sp_min_ecc.value()),
            "min_solidity": float(self.sp_min_sol.value()),
            "log_sigma": float(self.sp_log_sigma.value()),
            "peak_min_distance_px": int(self.sp_peak_dist.value()),
            "low_mask_factor": float(self.sp_low_factor.value()),
            "min_area_px": int(self.sp_min_area.value()),
            "closing_radius_px": int(self.sp_close.value()),
            "hole_area_px": int(self.sp_holes.value()),
            "area_bins": int(self.sp_bins.value()),
        }

def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="afm",
        display_name="AFM",
        create_panel=lambda: AfmPanel(),
    )
