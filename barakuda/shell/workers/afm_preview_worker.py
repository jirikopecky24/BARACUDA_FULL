from __future__ import annotations
import traceback
import imageio.v2 as iio
import numpy as np

from PyQt6.QtCore import QObject, pyqtSignal

from barakuda.devices.afm.core.afm_v2_pipeline import run_afm_v2, AfmV2Params
from barakuda.devices.afm.core.overlay_ellipse import render_ellipse_overlay

class AfmPreviewWorker(QObject):
    """Worker thread for AFM Cellpose preview.
    Runs segmentation and ellipse rendering without freezing the UI.
    """
    finished = pyqtSignal(object)  # payload dict: overlay, n_rods, loader_meta
    error = pyqtSignal(str)        # traceback string
    progress = pyqtSignal(str)     # status text

    def __init__(self, file_path: str, roi_rect: tuple[int, int, int, int], afm_params: dict):
        super().__init__()
        self.file_path = file_path
        self.roi_rect = roi_rect
        self.afm_params = afm_params
        self._is_cancelled = False

    def cancel(self):
        """Soft cancel (ignores result, doesn't hard-kill C++)."""
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled:
            return

        try:
            self.progress.emit("Loading image...")
            loader_meta = None
            if self.file_path.lower().endswith(".spm"):
                from barakuda.devices.afm.io.afmreader_loader import load_spm_height
                img_orig, loader_meta = load_spm_height(self.file_path)
            else:
                img_orig = iio.imread(self.file_path)

            if self._is_cancelled:
                return

            img = img_orig
            # ensure 2D grayscale for segmentation (PNG can be RGB)
            if img.ndim == 3:
                if img.shape[-1] >= 3:
                    img = (img[..., 0].astype(np.float32) * 0.299 +
                           img[..., 1].astype(np.float32) * 0.587 +
                           img[..., 2].astype(np.float32) * 0.114)
                else:
                    img = img[..., 0]
            img = np.asarray(img, dtype=np.float32)

            # crop ROI
            x, y, w, h = self.roi_rect
            H, W = img.shape[:2]
            x = max(0, min(x, W - 1))
            y = max(0, min(y, H - 1))
            w = max(1, min(w, W - x))
            h = max(1, min(h, H - y))
            roi_img = img[y:y + h, x:x + w]

            def _f(key, default): return float(self.afm_params.get(key, default))
            def _i(key, default): return int(self.afm_params.get(key, default))
            def _b(key, default): return bool(self.afm_params.get(key, default))
            def _s(key, default): return str(self.afm_params.get(key, default))

            p_v2 = AfmV2Params(
                invert=_b("invert", False),
                clip_p_low=_f("clip_p_low", 1.0),
                clip_p_high=_f("clip_p_high", 99.0),
                cp_model=_s("cp_model", "cyto3"),
                cp_diameter=_f("cp_diameter", 0.0),
                cp_flow_threshold=_f("cp_flow_threshold", 0.4),
                cp_cellprob_threshold=_f("cp_cellprob_threshold", -0.5),
                rods_only=_b("rods_only", True),
                rods_min_major_axis_px=_f("rods_min_major_axis_px", 12.0),
                rods_min_aspect_ratio=_f("rods_min_aspect_ratio", 1.8),
                rods_min_eccentricity=_f("rods_min_eccentricity", 0.65),
                rods_min_area_px=_i("rods_min_area_px", 8),
                ellipse_thickness_px=_i("ellipse_thickness_px", 2),
            )

            # Cellpose inference can take a while and freeze here
            self.progress.emit("Cellpose: segmentation running...")
            res = run_afm_v2(roi_img, p_v2)

            if self._is_cancelled:
                return

            self.progress.emit("Rendering overlay...")
            rod_table = res["rod_table"]
            n_rods = len(rod_table.get("label", []))

            overlay = render_ellipse_overlay(
                roi_img, rod_table, thickness_px=int(p_v2.ellipse_thickness_px)
            )

            if not self._is_cancelled:
                payload = {
                    "overlay": overlay,
                    "n_rods": n_rods,
                    "loader_meta": loader_meta,
                }
                self.finished.emit(payload)

        except Exception:
            if not self._is_cancelled:
                self.error.emit(traceback.format_exc())
