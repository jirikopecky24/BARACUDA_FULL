from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter, QLabel, QComboBox,
    QSizePolicy, QPushButton
)

from barakuda.shell.widgets.dataset_panel import DatasetPanel
from barakuda.shell.widgets.preview_panel import PreviewPanel
from barakuda.shell.widgets.log_panel import LogPanel
from barakuda.devices.registry import list_devices
from barakuda.devices.base import DeviceSpec
from barakuda.shell.batch_controller import BatchController
from barakuda.core.video_io import is_video_file
from barakuda.core.calibration_store import save_dataset_scale


class ShellMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("BARAKUDA Analysis Suite — Modular")
        self.resize(1400, 860)

        self.dataset = DatasetPanel()
        self.preview = PreviewPanel()
        self.log_panel = LogPanel()

        self.dataset.item_selected.connect(self._on_item_selected)

        self._devices: list[DeviceSpec] = list_devices()
        self._active_device: Optional[DeviceSpec] = None
        self._active_device_id: str = ""
        self._device_panel: Optional[QWidget] = None

        runs_folder = Path(__file__).resolve().parents[2] / "runs"
        self.batch = BatchController(runs_folder=runs_folder, log_fn=self.log_panel.log)

        header = QWidget()
        h_layout = QVBoxLayout(header)
        h_layout.setContentsMargins(8, 8, 8, 0)

        top_row = QWidget()
        top_layout = QVBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("BARAKUDA Analysis Suite")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        subtitle = QLabel("Audit-first • Deterministic • Batch-ready")
        subtitle.setStyleSheet("color: #666;")

        self.device_combo = QComboBox()
        for d in self._devices:
            self.device_combo.addItem(d.display_name, d.device_id)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)

        self.btn_preview_gate = QPushButton("Preview Gate (mandatory)")
        self.btn_run_batch = QPushButton("Run Batch")
        self.btn_run_batch.setEnabled(False)

        self.btn_preview_gate.clicked.connect(self._on_preview_gate)
        self.btn_run_batch.clicked.connect(self._on_run_batch)

        top_layout.addWidget(title)
        top_layout.addWidget(subtitle)
        top_layout.addWidget(QLabel("Device / Modality:"))
        top_layout.addWidget(self.device_combo)
        top_layout.addWidget(self.btn_preview_gate)
        top_layout.addWidget(self.btn_run_batch)

        h_layout.addWidget(top_row)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.main_split = QSplitter(Qt.Orientation.Horizontal)
        self.main_split.addWidget(self.dataset)
        self.main_split.addWidget(self.preview)

        self._device_container = QWidget()
        self._device_container_layout = QVBoxLayout(self._device_container)
        self._device_container_layout.setContentsMargins(0, 0, 0, 0)
        self.main_split.addWidget(self._device_container)

        self.main_split.setStretchFactor(0, 1)
        self.main_split.setStretchFactor(1, 3)
        self.main_split.setStretchFactor(2, 1)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.addWidget(self.main_split)
        vertical.addWidget(self.log_panel)
        vertical.setStretchFactor(0, 6)
        vertical.setStretchFactor(1, 1)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(header)
        root_layout.addWidget(vertical, 1)
        self.setCentralWidget(root)

        self.log_panel.log("Shell started.")
        self._set_device_by_index(0)

    # ---------------- dataset -> preview ----------------

    def _on_item_selected(self, path: Path) -> None:
        self.log_panel.log(f"Selected: {path}")
        try:
            self.preview.show_file(str(path))
            self.log_panel.log("Preview: video loaded." if is_video_file(path) else "Preview: file loaded.")
        except Exception as e:
            self.log_panel.log(f"Preview ERROR: {e!r}")

        self.batch.reset_gate()
        self.btn_run_batch.setEnabled(False)

    # ---------------- device switching ----------------

    def _on_device_changed(self, idx: int) -> None:
        self._set_device_by_index(idx)

    def _set_device_by_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._devices):
            return
        self._activate_device(self._devices[idx])
        self.batch.reset_gate()
        self.btn_run_batch.setEnabled(False)

    def _activate_device(self, spec: DeviceSpec) -> None:
        if self._device_panel is not None:
            self._device_panel.setParent(None)
            self._device_panel.deleteLater()
            self._device_panel = None

        self._active_device = spec
        self._active_device_id = str(spec.device_id)
        self._device_panel = spec.create_panel()
        self._device_container_layout.addWidget(self._device_panel)

        # Option A: Shell owns batch → schovej panelové batch/run tlačítka
        try:
            if hasattr(self._device_panel, "btn_run_batch"):
                self._device_panel.btn_run_batch.setEnabled(False)  # type: ignore[attr-defined]
                self._device_panel.btn_run_batch.hide()             # type: ignore[attr-defined]
            if hasattr(self._device_panel, "btn_run_selected"):
                self._device_panel.btn_run_selected.hide()          # type: ignore[attr-defined]
        except Exception:
            pass

        # ALE: Track Video + Save scale musí fungovat → napojíme signály
        if self._active_device_id == "optical_tweezers":
            try:
                self._device_panel.track_range_clicked.connect(self._ot_track_range)          # type: ignore[attr-defined]
                self._device_panel.save_dataset_scale_clicked.connect(self._ot_save_scale)    # type: ignore[attr-defined]
            except Exception as e:
                self.log_panel.log(f"WARN: OT panel signals not wired: {e!r}")

        self.log_panel.log(f"Device selected: {spec.display_name}")

    # ---------------- OT helpers ----------------

    def _ot_save_scale(self) -> None:
        if self._device_panel is None:
            return
        sel = self.dataset.get_selected_paths()
        if not sel:
            self.log_panel.log("Save scale: no selected file.")
            return

        p = sel[0]
        try:
            scale_params = self._device_panel.get_scale_params()  # type: ignore[attr-defined]
            um = float(scale_params.get("um_per_px", 0.0))
            if um <= 0:
                self.log_panel.log("Save scale: um/px must be > 0.")
                return

            info = save_dataset_scale(p, um)
            txt = f"Scale: {info.um_per_px:.6f} µm/px (dataset)"
            self.preview.set_scale_display(txt)
            self._device_panel.set_scale_status(txt)  # type: ignore[attr-defined]
            self.log_panel.log(f"Saved dataset scale: {p.name} -> {info.um_per_px:.6f} µm/px")
        except Exception as e:
            self.log_panel.log(f"Save scale ERROR: {e!r}")

    def _ot_track_range(self) -> None:
        # “Track Video (range)” uděláme jako single-run přes batch engine (1 file):
        if self._device_panel is None:
            return
        sel = self.dataset.get_selected_paths()
        if not sel:
            self.log_panel.log("Track range: no selected video.")
            return
        roi = self.preview.get_roi_rect()
        if roi is None:
            self.log_panel.log("Track range: ROI is not set.")
            return

        # Aby to bylo audit-first, uděláme nejdřív mini gate na aktuálním frame:
        frame_idx = int(self.preview.get_current_frame_index() or 0)
        self.batch.run_preview_gate(
            file_paths=[sel[0]],
            device_id="optical_tweezers",
            device_panel=self._device_panel,
            preview_roi_rect=roi,
            preview_frame_index=frame_idx,
        )
        if not self.batch.preview_done:
            self.log_panel.log("Track range blocked: Preview Gate for this file FAILED.")
            return

        def progress_fn(done: int, total: int) -> None:
            self.log_panel.log(f"Track progress: {done}/{total}")

        try:
            self.batch.run_batch(
                device_id="optical_tweezers",
                device_panel=self._device_panel,
                roi_rect=roi,
                dataset_set_status_fn=self.dataset.set_status,
                progress_fn=progress_fn,
            )
        except Exception as e:
            self.log_panel.log(f"Track range ERROR: {e!r}")

    # ---------------- preview gate ----------------

    def _on_preview_gate(self) -> None:
        paths = self.dataset.get_selected_paths()
        if not paths:
            self.log_panel.log("Preview Gate: no selected files.")
            return
        if self._device_panel is None:
            self.log_panel.log("Preview Gate: no active panel.")
            return

        roi = self.preview.get_roi_rect()
        frame_idx = int(self.preview.get_current_frame_index() or 0)

        self.log_panel.log(f"Preview Gate: using preview frame index={frame_idx}")
        if roi is None and self._active_device_id == "optical_tweezers":
            self.log_panel.log("Preview Gate: ROI is required for Optical Tweezers.")

        self.batch.run_preview_gate(
            file_paths=paths,
            device_id=self._active_device_id,
            device_panel=self._device_panel,
            preview_roi_rect=roi,
            preview_frame_index=frame_idx,
        )

        self.btn_run_batch.setEnabled(self.batch.preview_done)

    # ---------------- run batch ----------------

    def _on_run_batch(self) -> None:
        if not self.batch.preview_done:
            self.log_panel.log("Run Batch blocked: Preview Gate has not passed.")
            return
        if self._device_panel is None:
            self.log_panel.log("Run Batch: no active panel.")
            return

        roi = self.preview.get_roi_rect()
        if roi is None and self._active_device_id == "optical_tweezers":
            self.log_panel.log("Run Batch: ROI is required for Optical Tweezers.")
            return

        self.btn_preview_gate.setEnabled(False)
        self.btn_run_batch.setEnabled(False)

        try:
            if hasattr(self._device_panel, "set_batch_running"):
                self._device_panel.set_batch_running(True)  # type: ignore[attr-defined]

            def progress_fn(done: int, total: int) -> None:
                self.log_panel.log(f"Batch progress: {done}/{total}")

            self.batch.run_batch(
                device_id=self._active_device_id,
                device_panel=self._device_panel,
                roi_rect=roi if roi is not None else (0, 0, 0, 0),
                dataset_set_status_fn=self.dataset.set_status,
                progress_fn=progress_fn,
            )
        except Exception as e:
            self.log_panel.log(f"Run Batch ERROR: {e!r}")
        finally:
            try:
                if hasattr(self._device_panel, "set_batch_running"):
                    self._device_panel.set_batch_running(False)  # type: ignore[attr-defined]
            except Exception:
                pass
            self.btn_preview_gate.setEnabled(True)
            self.btn_run_batch.setEnabled(self.batch.preview_done)
