from __future__ import annotations
import traceback
import imageio.v2 as iio
import numpy as np

from PyQt6.QtCore import QObject, pyqtSignal

from barakuda.devices.afm.core.afm_v2_pipeline import run_afm_v2, AfmV2Params
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

            # ── Data Prep (5%) ──────────────────────────────
            self.progress_pct.emit(5, "Preprocessing...")
            from barakuda.devices.afm.core.afm_v2_pipeline import _normalize, rod_filter
            import math
            
            norm = _normalize(roi_img, p_v2.invert, p_v2.clip_p_low, p_v2.clip_p_high)
            img8 = (norm * 255.0).astype(np.uint8)

            if self._is_cancelled:
                return
                
            self.progress_pct.emit(15, "Initializing Cellpose...")
            
            from barakuda.devices.afm.core.afm_v2_pipeline import _HAS_CELLPOSE, cp_models
            if not _HAS_CELLPOSE:
                raise RuntimeError("Cellpose is not installed.")

            if hasattr(cp_models, "Cellpose"):
                model = cp_models.Cellpose(model_type=p_v2.cp_model)
            else:
                model = cp_models.CellposeModel(model_type=p_v2.cp_model)
                
            self.progress_pct.emit(20, "Cellpose: starting inference...")
            
            # ── Tiled Inference (20% to 80%) ────────────────────────
            H, W = img8.shape
            TILE_SIZE = 320
            OVERLAP = 32
            STEP = TILE_SIZE - OVERLAP
            
            y_starts = list(range(0, max(1, H - OVERLAP), STEP))
            x_starts = list(range(0, max(1, W - OVERLAP), STEP))
            
            # ensure we cover edges
            if y_starts[-1] + TILE_SIZE < H: y_starts.append(H - TILE_SIZE)
            if x_starts[-1] + TILE_SIZE < W: x_starts.append(W - TILE_SIZE)
            
            total_tiles = len(y_starts) * len(x_starts)
            done_tiles = 0
            
            global_masks = np.zeros((H, W), dtype=np.int32)
            max_label = 0
            
            for y in y_starts:
                for x in x_starts:
                    if self._is_cancelled:
                        return
                        
                    y0, y1 = max(0, y), min(H, y + TILE_SIZE)
                    x0, x1 = max(0, x), min(W, x + TILE_SIZE)
                    
                    tile = img8[y0:y1, x0:x1]
                    
                    # evaluate tile
                    eval_out = model.eval(
                        tile,
                        channels=[0, 0],
                        diameter=(None if p_v2.cp_diameter == 0 else float(p_v2.cp_diameter)),
                        flow_threshold=float(p_v2.cp_flow_threshold),
                        cellprob_threshold=float(p_v2.cp_cellprob_threshold),
                    )
                    
                    tile_masks = eval_out[0].astype(np.int32)
                    
                    # merge into global (simple max approach for overlap)
                    has_mask = tile_masks > 0
                    if np.any(has_mask):
                        shifted = tile_masks + max_label
                        shifted[~has_mask] = 0
                        
                        view = global_masks[y0:y1, x0:x1]
                        # overwrite where background currently
                        replace_mask = (view == 0) & has_mask
                        view[replace_mask] = shifted[replace_mask]
                        
                        max_label = np.max(shifted)
                        
                    done_tiles += 1
                    pct = 20 + int(60 * done_tiles / total_tiles)
                    self.progress_pct.emit(pct, f"Cellpose {done_tiles}/{total_tiles}")

            if self._is_cancelled:
                return

            self.progress_pct.emit(85, "Filtering shapes...")

            if p_v2.rods_only:
                final_masks, rod_table = rod_filter(global_masks, p_v2)
            else:
                from skimage import measure
                final_masks = global_masks
                props = measure.regionprops(final_masks)
                keep_labels = [p.label for p in props if p.area >= p_v2.rods_min_area_px]
                
                # fake rod table for area filter
                rod_table = {
                    "label": np.array(keep_labels, dtype=np.int32)
                }
                
                # apply area filter
                filtered_mask = np.zeros_like(final_masks)
                for lbl in keep_labels:
                    filtered_mask[final_masks == lbl] = lbl
                final_masks = filtered_mask

            if self._is_cancelled:
                return

            self.progress_pct.emit(95, "Rendering overlay...")
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
                self.progress_pct.emit(100, "Done")
                self.finished.emit(payload)

        except Exception:
            if not self._is_cancelled:
                self.error.emit(traceback.format_exc())
