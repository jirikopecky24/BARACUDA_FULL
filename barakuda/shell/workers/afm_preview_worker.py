from __future__ import annotations
import traceback
import imageio.v2 as iio
import numpy as np

from PyQt6.QtCore import QObject, pyqtSignal

from barakuda.devices.afm.core.afm_v2_pipeline import run_afm_v2, AfmV2Params, _normalize
from barakuda.devices.afm.core.overlay_ellipse import render_ellipse_overlay

import sys
import re

class _ProgressCatcher(object):
    def __init__(self, original_stream, signal_emit):
        self.original_stream = original_stream
        self.signal_emit = signal_emit
        self.buf = ""

    def write(self, s):
        try:
            self.original_stream.write(s)
        except Exception:
            pass
            
        self.buf += s
        while '\r' in self.buf or '\n' in self.buf:
            c = '\r' if '\r' in self.buf else '\n'
            line, _, self.buf = self.buf.partition(c)
            line = line.strip()
            if not line:
                continue
            
            pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', line)
            if pct_match:
                pct = pct_match.group(1)
                if "download" in line.lower():
                    self.signal_emit(f"Downloading model... {pct}%")
                else:
                    self.signal_emit(f"Cellpose running... {pct}%")
            elif "downloading" in line.lower():
                self.signal_emit("Downloading Cellpose model...")

    def flush(self):
        try:
            self.original_stream.flush()
        except Exception:
            pass

class AfmPreviewWorker(QObject):
    """Worker thread for AFM Cellpose preview.
    Runs segmentation and ellipse rendering without freezing the UI.
    """
    finished = pyqtSignal(object)  # payload dict: overlay, n_rods, loader_meta
    error = pyqtSignal(str)        # traceback string
    progress_pct = pyqtSignal(int, str)  # (percent, message)

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
            self.progress_pct.emit(0, "Loading image...")
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
            
            self.progress_pct.emit(0, f"Diag: raw shape=({H}, {W})")
            self.progress_pct.emit(0, f"Diag: ROI raw px=(x={x}, y={y}, w={w}, h={h})")
            self.progress_pct.emit(0, f"Diag: cropped shape={roi_img.shape}")

            def _f(key, default): return float(self.afm_params.get(key, default))
            def _i(key, default): return int(self.afm_params.get(key, default))
            def _b(key, default): return bool(self.afm_params.get(key, default))
            def _s(key, default): return str(self.afm_params.get(key, default))

            _cp_diam_px = self.afm_params.get("cp_diameter_px")
            p_v2 = AfmV2Params(
                compute_profile=_s("compute_profile", "auto"),
                preview_fast_mode=_b("preview_fast_mode", False),
                preview_downscale=_f("preview_downscale", 0.5),
                invert=_b("invert", False),
                clip_p_low=_f("clip_p_low", 1.0),
                clip_p_high=_f("clip_p_high", 99.0),
                cp_model=_s("cp_model", "cyto3"),
                cp_diameter_mode=_s("cp_diameter_mode", "auto"),
                cp_diameter_px=int(_cp_diam_px) if _cp_diam_px is not None else None,
                cp_flow_threshold=_f("cp_flow_threshold", 0.4),
                cp_cellprob_threshold=_f("cp_cellprob_threshold", -0.5),
                rods_only=_b("rods_only", True),
                rods_min_major_axis_px=_f("rods_min_major_axis_px", 12.0),
                rods_min_aspect_ratio=_f("rods_min_aspect_ratio", 1.8),
                rods_min_eccentricity=_f("rods_min_eccentricity", 0.65),
                rods_min_area_px=_i("rods_min_area_px", 8),
                ellipse_thickness_px=_i("ellipse_thickness_px", 2),
            )

            # ── Data Prep (5%) ──────────────────────────────
            self.progress_pct.emit(5, "Preprocessing...")

            if self._is_cancelled:
                return
                
            self.progress_pct.emit(15, "Initializing Cellpose...")
            
            from barakuda.devices.afm.core.afm_v2_pipeline import _HAS_CELLPOSE, _CELLPOSE_VERSION, run_afm_v2
            if not _HAS_CELLPOSE:
                raise RuntimeError("Cellpose is not installed.")

            self.progress_pct.emit(15, f"Cellpose version: {_CELLPOSE_VERSION}")

            if self._is_cancelled:
                return

            self.progress_pct.emit(20, "Cellpose: starting inference...")
            um_per_px = float(loader_meta.get("afm_um_per_px", 0.0)) if loader_meta else 0.0
            
            # The preview pipeline wraps auto-diameter, fallback routing, downscaling and filtering natively
            v2_out = run_afm_v2(roi_img, p_v2, um_per_px)

            if self._is_cancelled:
                return

            self.progress_pct.emit(80, "Inference complete.")
            
            audit = v2_out["audit"]
            timings = audit.get("timings_ms", {})
            self.progress_pct.emit(80, f"⏱️ Pre-process: {timings.get('preprocess_ms', 0)} ms")
            self.progress_pct.emit(80, f"⏱️ Cellpose Get: {timings.get('cellpose_get_ms', 0)} ms")
            self.progress_pct.emit(80, f"⏱️ Cellpose Eval: {timings.get('cellpose_eval_ms', 0)} ms")
            self.progress_pct.emit(80, f"⏱️ Post-process: {timings.get('postprocess_ms', 0)} ms")
            self.progress_pct.emit(80, f"⏱️ Total: {timings.get('total_ms', 0)} ms")
            
            cp_audit = audit.get("cellpose", {})
            dev_ui = cp_audit.get("device", "unknown")
            engine = dev_ui if dev_ui in ["cuda", "cpu"] else "unknown"
            diam_ui = cp_audit.get("diameter_effective_px", "Auto")
            self.progress_pct.emit(80, f"Device Engine: {engine} | Eff. Diameter: {diam_ui} px")

            self.progress_pct.emit(85, "Generating preview overlays...")

            final_masks = v2_out["rod_labels"]
            rod_table = v2_out["rod_table"]

            if self._is_cancelled:
                return

            self.progress_pct.emit(95, "Rendering overlay...")
            n_rods = len(rod_table.get("label", []))

            # Map rod centroids back to full image relative coords
            if "centroid_x" in rod_table and len(rod_table.get("centroid_x", [])) > 0:
                rod_table["centroid_x"] = rod_table["centroid_x"] + x
                rod_table["centroid_y"] = rod_table["centroid_y"] + y

            # Render overlay on the FULL image for context
            full_norm = _normalize(img, p_v2.invert, p_v2.clip_p_low, p_v2.clip_p_high)
            full_img8 = (full_norm * 255.0).astype(np.uint8)
            overlay = render_ellipse_overlay(
                full_img8, rod_table, thickness_px=int(p_v2.ellipse_thickness_px)
            )

            # Draw the ROI box on the overlay for clarity (yellow)
            import cv2
            cv2.rectangle(overlay, (int(x), int(y)), (int(x+w), int(y+h)), (255, 255, 0), max(1, int(p_v2.ellipse_thickness_px)))

            if not self._is_cancelled:
                payload = {
                    "overlay": overlay,
                    "n_rods": n_rods,
                    "loader_meta": loader_meta,
                }
                self.progress_pct.emit(100, "Done")
                self.finished.emit(payload)

        except Exception:
            if not self._is_cancelled:
                self.error.emit(traceback.format_exc())
