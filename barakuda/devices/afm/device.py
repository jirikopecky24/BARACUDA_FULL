from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton, QComboBox
from barakuda.devices.base import DeviceSpec


class AfmPanel(QWidget):
    run_batch_clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        title = QLabel("AFM — Bacteria Segmentation")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)
        
        
        self.btn_preview = QPushButton("Preview AFM")
        layout.addWidget(self.btn_preview)

        form = QFormLayout()

        self.cb_height_aware = QCheckBox("AFM height normalization (recommended)")
        self.cb_height_aware.setChecked(True)
        form.addRow(self.cb_height_aware)

        self.cb_separate = QCheckBox("Separate touching objects (watershed)")
        self.cb_separate.setChecked(True)
        form.addRow(self.cb_separate)

        self.cb_save_overlay = QCheckBox("Save overlay (segmentation on RGB)")
        self.cb_save_overlay.setChecked(True)
        form.addRow(self.cb_save_overlay)

        # Hidden but kept for compatibility if needed
        self.cb_use_contours = QCheckBox("Contour-first mode (closed outlines)")
        self.cb_use_contours.setChecked(False) 
        self.cb_use_contours.hide() # Hidden
        # layout.addWidget(self.cb_use_contours) # Removed from layout, kept as member

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

        # Renamed/Used as general edge sigma
        self.sp_edge_sigma = QDoubleSpinBox()
        self.sp_edge_sigma.setRange(0.2, 10.0)
        self.sp_edge_sigma.setDecimals(2)
        self.sp_edge_sigma.setValue(1.2)
        form.addRow("Edge sigma", self.sp_edge_sigma)

        # Hidden params (Canny)
        self.sp_canny_low = QDoubleSpinBox()
        self.sp_canny_low.setRange(0.0, 1.0)
        self.sp_canny_low.setDecimals(3)
        self.sp_canny_low.setValue(0.05)
        self.sp_canny_low.hide()
        # form.addRow("Canny low (0..1)", self.sp_canny_low)

        self.sp_canny_high = QDoubleSpinBox()
        self.sp_canny_high.setRange(0.0, 1.0)
        self.sp_canny_high.setDecimals(3)
        self.sp_canny_high.setValue(0.20)
        self.sp_canny_high.hide()
        # form.addRow("Canny high (0..1)", self.sp_canny_high)

        # Hidden params
        self.sp_edge_dilate = QSpinBox()
        self.sp_edge_dilate.setRange(0, 10)
        self.sp_edge_dilate.setValue(1)
        self.sp_edge_dilate.hide()
        # form.addRow("Edge dilate (px)", self.sp_edge_dilate)

        # Hidden - duplicate?
        self.sp_close_radius = QSpinBox()
        self.sp_close_radius.setRange(0, 20)
        self.sp_close_radius.setValue(2)
        self.sp_close_radius.hide()
        # form.addRow("Close radius (px)", self.sp_close_radius)

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

        # Duplicate - hidden
        self.sp_fill_holes = QSpinBox()
        self.sp_fill_holes.setRange(0, 50000)
        self.sp_fill_holes.setValue(300)
        self.sp_fill_holes.hide()
        # form.addRow("Fill holes area (px)", self.sp_fill_holes)

        self.sp_log_sigma = QDoubleSpinBox()
        self.sp_log_sigma.setRange(0.5, 10.0)
        self.sp_log_sigma.setDecimals(2)
        self.sp_log_sigma.setValue(2.0)
        form.addRow("LoG sigma", self.sp_log_sigma)

        self.sp_peak_dist = QSpinBox()
        self.sp_peak_dist.setRange(1, 50)
        self.sp_peak_dist.setValue(6)
        form.addRow("Peak min distance (px)", self.sp_peak_dist)

        # Watershed compactness (shape regularization)
        self.sp_compactness = QDoubleSpinBox()
        self.sp_compactness.setRange(0.0, 0.20)
        self.sp_compactness.setDecimals(3)
        self.sp_compactness.setSingleStep(0.005)
        self.sp_compactness.setValue(0.020)
        form.addRow("Watershed compactness", self.sp_compactness)

        # Outline smoothing radius (px) — visualization-only geometric regularization
        self.sp_outline_smooth = QSpinBox()
        self.sp_outline_smooth.setRange(0, 6)
        self.sp_outline_smooth.setSingleStep(1)
        self.sp_outline_smooth.setValue(2)
        form.addRow("Outline smoothing radius (px)", self.sp_outline_smooth)

        # Outline thickness (px) — controls visible stroke thickness
        self.sp_outline_thick = QSpinBox()
        self.sp_outline_thick.setRange(0, 3)  # 0 = thinnest (1px boundary), 2 = ~2–3px
        self.sp_outline_thick.setSingleStep(1)
        self.sp_outline_thick.setValue(2)
        form.addRow("Outline thickness (px)", self.sp_outline_thick)

        # Output / Export settings
        # ...

        # Outline mode (Strict / Inclusive)
        self.cb_outline_mode = QComboBox()
        self.cb_outline_mode.addItems(["inclusive", "strict"])
        self.cb_outline_mode.setCurrentText("inclusive")
        form.addRow("Outline mode", self.cb_outline_mode)

        self.sp_outline_ring = QSpinBox()
        self.sp_outline_ring.setRange(1, 6)
        self.sp_outline_ring.setValue(2)
        form.addRow("Outline ring radius (px)", self.sp_outline_ring)

        self.sp_outline_edge_sigma = QDoubleSpinBox()
        self.sp_outline_edge_sigma.setRange(0.5, 3.0)
        self.sp_outline_edge_sigma.setDecimals(2)
        self.sp_outline_edge_sigma.setSingleStep(0.1)
        self.sp_outline_edge_sigma.setValue(1.2)
        form.addRow("Outline edge sigma (px)", self.sp_outline_edge_sigma)

        self.sp_outline_canny_low = QDoubleSpinBox()
        self.sp_outline_canny_low.setRange(0.01, 0.49)
        self.sp_outline_canny_low.setDecimals(2)
        self.sp_outline_canny_low.setSingleStep(0.01)
        self.sp_outline_canny_low.setValue(0.10)
        form.addRow("Outline canny low", self.sp_outline_canny_low)

        self.sp_outline_canny_high = QDoubleSpinBox()
        self.sp_outline_canny_high.setRange(0.05, 0.95)
        self.sp_outline_canny_high.setDecimals(2)
        self.sp_outline_canny_high.setSingleStep(0.01)
        self.sp_outline_canny_high.setValue(0.30)
        form.addRow("Outline canny high", self.sp_outline_canny_high)

        # Hidden global threshold factor
        self.sp_low_factor = QDoubleSpinBox()
        self.sp_low_factor.setRange(0.0, 1.00) # Allow 0.0
        self.sp_low_factor.setDecimals(2)
        self.sp_low_factor.setSingleStep(0.05)
        self.sp_low_factor.setValue(0.45)
        self.sp_low_factor.hide()
        # form.addRow("Low mask factor (k * std)", self.sp_low_factor)

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
        # form.addRow("Area bins (freq)", self.sp_bins) # User didn't ask to remove this, but didn't list in "Keep". 
        # But listed in Defaults: "Area bins = 20". So keep it, but maybe hide if not important?
        # User says "Smazat z UI ... Canny ... Edge dilate ... druhy fill/close".
        # It doesn't say remove Bins. I'll keep it visible or hide if "UI čisté a přehledné" is priority?
        # "smazat z UI" implies removing from view. 
        # "Area bins" is for histogram. Useful. I'll keep it.
        form.addRow("Area bins (freq)", self.sp_bins)



        layout.addLayout(form)
        layout.addWidget(QLabel("ROI z Preview se použije jako výpočetní oblast."))
        
        self.btn_reset = QPushButton("Reset AFM defaults")
        self.btn_reset.clicked.connect(self.apply_afm_defaults)
        layout.addWidget(self.btn_reset)
        
        self.btn_run = QPushButton("Spustit AFM Batch")
        self.btn_run.clicked.connect(self.run_batch_clicked.emit)
        layout.addWidget(self.btn_run)
        
        layout.addStretch(1)
        
        # Apple Defaults immediately
        self.apply_afm_defaults()
        self.apply_afm_tooltips()

    def apply_afm_defaults(self):
        # ===============================
        # AFM DEFAULT PROFILE (Publication - Stable Manual Tuned Version)
        # ===============================

        # Core toggles (Publication profile)
        self.cb_height_aware.setChecked(False)       # AFM height normalization OFF
        self.cb_separate.setChecked(True)            # Separate touching objects ON
        self.cb_save_overlay.setChecked(True)        # Save overlay ON
        self.cb_invert.setChecked(False)             # Invert OFF
        self.cb_use_contours.setChecked(False)

        # Core sigmas
        self.sp_bg.setValue(4.0)
        self.sp_smooth.setValue(0.20)
        self.sp_edge_sigma.setValue(1.30)        # sweet spot 1.2–1.4

        # Canny (hidden but keep consistent)
        self.sp_canny_low.setValue(0.05)
        self.sp_canny_high.setValue(0.20)

        # Hidden internal closing/fill (leave stable)
        self.sp_close_radius.setValue(2)
        self.sp_fill_holes.setValue(300)

        # Filters (high coverage but not pure noise)
        self.sp_min_perim.setValue(10)
        self.sp_min_ecc.setValue(0.05)
        self.sp_min_sol.setValue(0.35)

        # Detection / separation
        self.sp_log_sigma.setValue(1.60)         # 1.5–1.8 (publication-friendly)
        self.sp_peak_dist.setValue(3)
        self.sp_compactness.setValue(0.030)      # geometric / print-ready
        self.sp_low_factor.setValue(0.45)        # keep internal threshold stable

        # Object filtering / Mask stabilization
        self.sp_min_area.setValue(15)
        self.sp_close.setValue(1)
        self.sp_holes.setValue(80) 
        self.sp_bins.setValue(20)

        # Outline design controls
        self.sp_outline_smooth.setValue(2)
        self.sp_outline_thick.setValue(2)

        # Inclusive Outline (Publication)
        self.cb_outline_mode.setCurrentText("inclusive")
        self.sp_outline_ring.setValue(2)
        self.sp_outline_edge_sigma.setValue(1.3)
        self.sp_outline_canny_low.setValue(0.08)
        self.sp_outline_canny_high.setValue(0.24)

    def apply_afm_tooltips(self):
        # ==============================
        # AFM PARAMETER TOOLTIPS (hover)
        # ==============================

        # Checkboxes
        self.cb_height_aware.setToolTip(
            "AFM height normalization: row leveling + background subtraction + percentile clipping.\n"
            "Use ON for more stable, comparable segmentation across datasets."
        )
        self.cb_separate.setToolTip(
            "Separate touching objects (watershed).\n"
            "ON = tries to split touching bacteria into instances.\n"
            "OFF = returns a single connected mask (no instance separation)."
        )
        self.cb_save_overlay.setToolTip(
            "Save overlay image with red contours drawn on the preview (RGB) image."
        )
        self.cb_invert.setToolTip(
            "Invert intensity assumption.\n"
            "Use only if bacteria appear DARK relative to background in the processed image."
        )

        # Sigma parameters
        self.sp_bg.setToolTip(
            "Background sigma [px].\n"
            "Controls how aggressively large-scale surface trends are removed.\n"
            "Higher = more background removal (flattening), lower = keeps more long-scale structure."
        )
        self.sp_smooth.setToolTip(
            "Smooth sigma [px].\n"
            "Gaussian smoothing before segmentation.\n"
            "Higher = less noise but can merge nearby objects; lower = sharper details but more false detections."
        )
        self.sp_edge_sigma.setToolTip(
            "Edge sigma [px].\n"
            "Scale used for edge/gradient emphasis.\n"
            "Lower = more sensitive to fine edges (may pick texture), higher = smoother edges."
        )

        # Shape filters
        self.sp_min_perim.setToolTip(
            "Min perimeter [px].\n"
            "Rejects objects with small boundary length (removes fragments / tiny detections)."
        )
        self.sp_min_ecc.setToolTip(
            "Min eccentricity [0–1].\n"
            "0 = circle-like, 1 = very elongated.\n"
            "Higher values keep elongated shapes and reject round/irregular noise."
        )
        self.sp_min_sol.setToolTip(
            "Min solidity [0–1].\n"
            "Solidity = area / convex hull area.\n"
            "Higher rejects concave/fragmented shapes; lower keeps more irregular shapes."
        )

        # Watershed / marker control
        self.sp_log_sigma.setToolTip(
            "LoG sigma [px].\n"
            "Scale for Laplacian-of-Gaussian used to find marker candidates.\n"
            "Higher = fewer markers (less over-segmentation), lower = more markers (risk of over-segmentation)."
        )
        self.sp_peak_dist.setToolTip(
            "Peak min distance [px].\n"
            "Minimum distance between detected local maxima (watershed markers).\n"
            "Higher = fewer seeds (less splitting), lower = more seeds (more splitting / possible map-like result)."
        )
        self.sp_compactness.setToolTip(
            "Watershed compactness (tvarová regularizace při watershed).\n"
            "Zvyšuje geometrickou pravidelnost a hladkost objektů (méně zubaté kontury).\n"
            "Vyšší hodnota = hladší/symetričtější tvary, ale může mírně potlačit jemné detaily.\n"
            "Jednotky: bezrozměrné (0.0–0.2). Doporučení: 0.015–0.030 pro publikovatelný vzhled."
        )
        self.sp_outline_smooth.setToolTip(
            "Outline smoothing radius (px).\n"
            "Použije se pouze pro vykreslení obrysu (ne měření).\n"
            "Vyšší hodnota = symetričtější, hladší kontury (publikovatelný vzhled), "
            "ale může mírně zaoblovat jemné detaily.\n"
            "0 = vypnuto. Doporučeno: 2."
        )

        self.sp_outline_thick.setToolTip(
            "Outline thickness (px).\n"
            "Řídí tloušťku žluté kontury ve výstupu.\n"
            "0 = nejtenčí (cca 1px), 1 = tenké, 2 = ~2–3px (doporučeno pro tisk), 3 = tlusté.\n"
            "Doporučeno: 2."
        )

        self.cb_outline_mode.setToolTip(
            "Outline mode.\n"
            "strict = obrys jen z masky (konzervativní).\n"
            "inclusive = obrys z masky + dokreslení hran z intenzity, ale jen v prstenci okolo masky.\n"
            "Inclusive je určený pro publikovatelný vizuál s maximálním pokrytím."
        )
        self.sp_outline_ring.setToolTip(
            "Outline ring radius (px).\n"
            "Šířka prstence okolo masky, kde se hledají extra hrany.\n"
            "Vyšší = více doplněných bakterií, ale může přidat šum. Doporučeno 2–3."
        )
        self.sp_outline_edge_sigma.setToolTip(
            "Outline edge sigma (px).\n"
            "Vyhlazení pro Canny hrany v inclusive režimu.\n"
            "Vyšší = hladší, symetričtější kontury (méně zubaté). Doporučeno 1.1–1.6."
        )
        self.sp_outline_canny_low.setToolTip(
            "Canny low threshold (0–1).\n"
            "Nižší = označí více hran (vyšší coverage), ale riziko šumu."
        )
        self.sp_outline_canny_high.setToolTip(
            "Canny high threshold (0–1).\n"
            "Nižší = více hran (vyšší coverage). Typicky high ~ 3× low."
        )

        # Post-processing / cleanup
        self.sp_min_area.setToolTip(
            "Min area [px²].\n"
            "Rejects small objects (noise). Increase if you see many tiny detections."
        )
        self.sp_close.setToolTip(
            "Closing radius [px].\n"
            "Morphological closing to connect small gaps and smooth boundaries.\n"
            "Higher can merge neighbors; use small values (0–2) for bacteria."
        )
        self.sp_holes.setToolTip(
            "Fill holes area [px²].\n"
            "Fills small holes inside objects up to this area.\n"
            "Increase if bacteria have unwanted internal holes."
        )
        self.sp_bins.setToolTip(
            "Area bins [count].\n"
            "Number of bins used for area histogram in exported statistics."
        )

    def get_afm_params(self) -> dict:
        return {
            "height_aware": bool(self.cb_height_aware.isChecked()),
            "save_overlay": bool(self.cb_save_overlay.isChecked()),
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
            "watershed_compactness": float(self.sp_compactness.value()),
            "peak_min_distance": int(self.sp_peak_dist.value()),
            "low_mask_factor": float(self.sp_low_factor.value()),
            "min_area_px": int(self.sp_min_area.value()),
            "closing_radius_px": int(self.sp_close.value()),
            "hole_area_px": int(self.sp_holes.value()),
            "area_bins": int(self.sp_bins.value()),
            "outline_smoothing_radius_px": int(self.sp_outline_smooth.value()),
            "edge_thickness_px": int(self.sp_outline_thick.value()),
            "outline_mode": str(self.cb_outline_mode.currentText()),
            "outline_ring_radius_px": int(self.sp_outline_ring.value()),
            "outline_edge_sigma": float(self.sp_outline_edge_sigma.value()),
            "outline_canny_low": float(self.sp_outline_canny_low.value()),
            "outline_canny_high": float(self.sp_outline_canny_high.value()),
        }

def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="afm",
        display_name="AFM",
        create_panel=lambda: AfmPanel(),
    )
