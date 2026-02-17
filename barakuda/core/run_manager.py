from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import numpy as np
from PyQt6.QtGui import QImage, QColor, QPainter, QPen


@dataclass(frozen=True)
class RunResult:
    run_id: str
    run_dir: Path


class RunManager:
    def __init__(self, runs_folder: Path) -> None:
        self.runs_folder = Path(runs_folder)
        self.runs_folder.mkdir(parents=True, exist_ok=True)

    def create_run(self, input_path: Path, config: Dict[str, Any]) -> RunResult:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + input_path.stem
        run_dir = self.runs_folder / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "run_id": run_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "input_path": str(input_path),
            "config": config,
        }
        (run_dir / "run.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return RunResult(run_id=run_id, run_dir=run_dir)

    def save_after_png(self, run_dir: Path, arr: np.ndarray, name: str = "after_raw.png") -> Path:
        """Raw frame (no overlays)."""
        out = Path(run_dir) / name
        self._save_png_qimage(out, arr)
        return out

    def save_json(self, run_dir: Path, name: str, payload: Dict[str, Any]) -> Path:
        out = Path(run_dir) / name
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    def save_overlay_png(
        self,
        run_dir: Path,
        frame_rgb: np.ndarray,
        x: float,
        y: float,
        roi: tuple[int, int, int, int] | None = None,
        name: str = "preview_tracking.png",
    ) -> Path:
        """RGB frame + ROI rectangle + red crosshair at (x,y)."""
        out = Path(run_dir) / name
        img = self._to_qimage_rgb(frame_rgb)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # ROI rectangle (gold)
        if roi is not None:
            rx, ry, rw, rh = roi
            pen = QPen(QColor(255, 215, 0, 200), 2)
            painter.setPen(pen)
            painter.drawRect(rx, ry, rw, rh)

        # Red crosshair
        pen = QPen(QColor(255, 0, 0, 220), 2)
        painter.setPen(pen)
        cx, cy = int(round(x)), int(round(y))
        painter.drawLine(cx - 10, cy, cx + 10, cy)
        painter.drawLine(cx, cy - 10, cx, cy + 10)

        painter.end()
        img.save(str(out))
        return out

    # -------- internal helpers --------
    def _save_png_qimage(self, path: Path, arr: np.ndarray) -> None:
        img = self._to_qimage(arr)
        img.save(str(path))

    def _to_qimage(self, arr: np.ndarray) -> QImage:
        arr = np.asarray(arr)
        if arr.ndim == 2:
            h, w = arr.shape
            a = np.clip(arr, 0, 255).astype(np.uint8, copy=False)
            img = QImage(a.data, w, h, w, QImage.Format.Format_Grayscale8)
            return img.copy()

        if arr.ndim == 3 and arr.shape[2] >= 3:
            return self._to_qimage_rgb(arr[..., :3])

        raise ValueError(f"Unsupported array shape for QImage: {arr.shape}")

    def _to_qimage_rgb(self, frame_rgb: np.ndarray) -> QImage:
        """
        Robust numpy (H,W,3) uint8 -> QImage without stride artifacts.
        """
        arr = np.asarray(frame_rgb)

        if arr.ndim == 2:
            # grayscale -> RGB
            arr = np.stack([arr, arr, arr], axis=-1)

        if arr.dtype != np.uint8:
            # normalize safely into uint8 if needed
            a = arr.astype(np.float32)
            a -= np.nanmin(a)
            mx = np.nanmax(a)
            if mx > 0:
                a /= mx
            arr = (np.clip(a, 0, 1) * 255.0).astype(np.uint8)

        # Ensure contiguous memory (CRITICAL)
        arr = np.ascontiguousarray(arr)

        h, w, c = arr.shape
        if c != 3:
            # fallback: take first 3 channels
            arr = arr[:, :, :3]
            arr = np.ascontiguousarray(arr)
            h, w, c = arr.shape

        bytes_per_line = 3 * w  # CRITICAL: correct stride

        qimg = QImage(arr.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

        # Detach from numpy buffer (prevents random artifacts after arr goes out of scope)
        return qimg.copy()
