from __future__ import annotations
import traceback
import imageio.v2 as iio
import numpy as np

from PyQt6.QtCore import QObject, pyqtSignal

from barakuda.devices.afm.core.afm_v2_pipeline import _normalize
from barakuda.devices.afm.core.overlay_ellipse import render_ellipse_overlay
from barakuda.devices.afm.methods import get_afm_method

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
            resolved_path = self.file_path
            try:
                from barakuda.devices.afm.manifest import resolve_afm_input_path

                resolved = resolve_afm_input_path(self.file_path)
                if resolved.image_path is not None:
                    resolved_path = str(resolved.image_path)
            except Exception:
                resolved_path = self.file_path

            if resolved_path.lower().endswith(".spm"):
                from barakuda.devices.afm.io.afmreader_loader import load_spm_height
                img_orig, loader_meta = load_spm_height(resolved_path)
            else:
                img_orig = iio.imread(resolved_path)

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

            method = get_afm_method(self.afm_params.get("afm_method"))
            runtime_params = method.build_runtime_params(self.afm_params)

            # ── Data Prep (5%) ──────────────────────────────
            self.progress_pct.emit(5, "Preprocessing...")

            if self._is_cancelled:
                return
                
            self.progress_pct.emit(15, "Initializing Cellpose...")
            
            from barakuda.devices.afm.core.afm_v2_pipeline import _HAS_CELLPOSE, _CELLPOSE_VERSION
            if not _HAS_CELLPOSE:
                raise RuntimeError("Cellpose is not installed.")

            self.progress_pct.emit(15, f"Cellpose version: {_CELLPOSE_VERSION}")

            if self._is_cancelled:
                return

            self.progress_pct.emit(20, "Cellpose: starting inference...")
            um_per_px = float(loader_meta.get("afm_um_per_px", 0.0)) if loader_meta else 0.0
            
            v2_out = method.compute(roi_img, runtime_params, um_per_px=um_per_px)

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

            # Render overlay directly on the FULL image
            full_norm = _normalize(img, runtime_params.invert, runtime_params.clip_p_low, runtime_params.clip_p_high)
            full_img8 = (full_norm * 255.0).astype(np.uint8)
            overlay = render_ellipse_overlay(
                full_img8, rod_table,
                thickness_px=int(runtime_params.ellipse_thickness_px),
                ellipse_alpha=float(runtime_params.ellipse_alpha),
            )

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
