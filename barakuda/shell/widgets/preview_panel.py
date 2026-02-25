from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTabWidget, QSlider, QHBoxLayout
)

from barakuda.core.video_io import is_video_file
from barakuda.core.video_reader import VideoReader


class PreviewPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._title = QLabel("Preview")
        self._title.setStyleSheet("font-weight: 600;")

        self._tabs = QTabWidget()

        self._view_before = pg.ImageView()
        self._view_before.ui.roiBtn.hide()
        self._view_before.ui.menuBtn.hide()

        self._view_after = pg.ImageView()
        self._view_after.ui.roiBtn.hide()
        self._view_after.ui.menuBtn.hide()

        self._tabs.addTab(self._view_before, "BEFORE")
        self._tabs.addTab(self._view_after, "AFTER")

        # --- video controls ---
        self._video_row = QWidget()
        video_row_layout = QHBoxLayout(self._video_row)
        video_row_layout.setContentsMargins(0, 0, 0, 0)

        self._frame_label = QLabel("frame: -/-   t: -")
        self._frame_label.setStyleSheet("color: #666;")

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.setValue(0)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(10)
        self._slider.valueChanged.connect(self._on_slider_changed)

        video_row_layout.addWidget(self._frame_label, 0)
        video_row_layout.addWidget(self._slider, 1)

        self._video_row.setVisible(False)

        self._info = QLabel("Vyber soubor vlevo.")
        self._info.setStyleSheet("color: #666;")
        self._info.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._title)
        layout.addWidget(self._tabs, 1)
        layout.addWidget(self._video_row)
        layout.addWidget(self._info)

        self._last_before: np.ndarray | None = None
        self._after_locked: bool = False

        # video state
        self._video_path: Path | None = None
        self._reader: VideoReader | None = None
        self._is_video: bool = False
        self._current_frame_index: int = 0

        self._setting_slider: bool = False

        # ROI
        self._roi: pg.RectROI | None = None
        self._roi_shape: tuple[int, int] | None = None  # (H,W)
        self._clamping_roi: bool = False

        # scale info to display
        self._scale_text: str = "Scale: not set (px only)"

        # cached info meta
        self._info_meta: dict | None = None

    # ---------------- public API ----------------

    def set_scale_display(self, text: str) -> None:
        self._scale_text = text
        self._refresh_info_block()

    def show_file(self, path_str: str) -> None:
        path = Path(path_str)

        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
        self._reader = None
        self._video_path = None
        self._is_video = False
        self._current_frame_index = 0

        if is_video_file(path):
            self._is_video = True
            self._video_path = path
            self._video_row.setVisible(True)

            try:
                self._reader = VideoReader(path)
                meta = self._reader.meta

                self._setting_slider = True
                try:
                    max_i = max(0, (meta.frame_count - 1)) if meta.frame_count > 0 else 0
                    self._slider.setMinimum(0)
                    self._slider.setMaximum(max_i)
                    self._slider.setValue(0)
                finally:
                    self._setting_slider = False

                frame_rgb = self._reader.get_frame(0)
                self._current_frame_index = 0
                self._set_before_and_after(frame_rgb)
                self._ensure_roi_for_image(frame_rgb.shape[0], frame_rgb.shape[1])
                self._update_video_labels(0)

                dur = meta.duration_s
                dur_txt = f"{dur:.2f} s" if dur is not None else "n/a"

                self._info_meta = {
                    "path": str(path),
                    "type": "video",
                    "size": f"{meta.width}×{meta.height}px",
                    "fps": f"{meta.fps:.3f}",
                    "frames": f"{meta.frame_count}",
                    "duration": dur_txt,
                    "current": "frame0",
                }
                self._refresh_info_block()

            except Exception as e:
                self._clear_views()
                self._video_row.setVisible(False)
                self._info.setText(f"{path}\n\nVIDEO: chyba načtení\n{e!r}")
            return

        self._video_row.setVisible(False)

        # --- SPM file: load via AFMReader, normalize for display ---
        if str(path).lower().endswith(".spm"):
            try:
                import logging
                _log = logging.getLogger(__name__)

                from barakuda.devices.afm.io.afmreader_loader import load_spm_height
                height_img, meta = load_spm_height(str(path))

                _log.info(
                    "SPM loaded via AFMReader | channel=%s | shape=%s | pixel_to_nm=%s | loader=%s",
                    meta.get("selected_channel", "?"),
                    meta.get("shape", "?"),
                    meta.get("pixel_to_nm", "?"),
                    meta.get("loader", "?"),
                )

                # Percentile normalization for preview display
                finite = height_img[np.isfinite(height_img)]
                if len(finite) > 0:
                    p1, p99 = np.percentile(finite, [1, 99])
                else:
                    p1, p99 = 0.0, 1.0
                norm = (height_img - p1) / (p99 - p1 + 1e-9)
                norm = np.clip(norm, 0.0, 1.0)
                preview_uint8 = (norm * 255.0).astype(np.uint8)
                arr = np.stack([preview_uint8] * 3, axis=-1)  # grayscale RGB

                self._current_frame_index = 0
                self._set_before_and_after(arr)
                self._ensure_roi_for_image(arr.shape[0], arr.shape[1])

                self._info_meta = {
                    "path": str(path),
                    "type": "spm",
                    "shape": f"{arr.shape}, dtype={height_img.dtype}",
                    "channel": str(meta.get("selected_channel", "?")),
                    "pixel_to_nm": str(meta.get("pixel_to_nm", "?")),
                    "loader": str(meta.get("loader", "?")),
                }
                self._refresh_info_block()
                return
            except Exception as e:
                self._clear_views()
                self._info.setText(f"{path}\n\nSPM: chyba načtení\n{e!r}")
                return

        # --- Standard image file: load via Qt QImage ---
        arr = self._load_image_qt(path)
        if arr is None:
            self._clear_views()
            self._info.setText(f"{path}\n\nNelze zobrazit jako obrázek (Qt QImage to nenačetl).")
            return

        self._current_frame_index = 0
        self._set_before_and_after(arr)
        self._ensure_roi_for_image(arr.shape[0], arr.shape[1])

        self._info_meta = {
            "path": str(path),
            "type": "image",
            "shape": f"{arr.shape}, dtype={arr.dtype}",
        }
        self._refresh_info_block()

    def set_after_image(self, arr: np.ndarray) -> None:
        self._after_locked = True
        self._view_after.setImage(np.asarray(arr), autoLevels=True)

    def set_after_from_file(self, path_str: str) -> bool:
        """Load an image via Qt and show it on AFTER tab.

        Returns True on success. Never throws.
        """
        try:
            arr = self._load_image_qt(Path(path_str))
            if arr is None:
                return False
            self.set_after_image(arr)
            self.show_after_tab()
            return True
        except Exception:
            return False

    def unlock_after(self) -> None:
        self._after_locked = False

    def show_after_tab(self) -> None:
        try:
            self._tabs.setCurrentIndex(1)
        except Exception:
            pass

    def get_before_image(self) -> np.ndarray | None:
        return self._last_before

    def get_current_frame_index(self) -> int:
        return int(self._current_frame_index)

    def set_frame_index(self, i: int) -> None:
        if self._reader is None or not self._is_video:
            return

        i = int(i)
        self._setting_slider = True
        try:
            i = max(self._slider.minimum(), min(self._slider.maximum(), i))
            self._slider.setValue(i)
        finally:
            self._setting_slider = False

        self._on_slider_changed(i)

    def get_video_frame_count(self) -> int | None:
        if self._reader is None:
            return None
        return int(self._reader.meta.frame_count)

    def get_video_fps(self) -> float | None:
        if self._reader is None:
            return None
        return float(self._reader.meta.fps)

    def get_roi_rect(self) -> tuple[int, int, int, int] | None:
        if self._roi is None or self._roi_shape is None:
            return None

        h, w = self._roi_shape
        # NOTE: pg.RectROI pos() is usually in the coordinate system of its parent 
        # (which is the ViewBox or ImageItem). But to be perfectly safe, we map it
        # to the image item's coordinate system.
        
        # pg.ImageView has .getImageItem() exposing the image coords natively
        img_item = self._view_before.getImageItem()
        # map rect from ROI local (bounds) to ImageItem local
        mapped_rect = img_item.mapRectFromItem(self._roi, self._roi.boundingRect())
        
        x = int(round(float(mapped_rect.x())))
        y = int(round(float(mapped_rect.y())))
        rw = int(round(float(mapped_rect.width())))
        rh = int(round(float(mapped_rect.height())))

        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        rw = max(1, min(rw, w - x))
        rh = max(1, min(rh, h - y))

        return (x, y, rw, rh)

    # ---------------- slider ----------------

    def _on_slider_changed(self, value: int) -> None:
        if self._setting_slider:
            return
        if not self._is_video or self._reader is None:
            return

        try:
            i = int(value)
            frame_rgb = self._reader.get_frame(i)

            self._current_frame_index = i
            self._last_before = frame_rgb
            self._view_before.setImage(frame_rgb, autoLevels=True)

            self._ensure_roi_for_image(frame_rgb.shape[0], frame_rgb.shape[1])
            self._update_video_labels(i)

            if isinstance(self._info_meta, dict):
                self._info_meta["current"] = f"frame{i}"
                self._refresh_info_block()

        except Exception as e:
            self._info.setText(f"{self._video_path}\n\nVIDEO: chyba při čtení snímku\n{e!r}")

    # ---------------- internal UI helpers ----------------

    def _refresh_info_block(self) -> None:
        meta = self._info_meta
        if not isinstance(meta, dict):
            self._info.setText(self._scale_text)
            return

        lines = []
        lines.append(str(meta.get("path", "")))
        lines.append(f"type={meta.get('type', 'n/a')}")
        if meta.get("type") == "video":
            lines.append(f"size={meta.get('size', 'n/a')}")
            lines.append(f"fps={meta.get('fps', 'n/a')}")
            lines.append(f"frames={meta.get('frames', 'n/a')}")
            lines.append(f"duration={meta.get('duration', 'n/a')}")
            lines.append(f"current={meta.get('current', 'n/a')}")
        elif meta.get("type") == "spm":
            lines.append(f"shape={meta.get('shape', 'n/a')}")
            lines.append(f"channel={meta.get('channel', 'n/a')}")
            lines.append(f"pixel_to_nm={meta.get('pixel_to_nm', 'n/a')}")
            lines.append(f"loader={meta.get('loader', 'n/a')}")
        else:
            lines.append(f"shape={meta.get('shape', 'n/a')}")

        # ALWAYS show scale at bottom, except for SPM where it's native to the device panel
        if meta.get("type") != "spm":
            lines.append(self._scale_text)

        roi = self.get_roi_rect()
        if roi is not None:
            lines.append(f"ROI: x={roi[0]}, y={roi[1]}, w={roi[2]}, h={roi[3]}")

        self._info.setText("\n".join(lines))

    def _update_video_labels(self, i: int) -> None:
        if self._reader is None:
            self._frame_label.setText("frame: -/-   t: -")
            return
        meta = self._reader.meta
        total = max(1, int(meta.frame_count))
        fps = float(meta.fps) if meta.fps and meta.fps > 0 else 1.0
        t = float(i) / fps
        self._frame_label.setText(f"frame: {i}/{total-1}   t: {t:.3f} s")

    def _set_before_and_after(self, arr: np.ndarray) -> None:
        arr = np.asarray(arr)
        self._last_before = arr
        self._view_before.setImage(arr, autoLevels=True)
        if not self._after_locked:
            self._view_after.setImage(arr, autoLevels=True)

    def _ensure_roi_for_image(self, H: int, W: int) -> None:
        """
        Create ROI once and ensure it stays inside image bounds.
        IMPORTANT: Add 4 corner scale handles so ROI is easy to reshape.
        """
        if self._roi is None:
            # Yellow ROI frame
            pen = pg.mkPen((255, 255, 0), width=2)

            self._roi = pg.RectROI([W * 0.25, H * 0.25], [W * 0.5, H * 0.5], pen=pen)

            # Remove default single handle behavior and add explicit corner handles
            # Four corners:
            # (pos, center)
            self._roi.addScaleHandle([0, 0], [1, 1])  # top-left
            self._roi.addScaleHandle([1, 0], [0, 1])  # top-right
            self._roi.addScaleHandle([0, 1], [1, 0])  # bottom-left
            self._roi.addScaleHandle([1, 1], [0, 0])  # bottom-right

            # Optional: side handles (more convenient for thin rectangles)
            self._roi.addScaleHandle([0.5, 0], [0.5, 1])  # top
            self._roi.addScaleHandle([0.5, 1], [0.5, 0])  # bottom
            self._roi.addScaleHandle([0, 0.5], [1, 0.5])  # left
            self._roi.addScaleHandle([1, 0.5], [0, 0.5])  # right

            self._view_before.addItem(self._roi)
            self._roi.sigRegionChanged.connect(self._on_roi_changed)

        self._roi_shape = (int(H), int(W))
        self._clamp_roi_to_image()

    def _on_roi_changed(self) -> None:
        self._clamp_roi_to_image()
        # Refresh info block to display live ROI coordinates
        self._refresh_info_block()

    def _clamp_roi_to_image(self) -> None:
        if self._roi is None or self._roi_shape is None or self._clamping_roi:
            return
        h, w = self._roi_shape
        pos = self._roi.pos()
        size = self._roi.size()

        x = float(pos.x())
        y = float(pos.y())
        rw = float(size.x())
        rh = float(size.y())

        changed = False
        if rw < 5:
            rw = 5.0
            changed = True
        if rh < 5:
            rh = 5.0
            changed = True

        if x < 0:
            x = 0.0
            changed = True
        if y < 0:
            y = 0.0
            changed = True

        if x + rw > w:
            x = max(0.0, float(w) - rw)
            changed = True
        if y + rh > h:
            y = max(0.0, float(h) - rh)
            changed = True

        if changed:
            self._clamping_roi = True
            try:
                self._roi.setPos([x, y], update=True)
                self._roi.setSize([rw, rh], update=True)
            finally:
                self._clamping_roi = False

    def _clear_views(self) -> None:
        self._last_before = None
        self._after_locked = False
        self._view_before.clear()
        self._view_after.clear()

    def _load_image_qt(self, path: Path) -> np.ndarray | None:
        img = QImage(str(path))
        if img.isNull():
            return None

        # Convert to RGB888 (standard 3-channel, 8-bit per channel)
        img = img.convertToFormat(QImage.Format.Format_RGB888)
        
        w = img.width()
        h = img.height()
        
        # IMPORTANT: QImage rows are 32-bit aligned. 
        # bytesPerLine() gives the true stride (width in bytes including padding).
        bpl = img.bytesPerLine()

        ptr = img.bits()
        ptr.setsize(h * bpl)
        
        # 1) View as 1D uint8 array of size (h * bpl)
        # 2) Reshape to (h, bpl) to handle rows
        arr_padded = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl))
        
        # 3) Crop the valid data width (w * 3 bytes for RGB888)
        #    and reshape to (h, w, 3)
        valid_bytes = w * 3
        arr = arr_padded[:, :valid_bytes].reshape((h, w, 3))
        
        # 4) Make a deep copy to detach from QImage memory
        return arr.copy()
