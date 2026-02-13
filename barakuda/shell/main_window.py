from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter, QLabel, QComboBox,
    QSizePolicy, QPushButton, QToolButton, QHBoxLayout, QDockWidget
)

from barakuda.shell.widgets.dataset_panel import DatasetPanel
from barakuda.shell.widgets.preview_panel import PreviewPanel
from barakuda.shell.widgets.log_panel import LogPanel
from barakuda.devices.registry import list_devices
from barakuda.devices.base import DeviceSpec
from barakuda.shell.batch_controller import BatchController
from barakuda.core.video_io import is_video_file
from barakuda.core.calibration_store import save_dataset_scale
from barakuda.core.calibration_store import load_dataset_scale


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
        h_layout.setSpacing(6)

        # Compact top bar (always visible)
        topbar = QWidget()
        topbar_l = QHBoxLayout(topbar)
        topbar_l.setContentsMargins(0, 0, 0, 0)
        topbar_l.setSpacing(8)

        title = QLabel("BARAKUDA Analysis Suite")
        title.setStyleSheet("font-size: 14px; font-weight: 700;")

        self.btn_toggle_controls = QToolButton()
        self.btn_toggle_controls.setCheckable(True)
        self.btn_toggle_controls.setChecked(False)
        self.btn_toggle_controls.setText("▸ Controls")

        def _sync_controls_text(checked: bool) -> None:
            self.btn_toggle_controls.setText("▾ Controls" if checked else "▸ Controls")

        self.btn_toggle_controls.toggled.connect(_sync_controls_text)

        topbar_l.addWidget(title)
        topbar_l.addStretch(1)
        topbar_l.addWidget(self.btn_toggle_controls)

        # Controls panel (collapsible)
        self.controls = QWidget()
        c = QHBoxLayout(self.controls)
        c.setContentsMargins(0, 0, 0, 0)
        c.setSpacing(8)

        self.device_combo = QComboBox()
        for d in self._devices:
            self.device_combo.addItem(d.display_name, d.device_id)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)

        self.method_combo = QComboBox()
        self.method_combo.setVisible(False)

        self.btn_run = QPushButton("RUN")
        self.btn_run.setFixedHeight(28)

        # Keep controls compact
        for w in [self.device_combo, self.method_combo]:
            try:
                w.setFixedHeight(26)
            except Exception:
                pass

        self.btn_run.clicked.connect(self._on_run_batch)

        c.addWidget(QLabel("Device:"))
        c.addWidget(self.device_combo, 1)
        c.addWidget(QLabel("Analysis mode:"))
        c.addWidget(self.method_combo, 0)
        c.addWidget(self.btn_run, 0)
        c.addStretch(1)

        self.controls.setVisible(False)
        self.btn_toggle_controls.toggled.connect(self.controls.setVisible)

        h_layout.addWidget(topbar)
        h_layout.addWidget(self.controls)
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.setMaximumHeight(40)

        self._device_container = QWidget()
        self._device_container_layout = QVBoxLayout(self._device_container)
        self._device_container_layout.setContentsMargins(0, 0, 0, 0)

        # ---------------- Central (header + preview) ----------------
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(header)
        root_layout.addWidget(self.preview, 1)
        self.setCentralWidget(root)

        # ---------------- Dock widgets (Dataset / Pipeline / Log) ----------------
        self.dataset_dock = QDockWidget("Dataset", self)
        self.dataset_dock.setWidget(self.dataset)
        self.dataset_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self.pipeline_dock = QDockWidget("Pipeline", self)
        self.pipeline_dock.setWidget(self._device_container)
        self.pipeline_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self.log_dock = QDockWidget("Log", self)
        self.log_dock.setWidget(self.log_panel)
        self.log_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dataset_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.pipeline_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)

        # Reasonable default proportions (can be adjusted by user)
        try:
            self.resizeDocks([self.dataset_dock, self.pipeline_dock], [300, 360], Qt.Orientation.Horizontal)
            self.resizeDocks([self.log_dock], [180], Qt.Orientation.Vertical)
        except Exception:
            pass

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

        # Auto-set OT end-frame to last frame of the loaded video (frame_count - 1).
        if self._active_device_id == "optical_tweezers" and self._device_panel is not None:
            try:
                fc = self.preview.get_video_frame_count()
                if fc is not None and fc > 0 and hasattr(self._device_panel, "set_end_frame"):
                    self._device_panel.set_end_frame(int(fc - 1))  # type: ignore[attr-defined]
            except Exception as e:
                self.log_panel.log(f"WARN: end-frame autoload failed: {e!r}")

        self.batch.reset_gate()

        # Keep OT scale visible + deterministic default.
        if self._active_device_id == "optical_tweezers" and self._device_panel is not None:
            try:
                info = load_dataset_scale(path)
                if info is not None and info.um_per_px is not None:
                    um = float(info.um_per_px)
                    txt = f"Scale: {um:.6f} µm/px (dataset)"
                    self.preview.set_scale_display(txt)
                    self._device_panel.set_um_per_px(um)      # type: ignore[attr-defined]
                    self._device_panel.set_scale_status(txt)   # type: ignore[attr-defined]
                else:
                    # Default OT scale (user requirement) for convenience; saved scale still wins.
                    um = 0.066528
                    txt = f"Scale: {um:.6f} µm/px (px default)"
                    self.preview.set_scale_display(txt)
                    self._device_panel.set_um_per_px(um)      # type: ignore[attr-defined]
                    self._device_panel.set_scale_status(txt)   # type: ignore[attr-defined]
            except Exception as e:
                self.log_panel.log(f"WARN: scale load failed: {e!r}")

    # ---------------- device switching ----------------

    def _on_device_changed(self, idx: int) -> None:
        self._set_device_by_index(idx)

    def _set_device_by_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._devices):
            return
        self._activate_device(self._devices[idx])
        self.batch.reset_gate()

    def _activate_device(self, spec: DeviceSpec) -> None:
        if self._device_panel is not None:
            self._device_panel.setParent(None)
            self._device_panel.deleteLater()
            self._device_panel = None

        self._active_device = spec
        self._active_device_id = str(spec.device_id)
        self._device_panel = spec.create_panel()
        self._device_container_layout.addWidget(self._device_panel)

        # ALE: Track Video + Save scale musí fungovat → napojíme signály
        if self._active_device_id == "optical_tweezers":
            try:
                self._device_panel.track_range_clicked.connect(self._ot_track_range)          # type: ignore[attr-defined]
                self._device_panel.save_dataset_scale_clicked.connect(self._ot_save_scale)    # type: ignore[attr-defined]
            except Exception as e:
                self.log_panel.log(f"WARN: OT panel signals not wired: {e!r}")

        self.log_panel.log(f"Device selected: {spec.display_name}")

        # Top-bar method selector (device-specific)
        if self._active_device_id == "optical_tweezers":
            self.method_combo.blockSignals(True)
            try:
                self.method_combo.clear()
                self.method_combo.addItem("RADIAL_SYMMETRY", "RADIAL_SYMMETRY")
                self.method_combo.addItem("INTENSITY_PEAK", "INTENSITY_PEAK")
                self.method_combo.setCurrentIndex(0)
                self.method_combo.setVisible(True)

                # push into device panel (so batch reads it from get_tracking_params)
                if hasattr(self._device_panel, "set_tracking_method"):
                    self._device_panel.set_tracking_method("RADIAL_SYMMETRY")  # type: ignore[attr-defined]

                def _on_method_changed(_idx: int) -> None:
                    mid = str(self.method_combo.currentData())
                    if hasattr(self._device_panel, "set_tracking_method"):
                        self._device_panel.set_tracking_method(mid)  # type: ignore[attr-defined]

                # avoid duplicate connections
                try:
                    self.method_combo.currentIndexChanged.disconnect()
                except Exception:
                    pass
                self.method_combo.currentIndexChanged.connect(_on_method_changed)

            finally:
                self.method_combo.blockSignals(False)
        else:
            self.method_combo.setVisible(False)

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

            # UI convenience: show the produced AFTER overlay for the selected video.
            try:
                runs_folder = self.batch.run_manager.runs_folder
                stem = sel[0].stem
                candidates = sorted(
                    (p for p in runs_folder.glob(f"*-{stem}") if p.is_dir()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    after_path = candidates[0] / f"{stem}_after.png"
                    if after_path.exists():
                        ok = self.preview.set_after_from_file(str(after_path))
                        if ok:
                            self.log_panel.log(f"AFTER overlay shown: {after_path}")
            except Exception:
                pass
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

        pass  # preview gate result is logged

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

        self.btn_run.setEnabled(False)

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
            self.btn_run.setEnabled(True)
