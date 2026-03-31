from __future__ import annotations

from pathlib import Path
from typing import Optional
import re

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QComboBox,
    QHBoxLayout, QDockWidget, QStackedWidget, QSplitter, QSizePolicy
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
from barakuda.shell.widgets.preview_gate_report_dialog import PreviewGateReportDialog
from barakuda.shell.widgets.run_protocol_dialog import RunProtocolDialog


class ShellMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("BARAKUDA Analysis Suite — Modular")
        self.resize(1400, 860)
        self.setMinimumSize(1280, 700)
        self._set_window_icon_if_available()

        self.dataset = DatasetPanel()
        self._afm_preview = PreviewPanel(device_kind="AFM")
        self._ot_preview = PreviewPanel(device_kind="OT")
        self.log_panel = LogPanel()

        self.dataset.item_selected.connect(self._on_item_selected)

        self._devices: list[DeviceSpec] = list_devices()
        self._active_device: Optional[DeviceSpec] = None
        self._active_device_id: str = ""
        self._device_panel: Optional[QWidget] = None

        # Per-device preview thread/worker (never shared)
        self._afm_preview_thread = None
        self._afm_preview_worker = None
        self._afm_preview_job_id = 0  # monotonic counter for job-id gating

        # AFM RUN thread/worker (separate from preview)
        self._afm_run_thread = None
        self._afm_run_worker = None

        # OT RUN thread/worker
        self._ot_run_thread = None
        self._ot_run_worker = None
        # Track per-item completion for progressive OT overlay updates.
        self._ot_last_done_seen: int = -1
        self._ot_overlay_last_applied_done: int = -1

        runs_folder = Path(__file__).resolve().parents[2] / "runs"
        self.batch = BatchController(runs_folder=runs_folder, log_fn=self.log_panel.log)

        self._device_container = QWidget()
        self._device_container_layout = QVBoxLayout(self._device_container)
        self._device_container_layout.setContentsMargins(0, 0, 0, 0)

        # ---------------- Central (stacked preview panels) ----------------
        self._preview_stack = QStackedWidget()
        self._preview_stack.addWidget(self._afm_preview)
        self._preview_stack.addWidget(self._ot_preview)
        self._preview_stack.setCurrentWidget(self._afm_preview)
        self._preview_stack.setMinimumWidth(520)
        self._preview_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Right-hand panel (device container with PipelinePanel / AFM panel)
        # should behave similarly to the Dataset dock: never collapse below
        # a comfortable minimum width so that labels and controls remain readable.
        self._device_container.setMinimumWidth(470)
        self._device_container.setMaximumWidth(760)
        self._device_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self._center_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._center_splitter.addWidget(self._preview_stack)
        self._center_splitter.addWidget(self._device_container)
        self._center_splitter.setStretchFactor(0, 3)
        self._center_splitter.setStretchFactor(1, 2)
        self._center_splitter.setChildrenCollapsible(False)
        # Do not allow the right panel to be collapsed to 0px.
        try:
            self._center_splitter.setCollapsible(0, False)
            self._center_splitter.setCollapsible(1, False)
        except Exception:
            # Older Qt versions may not support setCollapsible; safe to ignore.
            pass
        self.setCentralWidget(self._center_splitter)

        # ---------------- Method dock (above Dataset) ----------------
        method_widget = QWidget()
        ml = QHBoxLayout(method_widget)
        ml.setContentsMargins(8, 6, 8, 6)
        ml.setSpacing(8)

        self.device_combo = QComboBox()
        self.device_combo.setToolTip("Select the active BARAKUDA module.")
        for d in self._devices:
            self.device_combo.addItem(d.display_name, d.device_id)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)

        self.method_combo = QComboBox()
        self.method_combo.setToolTip("Select the analysis method available for the current module.")
        self.method_combo.setVisible(False)

        self.method_label = QLabel("Method:")
        self.method_label.setVisible(False)

        ml.addWidget(QLabel("Device:"))
        ml.addWidget(self.device_combo, 1)
        ml.addWidget(self.method_label)
        ml.addWidget(self.method_combo, 0)

        self.method_dock = QDockWidget("", self)
        self.method_dock.setWidget(method_widget)
        self.method_dock.setTitleBarWidget(QWidget())  # no title bar
        self.method_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        # ---------------- Dock widgets (Dataset / Pipeline / Log) ----------------
        self.dataset_dock = QDockWidget("Dataset", self)
        self.dataset_dock.setWidget(self.dataset)
        self.dataset.setMinimumWidth(260)
        self.dataset_dock.setMinimumWidth(280)
        self.dataset_dock.setFeatures(
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

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.method_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dataset_dock)
        self.splitDockWidget(self.method_dock, self.dataset_dock, Qt.Orientation.Vertical)

        # Heartbeat ticker
        self._tick_counter = 0
        self._tick_label = QLabel("Tick: 0")
        self.statusBar().addPermanentWidget(self._tick_label)
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(250)
        
        self._first_show = True
        self._manual_roi_edited_paths = set()
        self._last_ot_bead_diameter_um: Optional[float] = None
        self._last_non_acq_splitter_sizes: Optional[list[int]] = None
        self._last_dataset_dock_width: int = 300

    def _remember_non_acq_splitter_sizes(self) -> None:
        """Persist user-adjusted center splitter widths for OT/AFM view."""
        try:
            sizes = [int(v) for v in self._center_splitter.sizes()]
        except Exception:
            return
        if len(sizes) != 2:
            return
        if sizes[0] <= 0 or sizes[1] <= 0:
            return
        self._last_non_acq_splitter_sizes = sizes

    def _restore_non_acq_splitter_sizes(self) -> None:
        """Restore previous OT/AFM splitter widths, fallback to proportional default."""
        try:
            remembered = self._last_non_acq_splitter_sizes
            if remembered and len(remembered) == 2 and remembered[0] > 0 and remembered[1] > 0:
                self._center_splitter.setSizes(remembered)
                return

            total = int(self._center_splitter.width())
            if total <= 0:
                total = 1400
            right_min = max(380, int(self._device_container.minimumWidth() or 0))
            right = max(right_min, int(total * 0.36))
            left = max(320, total - right)
            self._center_splitter.setSizes([left, right])
        except Exception:
            pass

    def _remember_dataset_dock_width(self) -> None:
        try:
            w = int(self.dataset_dock.width())
        except Exception:
            return
        if w > 120:
            self._last_dataset_dock_width = w

    def _restore_dataset_dock_width(self) -> None:
        try:
            target = max(280, int(self._last_dataset_dock_width))
            self.resizeDocks([self.dataset_dock], [target], Qt.Orientation.Horizontal)
        except Exception:
            pass

    def _set_window_icon_if_available(self) -> None:
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "branding" / "barakuda" / "app_icon.png"
        if not icon_path.is_file():
            return
        try:
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                self.setWindowIcon(icon)
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        
        if self._first_show:
            self._first_show = False
            # Ensure method dock stays visible above Dataset (avoid collapsing to ~0px).
            try:
                self.method_dock.setMinimumHeight(48)
                self.method_dock.setMaximumHeight(80)
                self.resizeDocks(
                    [self.method_dock, self.dataset_dock],
                    [60, 600],
                    Qt.Orientation.Vertical,
                )
            except Exception:
                pass


            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)

            # Reasonable default proportions (can be adjusted by user)
            try:
                self.resizeDocks([self.dataset_dock], [200], Qt.Orientation.Horizontal)
                self.resizeDocks([self.log_dock], [180], Qt.Orientation.Vertical)
                self._restore_non_acq_splitter_sizes()
            except Exception:
                pass

            self.log_panel.log("Shell started.")
            self._set_device_by_index(0)

    def _on_tick(self) -> None:
        self._tick_counter += 1
        self._tick_label.setText(f"Tick: {self._tick_counter}")

    def _on_open_protocol_editor(self) -> None:
        selected = self.dataset.get_selected_paths()
        run_folder: Path | None = None
        if selected:
            p = selected[0]
            if p.is_dir():
                run_folder = p
            elif p.name.lower() == "run_protocol.json":
                run_folder = p.parent
            else:
                run_folder = p.parent
        dlg = RunProtocolDialog(run_folder=run_folder, parent=self)
        dlg.exec()

    # -- active preview routing (per-device) --

    @property
    def preview(self) -> PreviewPanel:
        """Return the preview panel for the currently active device."""
        if self._active_device_id == "afm":
            return self._afm_preview
        return self._ot_preview

    # ---------------- dataset -> preview ----------------

    def _on_item_selected(self, path: Path) -> None:
        self.log_panel.log(f"Selected: {path}")

        # OT dataset inputs: resolve item.json / item root / item video for all downstream use
        # (scale loading, end-frame, params key). PreviewPanel handles the same resolution too.
        _ot_resolved_path = path
        _afm_resolved_path = path
        _afm_manifest_params = None
        if self._active_device_id == "optical_tweezers":
            try:
                from barakuda.devices.optical_tweezers.manifest import resolve_ot_input_path
                _resolved = resolve_ot_input_path(path)
                if _resolved.video_path is not None:
                    _ot_resolved_path = _resolved.video_path
                    self.log_panel.log(
                        f"Dataset input resolved: {_resolved.video_path.name}"
                    )
            except Exception as _e:
                self.log_panel.log(f"WARN: dataset input resolve failed: {_e!r}")
        elif self._active_device_id == "afm":
            try:
                from barakuda.devices.afm.manifest import load_item_manifest, resolve_afm_input_path

                _resolved = resolve_afm_input_path(path)
                if _resolved.image_path is not None:
                    _afm_resolved_path = _resolved.image_path
                    self.log_panel.log(
                        f"Dataset input resolved: {_resolved.image_path.name}"
                    )
                _afm_manifest_params = None
                if _resolved.item_json_path is not None and _resolved.item_json_path.exists():
                    try:
                        _afm_manifest = load_item_manifest(_resolved.item_json_path)
                        _afm_manifest_params = ((_afm_manifest.raw.get("afm") or {}).get("params"))
                    except Exception:
                        _afm_manifest_params = None
            except Exception as _e:
                self.log_panel.log(f"WARN: AFM dataset input resolve failed: {_e!r}")
                _afm_manifest_params = None

        try:
            self.preview.show_file(str(path))
            active_preview_path = _ot_resolved_path if self._active_device_id == "optical_tweezers" else _afm_resolved_path
            self.log_panel.log("Preview: video loaded." if is_video_file(active_preview_path) else "Preview: file loaded.")
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
                
            try:
                if hasattr(self._device_panel, "is_auto_roi_on_load") and self._device_panel.is_auto_roi_on_load():
                    if str(path) not in getattr(self, "_manual_roi_edited_paths", set()):
                        QTimer.singleShot(200, self._on_auto_roi)
            except Exception as e:
                self.log_panel.log(f"WARN: auto ROI failed: {e!r}")

        self.batch.reset_gate()

        # Keep OT scale visible + deterministic default.
        if self._active_device_id == "optical_tweezers" and self._device_panel is not None:
            try:
                info = load_dataset_scale(_ot_resolved_path)
                if info is not None and info.um_per_px is not None:
                    um = float(info.um_per_px)
                    txt = f"Scale: {um:.6f} µm/px (dataset)"
                    self.preview.set_scale_display(txt)
                    self._device_panel.set_um_per_px(um)      # type: ignore[attr-defined]
                    self._device_panel.set_scale_status(txt)   # type: ignore[attr-defined]
                    if info.stage_um_per_unit is not None:
                        self._device_panel.set_stage_um_per_unit(info.stage_um_per_unit)  # type: ignore[attr-defined]
                else:
                    # Default OT scale (user requirement) for convenience; saved scale still wins.
                    um = 0.060420
                    txt = f"Scale: {um:.6f} µm/px (px default)"
                    self.preview.set_scale_display(txt)
                    self._device_panel.set_um_per_px(um)      # type: ignore[attr-defined]
                    self._device_panel.set_scale_status(txt)   # type: ignore[attr-defined]
            except Exception as e:
                self.log_panel.log(f"WARN: scale load failed: {e!r}")

        # Auto-load AFM scale/metadata into panel on selection to avoid "unknown"
        if self._active_device_id == "afm" and self._device_panel is not None:
            # Disarm auto-preview on new dataset item (re-armed on first manual Preview)
            if hasattr(self._device_panel, "disarm_auto_preview"):
                self._device_panel.disarm_auto_preview()  # type: ignore[attr-defined]
            if str(_afm_resolved_path).lower().endswith(".spm"):
                try:
                    from barakuda.devices.afm.io.afmreader_loader import load_spm_height
                    _, loader_meta = load_spm_height(str(_afm_resolved_path))
                    if hasattr(self._device_panel, "update_loader_info"):
                        self._device_panel.update_loader_info(loader_meta)  # type: ignore[attr-defined]
                except Exception as e:
                    self.log_panel.log(f"WARN: AFM scale auto-load failed: {e!r}")
            if hasattr(self._device_panel, "load_afm_params") and hasattr(self._device_panel, "get_afm_params"):
                try:
                    pms = self.dataset.get_item_params(path)
                    if pms is not None:
                        self._device_panel.load_afm_params(pms)  # type: ignore[attr-defined]
                    elif _afm_manifest_params is not None:
                        self._device_panel.load_afm_params(_afm_manifest_params)  # type: ignore[attr-defined]
                        self.dataset.set_item_params(path, _afm_manifest_params)
                    else:
                        self.dataset.set_item_params(path, self._device_panel.get_afm_params())  # type: ignore[attr-defined]
                    self._sync_afm_method_selector_from_panel()
                except Exception as e:
                    self.log_panel.log(f"WARN: AFM per-item load failed: {e!r}")

        # OT: Load per-video parameters if available, else save current as defaults for this video
        if self._active_device_id == "optical_tweezers" and self._device_panel is not None:
            if hasattr(self._device_panel, "load_ot_params") and hasattr(self._device_panel, "dump_ot_params"):
                try:
                    pms = self.dataset.get_item_params(path)
                    if pms is not None:
                        self._device_panel.load_ot_params(pms)
                    else:
                        # First time clicking this video: snapshot current UI as its params
                        self.dataset.set_item_params(path, self._device_panel.dump_ot_params())
                except Exception as e:
                    self.log_panel.log(f"WARN: OT per-video load failed: {e!r}")
            self._sync_ot_bead_diameter_state()

    def _on_ot_panel_value_changed(self) -> None:
        """When an OT control changes, save the new params to the currently active dataset item."""
        if self._active_device_id != "optical_tweezers" or self._device_panel is None:
            return
            
        paths = self.dataset.get_selected_paths()
        if not paths:
            return
            
        # We only save to the single actively previewed item (the first selected)
        active_path = paths[0]
        try:
            pms = self._device_panel.dump_ot_params()
            self.dataset.set_item_params(active_path, pms)
        except Exception as e:
            self.log_panel.log(f"WARN: Failed to save OT params to dataset item: {e!r}")

        current_bead_diameter = self._get_current_ot_bead_diameter_um()
        previous_bead_diameter = self._last_ot_bead_diameter_um
        self._last_ot_bead_diameter_um = current_bead_diameter
        if (
            current_bead_diameter is not None
            and previous_bead_diameter is not None
            and abs(current_bead_diameter - previous_bead_diameter) > 1e-9
            and self._ot_preview.get_before_image() is not None
        ):
            self.log_panel.log(
                f"Auto ROI: bead diameter changed to {current_bead_diameter:.3f} µm, recalculating."
            )
            self._on_auto_roi()

    def _on_afm_panel_value_changed(self) -> None:
        if self._active_device_id != "afm" or self._device_panel is None:
            return

        paths = self.dataset.get_selected_paths()
        if not paths:
            return

        active_path = paths[0]
        try:
            params = self._device_panel.get_afm_params()
            self.dataset.set_item_params(active_path, params)
        except Exception as e:
            self.log_panel.log(f"WARN: Failed to save AFM params to dataset item: {e!r}")

    # ---------------- device switching ----------------

    def _on_device_changed(self, idx: int) -> None:
        self._set_device_by_index(idx)

    def _set_device_by_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._devices):
            return
        self._activate_device(self._devices[idx])
        self.batch.reset_gate()

    def _activate_device(self, spec: DeviceSpec) -> None:
        previous_device_id = self._active_device_id
        if self._active_device_id != "acquisition":
            self._remember_non_acq_splitter_sizes()
            self._remember_dataset_dock_width()

        if self._device_panel is not None:
            self._device_panel.setParent(None)
            self._device_panel.deleteLater()
            self._device_panel = None

        self._active_device = spec
        self._active_device_id = str(spec.device_id)
        self._device_panel = spec.create_panel()
        self._device_container_layout.addWidget(self._device_panel)

        if self._active_device_id == "optical_tweezers":
            try:
                self._device_panel.preview_gate_clicked.connect(self._on_preview_gate)    # type: ignore[attr-defined]
                self._device_panel.gate_report_clicked.connect(self._on_preview_gate_report) # type: ignore[attr-defined]
                self._device_panel.run_batch_clicked.connect(self._on_run_batch)           # type: ignore[attr-defined]
                self._device_panel.stop_clicked.connect(self.batch.stop)                   # type: ignore[attr-defined]
                self._device_panel.save_dataset_scale_clicked.connect(self._ot_save_scale) # type: ignore[attr-defined]
                if hasattr(self._device_panel, "open_protocol_clicked"):
                    self._device_panel.open_protocol_clicked.connect(self._on_open_protocol_editor)
                
                if hasattr(self._device_panel, "value_changed"):
                    self._device_panel.value_changed.connect(self._on_ot_panel_value_changed)
                    
                if hasattr(self._device_panel, "auto_roi_clicked"):
                    self._device_panel.auto_roi_clicked.connect(self._on_auto_roi)
                    
                if hasattr(self._device_panel, "load_profile_requested"):
                    self._device_panel.load_profile_requested.connect(self._on_ot_load_profile)
                    self._device_panel.save_profile_requested.connect(self._on_ot_save_profile)
                    
                try:
                    self._ot_preview.roi_changed.disconnect()
                except Exception:
                    pass
                self._ot_preview.roi_changed.connect(self._on_manual_roi_edit)
                
                # Fetch profiles and populate UI
                self._update_ot_profile_list()
                self._sync_ot_bead_diameter_state()
            except Exception as e:
                self.log_panel.log(f"WARN: OT panel signals not wired: {e!r}")

        elif self._active_device_id == "afm":
            try:
                # Wire the Run button from AfmPanel
                if hasattr(self._device_panel, "run_batch_clicked"):
                    self._device_panel.run_batch_clicked.connect(self._on_run_batch)  # type: ignore[attr-defined]
                if hasattr(self._device_panel, "btn_preview"):
                    self._device_panel.btn_preview.clicked.connect(self._on_afm_preview)  # type: ignore[attr-defined]
                if hasattr(self._device_panel, "btn_cancel"):
                    self._device_panel.btn_cancel.clicked.connect(self._on_afm_preview_cancel_clicked)  # type: ignore[attr-defined]
                if hasattr(self._device_panel, "auto_preview_requested"):
                    self._device_panel.auto_preview_requested.connect(self._on_afm_preview)  # type: ignore[attr-defined]
                if hasattr(self._device_panel, "value_changed"):
                    self._device_panel.value_changed.connect(self._on_afm_panel_value_changed)  # type: ignore[attr-defined]
            except Exception as e:
                self.log_panel.log(f"WARN: AFM panel signals not wired: {e!r}")

        elif self._active_device_id == "acquisition":
            # AcquisitionPanel is self-contained (owns its preview).
            # Wire log function so recording lifecycle events reach the Log panel.
            if hasattr(self._device_panel, "set_log_fn"):
                self._device_panel.set_log_fn(self.log_panel.log)  # type: ignore[union-attr]

        self.log_panel.log(f"Device selected: {spec.display_name}")

        # Switch the preview stack to the correct panel
        # Acquisition has its own built-in preview — hide the shared one
        if self._active_device_id == "acquisition":
            # Acquisition owns its own preview+controls layout.
            # Collapse shared preview pane to avoid a large empty left area.
            self._preview_stack.setMinimumWidth(0)
            self._device_container.setMinimumWidth(860)
            self._device_container.setMaximumWidth(16777215)
            self._preview_stack.hide()
            self.dataset_dock.hide()
            try:
                total = max(1, int(self._center_splitter.width()))
                self._center_splitter.setSizes([0, total])
            except Exception:
                pass
        else:
            self._preview_stack.setMinimumWidth(320)
            self._device_container.setMinimumWidth(470)
            self._device_container.setMaximumWidth(760)
            self._preview_stack.show()
            self.dataset_dock.show()
            if previous_device_id == "acquisition":
                QTimer.singleShot(0, self._restore_dataset_dock_width)
                QTimer.singleShot(0, self._restore_non_acq_splitter_sizes)
            if self._active_device_id == "afm":
                self._preview_stack.setCurrentWidget(self._afm_preview)
            else:
                self._preview_stack.setCurrentWidget(self._ot_preview)

        # Top-bar method selector (device-specific)
        try:
            self.method_combo.currentIndexChanged.disconnect()
        except Exception:
            pass

        if self._active_device_id == "optical_tweezers":
            self.method_combo.blockSignals(True)
            try:
                self.method_combo.clear()
                self.method_combo.addItem("Brownian (PSD)", "Brownian")
                self.method_combo.addItem("Drag (Stage)", "Drag")
                self.method_combo.addItem("Microrheology (Coming later)", "Rheology")

                # Per-method tooltips (shown in dropdown when hovering)
                self.method_combo.setItemData(
                    0,
                    "Brownian (PSD): passive calibration from the Brownian motion power spectral density.",
                    Qt.ItemDataRole.ToolTipRole,
                )
                self.method_combo.setItemData(
                    1,
                    "Drag (Stage): calibration from stage-driven drag of the trapped bead at constant velocity.",
                    Qt.ItemDataRole.ToolTipRole,
                )
                self.method_combo.setItemData(
                    2,
                    "Microrheology: planned module for frequency-dependent viscoelastic measurements.",
                    Qt.ItemDataRole.ToolTipRole,
                )
                
                # Disable the rheology item
                self._set_method_combo_item_enabled(self.method_combo.count() - 1, False)
                        
                self.method_combo.setCurrentIndex(0)
                self.method_combo.setVisible(True)
                
                self.method_label.setText("Method:")
                self.method_label.setVisible(True)

                if hasattr(self._device_panel, "set_calibration_mode"):
                    self._device_panel.set_calibration_mode("Brownian")

                def _on_method_changed(_idx: int) -> None:
                    mid = str(self.method_combo.currentData())
                    if hasattr(self._device_panel, "set_calibration_mode"):
                        self._device_panel.set_calibration_mode(mid)
                self.method_combo.currentIndexChanged.connect(_on_method_changed)

            finally:
                self.method_combo.blockSignals(False)
        elif self._active_device_id == "afm":
            self.method_combo.blockSignals(True)
            try:
                self.method_combo.clear()
                methods = []
                if hasattr(self._device_panel, "available_afm_methods"):
                    methods = list(self._device_panel.available_afm_methods())  # type: ignore[attr-defined]
                if not methods:
                    methods = [("Rod Bacteria (Cellpose + Rod Fit)", "rod_bacteria", True)]

                for label, method_id, _enabled in methods:
                    self.method_combo.addItem(label, method_id)
                for idx, (_label, _method_id, enabled) in enumerate(methods):
                    self._set_method_combo_item_enabled(idx, enabled)

                self.method_label.setText("Method:")
                self.method_label.setVisible(True)
                self.method_combo.setVisible(True)

                current_method = "rod_bacteria"
                if hasattr(self._device_panel, "get_afm_method"):
                    current_method = str(self._device_panel.get_afm_method())  # type: ignore[attr-defined]
                method_index = self.method_combo.findData(current_method)
                self.method_combo.setCurrentIndex(method_index if method_index >= 0 else 0)

                def _on_afm_method_changed(_idx: int) -> None:
                    method_id = str(self.method_combo.currentData() or "rod_bacteria")
                    if hasattr(self._device_panel, "set_afm_method"):
                        self._device_panel.set_afm_method(method_id)  # type: ignore[attr-defined]

                self.method_combo.currentIndexChanged.connect(_on_afm_method_changed)
            finally:
                self.method_combo.blockSignals(False)
        else:
            self.method_combo.setVisible(False)
            self.method_label.setVisible(False)

    def _on_manual_roi_edit(self) -> None:
        if self._active_device_id == "optical_tweezers" and self._device_panel is not None:
            if hasattr(self._device_panel, "_adaptive_roi"):
                self._device_panel._adaptive_roi.setChecked(False)
        paths = self.dataset.get_selected_paths()
        if paths:
            if not hasattr(self, "_manual_roi_edited_paths"):
                self._manual_roi_edited_paths = set()
            self._manual_roi_edited_paths.add(str(paths[0]))

    def _get_current_ot_bead_diameter_um(self) -> Optional[float]:
        if self._active_device_id != "optical_tweezers" or self._device_panel is None:
            return None
        try:
            if hasattr(self._device_panel, "get_postprocess_params"):
                return float(self._device_panel.get_postprocess_params().get("bead_diameter_um", 1.0))
        except Exception:
            pass
        try:
            if hasattr(self._device_panel, "_bead_diameter_um"):
                return float(self._device_panel._bead_diameter_um.value())
        except Exception:
            pass
        return None

    def _sync_ot_bead_diameter_state(self) -> None:
        self._last_ot_bead_diameter_um = self._get_current_ot_bead_diameter_um()

    def _set_method_combo_item_enabled(self, index: int, enabled: bool) -> None:
        model = self.method_combo.model()
        if hasattr(model, "item"):
            item = model.item(index)
            if item:
                item.setEnabled(enabled)

    def _sync_afm_method_selector_from_panel(self) -> None:
        if self._active_device_id != "afm" or self._device_panel is None:
            return
        if not hasattr(self._device_panel, "get_afm_method"):
            return
        method_id = str(self._device_panel.get_afm_method())  # type: ignore[attr-defined]
        idx = self.method_combo.findData(method_id)
        if idx < 0:
            return
        was_blocked = self.method_combo.blockSignals(True)
        try:
            self.method_combo.setCurrentIndex(idx)
        finally:
            self.method_combo.blockSignals(was_blocked)

    # ---------------- OT helpers ----------------

    def _on_ot_load_profile(self, profile_name: str) -> None:
        """Minimal handler to satisfy signal wiring without modifying profile logic."""
        self.log_panel.log(f"OT load profile requested: {profile_name} (No-op)")

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

            stage_raw = scale_params.get("stage_um_per_unit", 0.0)
            stage_um_per_unit: float | None = float(stage_raw) if float(stage_raw) > 0 else None

            info = save_dataset_scale(p, um, stage_um_per_unit=stage_um_per_unit)
            txt = f"Scale: {info.um_per_px:.6f} µm/px (dataset)"
            self.preview.set_scale_display(txt)
            self._device_panel.set_scale_status(txt)  # type: ignore[attr-defined]
            stage_log = f", stage: {stage_um_per_unit:.4f} µm/unit" if stage_um_per_unit else ""
            self.log_panel.log(
                f"Saved dataset scale: {p.name} -> {info.um_per_px:.6f} µm/px{stage_log}"
            )
        except Exception as e:
            self.log_panel.log(f"Save scale ERROR: {e!r}")

    def _on_auto_roi(self) -> None:
        if self._active_device_id != "optical_tweezers" or self._device_panel is None:
            return

        paths = self.dataset.get_selected_paths()
        if paths:
            if hasattr(self, "_manual_roi_edited_paths"):
                self._manual_roi_edited_paths.discard(str(paths[0]))

        frame = self._ot_preview.get_before_image()
        if frame is None:
            self.log_panel.log("Auto ROI: No image loaded.")
            return

        from barakuda.devices.optical_tweezers.pipeline.auto_roi import auto_roi_rs
        
        try:
            scale_params = self._device_panel.get_scale_params()
            um_per_px = float(scale_params.get("um_per_px", 0.0))

            dia = 1.0
            if hasattr(self._device_panel, "get_postprocess_params"):
                dia = float(self._device_panel.get_postprocess_params().get("bead_diameter_um", 1.0))
            elif hasattr(self._device_panel, "_bead_diameter_um"):
                dia = float(self._device_panel._bead_diameter_um.value())

            margin = 1.8
            if hasattr(self._device_panel, "get_tracking_params"):
                margin = float(self._device_panel.get_tracking_params().get("roi_margin", 1.8))
            elif hasattr(self._device_panel, "_roi_margin"):
                margin = float(self._device_panel._roi_margin.value())

            rx, ry, rw, rh = auto_roi_rs(frame, um_per_px, dia, margin_factor=margin)
            self._ot_preview.set_roi_rect(rx, ry, rw, rh)
            self.log_panel.log(f"Auto ROI: Found particle at x={rx}, y={ry}")
            
            if hasattr(self._device_panel, "_adaptive_roi"):
                self._device_panel._adaptive_roi.setChecked(True)
            self._skip_adaptive_first_frame = True
        except Exception as e:
            self.log_panel.log(f"Auto ROI ERROR: {e!r}")

    # ---------------- OT profile management ----------------

    def _update_ot_profile_list(self) -> None:
        """Populate the profile combo in the OT panel from disk."""
        if self._device_panel is None:
            return
        try:
            from barakuda.devices.optical_tweezers.profile.profile_store import list_profiles
            profiles = list_profiles()
            if hasattr(self._device_panel, "update_profile_list"):
                self._device_panel.update_profile_list(profiles)  # type: ignore[attr-defined]
        except Exception as e:
            self.log_panel.log(f"WARN: OT profile list refresh failed: {e!r}")

    def _on_ot_load_profile(self, name: str) -> None:
        """Load a named OT profile from disk and apply it to the panel."""
        if self._device_panel is None:
            return
        try:
            from barakuda.devices.optical_tweezers.profile.profile_store import load_profile
            data = load_profile(name)
            if not data:
                self.log_panel.log(f"OT profile '{name}': not found or empty.")
                return
            params = data.get("defaults", data)
            if hasattr(self._device_panel, "load_ot_params"):
                self._device_panel.load_ot_params(params)  # type: ignore[attr-defined]
            self.log_panel.log(f"OT profile loaded: {name}")
        except Exception as e:
            self.log_panel.log(f"OT profile load ERROR: {e!r}")

    def _on_ot_save_profile(self, name: str) -> None:
        """Save current OT panel params to a named profile on disk."""
        if self._device_panel is None:
            return
        try:
            from barakuda.devices.optical_tweezers.profile.profile_store import save_profile
            if not hasattr(self._device_panel, "dump_ot_params"):
                return
            params = self._device_panel.dump_ot_params()  # type: ignore[attr-defined]
            save_profile(name, {"defaults": params})
            self.log_panel.log(f"OT profile saved: {name}")
            self._update_ot_profile_list()
        except Exception as e:
            self.log_panel.log(f"OT profile save ERROR: {e!r}")

    # ---------------- preview gate ----------------

    def _on_preview_gate(self) -> None:
        if self._active_device_id == "afm":
            paths = self.dataset.get_selected_paths()
        else:
            paths = self.dataset.get_checked_paths()
        if not paths:
            self.log_panel.log("Preview Gate: no selected files.")
            return
        if self._device_panel is None:
            self.log_panel.log("Preview Gate: no active panel.")
            return

        roi = self.preview.get_roi_rect()
        frame_idx = int(self.preview.get_current_frame_index() or 0)

        # Read gate policy from the panel
        gate_policy = "STRICT"
        try:
            if hasattr(self._device_panel, 'get_gate_policy'):
                gate_policy = self._device_panel.get_gate_policy()  # type: ignore[attr-defined]
        except Exception:
            pass

        self.log_panel.log(f"Preview Gate policy: {gate_policy}")
        self.log_panel.log(f"Preview Gate: using preview frame index={frame_idx}")
        if roi is None and self._active_device_id == "optical_tweezers":
            self.log_panel.log("Preview Gate: ROI is required for Optical Tweezers.")
            return

        # Mark selected items as "running" while gating
        for p in paths:
            self.dataset.set_status(p, "running")

        results = self.batch.run_preview_gate(
            file_paths=paths,
            device_id=self._active_device_id,
            device_panel=self._device_panel,
            preview_roi_rect=roi,
            preview_frame_index=frame_idx,
            gate_policy=gate_policy,
        )

        # Per-file PASS/FAIL -> Dataset icons
        failed: list[str] = []
        passed: list[str] = []

        for r in results:
            p = Path(r.path)
            if r.ok:
                self.dataset.set_status(p, "done")     # ✅
                passed.append(p.name)
                self.log_panel.log(f"Preview Gate PASS: {p.name}")
            else:
                self.dataset.set_status(p, "failed")   # ❌
                failed.append(p.name)
                # message already contains reason
                self.log_panel.log(f"Preview Gate FAIL: {p.name} — {r.message}")

        if failed:
            self.log_panel.log(f"Preview Gate summary: FAIL ({len(failed)}): " + ", ".join(failed))
        else:
            self.log_panel.log(f"Preview Gate summary: ALL PASS ({len(passed)})")

        # Enable RUN only if gate passed for all
        if hasattr(self._device_panel, 'btn_run'):
            self._device_panel.btn_run.setEnabled(self.batch.preview_done)  # type: ignore[attr-defined]
        # Enable Report button
        if hasattr(self._device_panel, 'btn_gate_report'):
            self._device_panel.btn_gate_report.setEnabled(True)  # type: ignore[attr-defined]

    # ---------------- preview gate report ----------------

    def _on_preview_gate_report(self) -> None:
        results = []
        try:
            results = self.batch.get_preview_gate_results()
        except Exception:
            results = getattr(self.batch, "_last_preview_results", [])

        report_path = None
        try:
            report_path = self.batch.get_preview_gate_report_path()
        except Exception:
            pass

        if not results:
            self.log_panel.log("Preview Gate Report: no results available.")
            return

        dlg = PreviewGateReportDialog(results=results, report_path=report_path, parent=self)
        dlg.exec()

    # ---------------- run batch ----------------

    def _on_run_batch(self) -> None:
        self.log_panel.log(f"RUN pressed for device: {self._active_device_id}")

        if self._active_device_id == "afm":
            # Guard: if RUN thread is already running, ignore
            if self._afm_run_thread is not None:
                try:
                    if self._afm_run_thread.isRunning():
                        self.log_panel.log("AFM RUN: already running, ignoring.")
                        return
                except RuntimeError:
                    pass
                self._afm_run_thread = None

            roi = self.preview.get_roi_rect()
            if roi is None:
                self.log_panel.log("AFM RUN: ROI is required.")
                return

            paths = self.dataset.get_selected_paths()
            if not paths:
                self.log_panel.log("AFM RUN: no selected files.")
                return

            params = {}
            try:
                params = self._device_panel.get_afm_params()  # type: ignore[attr-defined]
            except Exception:
                pass

            self.log_panel.log(f"AFM RUN: START | {len(paths)} file(s) | roi={roi}")

            # Set UI state
            if hasattr(self._device_panel, 'set_run_state'):
                self._device_panel.set_run_state(True)  # type: ignore[attr-defined]

            from PyQt6.QtCore import QThread, QTimer
            from barakuda.shell.workers.afm_run_worker import AfmRunWorker

            self._afm_run_thread = QThread()
            self._afm_run_worker = AfmRunWorker(
                batch_controller=self.batch,
                file_paths=paths,
                roi_rect=roi,
                afm_params=params,
                dataset_set_status_fn=self.dataset.set_status,
            )
            self._afm_run_worker.moveToThread(self._afm_run_thread)

            self._afm_run_thread.started.connect(self._afm_run_worker.run)

            self._afm_run_worker.progress_pct.connect(self._handle_afm_run_progress)
            self._afm_run_worker.finished.connect(self._afm_run_done)
            self._afm_run_worker.error.connect(self._afm_run_failed)

            # cleanup wiring
            self._afm_run_worker.finished.connect(self._afm_run_thread.quit)
            self._afm_run_worker.error.connect(self._afm_run_thread.quit)
            self._afm_run_thread.finished.connect(self._afm_run_worker.deleteLater)
            self._afm_run_thread.finished.connect(self._cleanup_afm_run_thread)

            # Smooth timer for 20->79% during inference
            if not hasattr(self, '_afm_run_timer'):
                self._afm_run_timer = QTimer(self)
                self._afm_run_timer.timeout.connect(self._afm_run_on_timer)
            self._afm_run_progress_val = 0
            self._afm_run_timer.start(500)

            self._afm_run_thread.start()
            return
        if not self.batch.preview_done:
            # Optical Tweezers require Preview Gate PASS (hard rule).
            # AFM does NOT use Preview Gate.
            if self._active_device_id == "optical_tweezers":
                self.log_panel.log("Run Batch blocked: Preview Gate has not passed.")
                return
        if self._device_panel is None:
            self.log_panel.log("Run Batch: no active panel.")
            return

        if self._active_device_id == "optical_tweezers":
            if getattr(self, "_ot_run_thread", None) is not None:
                try:
                    if self._ot_run_thread.isRunning():
                        self.log_panel.log("OT RUN: already running, ignoring.")
                        return
                except RuntimeError:
                    pass
                self._ot_run_thread = None

        roi = self.preview.get_roi_rect()
        if roi is None and self._active_device_id in ("optical_tweezers", "afm"):
            self.log_panel.log("Run Batch: ROI is required.")
            return

        # disable RUN on the panel if it exists
        if hasattr(self._device_panel, 'btn_run'):
            self._device_panel.btn_run.setEnabled(False)  # type: ignore[attr-defined]

        if self._active_device_id == "optical_tweezers":
            from PyQt6.QtCore import QThread
            from barakuda.shell.workers.ot_run_worker import OTRunWorker

            panel_data = {
                "tracking": self._device_panel.get_tracking_params(),
                "postprocess": self._device_panel.get_postprocess_params(),
                "scale": self._device_panel.get_scale_params(),
                "frame_range": self._device_panel.get_frame_range(),
                "run_output_root": (
                    self._device_panel.get_run_output_root()
                    if hasattr(self._device_panel, "get_run_output_root")
                    else ""
                ),
            }

            # Collect all per-video params from the dataset panel
            dataset_params = {}
            for p in self.dataset.get_all_items():
                pms = self.dataset.get_item_params(p["path"])
                if pms is not None:
                    dataset_params[p["path"]] = pms

            self._ot_run_thread = QThread()
            self._ot_run_worker = OTRunWorker(
                batch_controller=self.batch,
                checked_paths=self.dataset.get_checked_paths(),
                roi_rect=roi if roi is not None else (0, 0, 0, 0),
                panel_data=panel_data,
                dataset_params=dataset_params,
            )
            self._ot_run_worker.moveToThread(self._ot_run_thread)
            self._ot_run_thread.started.connect(self._ot_run_worker.run)

            # Route signals to UI updates
            def _on_ot_prog(pct: int, msg: str):
                self.log_panel.log(f"OT batch progress: {pct}% {msg}")
                if hasattr(self._device_panel, "set_batch_progress"):
                    self._device_panel.set_batch_progress(0, 100, msg, pct)

                # Progressive preview: update overlay only after an OT item
                # fully completes (i.e. when the "done index" increments).
                # This avoids updating on per-frame progress where done index
                # has not yet advanced.
                if "RUN: [" not in msg:
                    return
                m = re.search(r"\bRUN:\s*\[(\d+)/(\d+)\]", msg)
                if not m:
                    return
                try:
                    done_idx = int(m.group(1))
                except Exception:
                    return

                prev_done_idx = self._ot_last_done_seen
                completion = "(100%)" in msg

                if done_idx <= prev_done_idx:
                    return

                # done_idx increased -> this is the end-of-item progress_fn call.
                self._ot_last_done_seen = done_idx

                if not completion or done_idx <= self._ot_overlay_last_applied_done:
                    return

                overlay_video_path = getattr(self.batch, "last_ot_overlay_video_path", None)
                overlay_trajectory_path = getattr(self.batch, "last_ot_overlay_trajectory_path", None)
                if not overlay_video_path or not overlay_trajectory_path:
                    return

                try:
                    self._ot_preview.set_ot_live_overlay(
                        overlay_trajectory_path,
                        video_path=overlay_video_path,
                    )
                    self._ot_overlay_last_applied_done = done_idx
                except Exception:
                    # Preview updates should never crash the batch run.
                    pass
            self._ot_run_worker.progress_pct.connect(_on_ot_prog)
            self._ot_run_worker.log_msg.connect(self.log_panel.log)
            self._ot_run_worker.status_update.connect(self.dataset.set_status)

            def _on_ot_done():
                if hasattr(self._device_panel, 'btn_run'):
                    self._device_panel.btn_run.setEnabled(True)
                overlay_video_path = getattr(self.batch, "last_ot_overlay_video_path", None)
                overlay_trajectory_path = getattr(self.batch, "last_ot_overlay_trajectory_path", None)
                if overlay_video_path and overlay_trajectory_path:
                    try:
                        self._ot_preview.set_ot_live_overlay(
                            overlay_trajectory_path,
                            video_path=overlay_video_path,
                        )
                    except Exception:
                        pass
                self._ot_run_thread.quit()

            def _on_ot_err(err: str):
                self.log_panel.log(f"OT RUN ERROR: {err}")
                if hasattr(self._device_panel, 'btn_run'):
                    self._device_panel.btn_run.setEnabled(True)
                self._ot_run_thread.quit()

            self._ot_run_worker.finished.connect(_on_ot_done)
            self._ot_run_worker.error.connect(_on_ot_err)

            self._ot_run_thread.finished.connect(self._ot_run_worker.deleteLater)
            self._ot_run_thread.finished.connect(lambda: setattr(self, "_ot_run_thread", None))

            self._ot_run_thread.start()

    def _on_afm_preview(self) -> None:
        if self._active_device_id != "afm" or self._device_panel is None:
            return

        if self._afm_preview_worker:
            self._afm_preview_worker.cancel()

        thread = self._afm_preview_thread
        if thread is not None:
            try:
                if thread.isRunning():
                    self.log_panel.log("AFM Preview: superseding running preview (auto-preview).")
                    # Don't block — old worker will finish and be discarded via job_id gating
                thread.quit()
                thread.wait(200)  # wait briefly, don't block UI
                thread.deleteLater()
            except RuntimeError:
                pass
            self._afm_preview_thread = None

        from PyQt6.QtCore import QThread
        from barakuda.shell.workers.afm_preview_worker import AfmPreviewWorker

        paths = self.dataset.get_selected_paths()
        if not paths:
            self.log_panel.log("AFM Preview: no file selected.")
            return

        file_path = str(paths[0])

        # Get params from panel
        afm_params: dict = {}
        if hasattr(self._device_panel, "get_afm_params"):
            afm_params = self._device_panel.get_afm_params()  # type: ignore[attr-defined]

        # ROI fallback
        roi = self.preview.get_roi_rect()
        if roi is None or roi[2] < 2 or roi[3] < 2:
            img_size = None
            try:
                img_size = self.preview.get_image_size()
            except Exception:
                pass
            if img_size and img_size[0] > 0 and img_size[1] > 0:
                roi = (0, 0, int(img_size[0]), int(img_size[1]))
            else:
                roi = (0, 0, 512, 512)
            self.log_panel.log(f"Preview AFM: ROI not set → using full frame {roi[2]}×{roi[3]}")

        self.log_panel.log(f"Preview AFM: START | file={paths[0].name} | roi={roi}")

        # Arm auto-preview after first manual Preview click
        if hasattr(self._device_panel, "arm_auto_preview"):
            self._device_panel.arm_auto_preview()  # type: ignore[attr-defined]
        
        # update UI state
        if hasattr(self._device_panel, "set_preview_state"):
            self._device_panel.set_preview_state(True)  # type: ignore[attr-defined]

        # Start thread
        self._afm_preview_thread = QThread()
        self._afm_preview_thread.finished.connect(self._cleanup_afm_preview_thread)
        self._afm_preview_worker = AfmPreviewWorker(file_path, roi, afm_params)
        self._afm_preview_worker.moveToThread(self._afm_preview_thread)

        # Job-id gating: tag this worker so callbacks can discard stale results
        self._afm_preview_job_id += 1
        current_job_id = self._afm_preview_job_id
        self._afm_preview_worker._job_id = current_job_id  # type: ignore[attr-defined]

        self._afm_preview_thread.started.connect(self._afm_preview_worker.run)
        
        self._afm_preview_worker.progress_pct.connect(self._handle_afm_preview_progress)
        self._afm_preview_worker.finished.connect(self._afm_preview_done)
        self._afm_preview_worker.error.connect(self._afm_preview_failed)
        
        # cleanup
        self._afm_preview_worker.finished.connect(self._afm_preview_thread.quit)
        self._afm_preview_worker.error.connect(self._afm_preview_thread.quit)
        self._afm_preview_thread.finished.connect(self._afm_preview_worker.deleteLater)

        # start timer for smooth 20->79% progress
        from PyQt6.QtCore import QTimer
        if not hasattr(self, "_afm_preview_timer"):
            self._afm_preview_timer = QTimer(self)
            self._afm_preview_timer.timeout.connect(self._afm_preview_on_timer)
        self._afm_preview_progress_val = 0
        self._afm_preview_timer.start(500)  # increment roughly every 0.5s

        self._afm_preview_thread.start()

    def _afm_preview_on_timer(self) -> None:
        val = getattr(self, "_afm_preview_progress_val", 0)
        if 20 <= val < 79:
            val += 1
            self._afm_preview_progress_val = val
            if hasattr(self._device_panel, "set_preview_progress"):
                self._device_panel.set_preview_progress(val, "Cellpose evaluating...")

    def _afm_preview_done(self, payload: dict) -> None:
        if hasattr(self, "_afm_preview_timer"):
            self._afm_preview_timer.stop()
        if hasattr(self._device_panel, "reset_preview_progress"):
            self._device_panel.reset_preview_progress()  # type: ignore[attr-defined]

        if self._afm_preview_worker and getattr(self._afm_preview_worker, "_is_cancelled", False):
            self.log_panel.log("Preview AFM: CANCELLED (result ignored)")
            if hasattr(self._device_panel, "set_preview_state"):
                self._device_panel.set_preview_state(False)  # type: ignore[attr-defined]
            if hasattr(self._device_panel, "set_status_message"):
                self._device_panel.set_status_message("Cancelled", is_error=True)  # type: ignore[attr-defined]
            return

        # Job-id gating: discard stale results from superseded previews
        worker_job_id = getattr(self._afm_preview_worker, "_job_id", -1)
        if worker_job_id != self._afm_preview_job_id:
            self.log_panel.log(f"Preview AFM: stale result (job {worker_job_id} vs current {self._afm_preview_job_id}), discarded.")
            return

        overlay_rgb = payload.get("overlay")
        n_rods = payload.get("n_rods", "?")
        loader_meta = payload.get("loader_meta")

        if getattr(self, "batch", None):
            self.batch._last_afm_loader_meta = loader_meta
             
        if overlay_rgb is not None:
            self._afm_preview.set_after_image(overlay_rgb)
        else:
            self.log_panel.log("Preview AFM: overlay is None, AFTER tab will be empty.")

        self._afm_preview.show_after_tab()
        self.log_panel.log(f"Preview AFM: DONE (n_rods={n_rods})")

        if hasattr(self._device_panel, "update_loader_info"):
            self._device_panel.update_loader_info(loader_meta)  # type: ignore[attr-defined]

        if hasattr(self._device_panel, "set_preview_state"):
            self._device_panel.set_preview_state(False)  # type: ignore[attr-defined]
            
        if hasattr(self._device_panel, "set_status_message"):
            self._device_panel.set_status_message("Done")  # type: ignore[attr-defined]


    def _afm_preview_failed(self, tb_str: str) -> None:
        if hasattr(self, "_afm_preview_timer"):
            self._afm_preview_timer.stop()
            
        if self._afm_preview_worker and getattr(self._afm_preview_worker, "_is_cancelled", False):
            self.log_panel.log("Preview AFM: FAILED while cancelling")
            self._on_afm_preview_error("Cancelled")
            return

        # Job-id gating: discard stale errors
        worker_job_id = getattr(self._afm_preview_worker, "_job_id", -1)
        if worker_job_id != self._afm_preview_job_id:
            self.log_panel.log(f"Preview AFM: stale error (job {worker_job_id}), discarded.")
            return

        self.log_panel.log("Preview AFM: ERROR")
        # Log stack trace
        for line in tb_str.splitlines():
            self.log_panel.log(line)
        self._on_afm_preview_error(tb_str)

    def _afm_preview_cleanup(self) -> None:
        """Common cleanup for AFM preview."""
        if hasattr(self, "_afm_preview_timer"):
            self._afm_preview_timer.stop()
            
        if hasattr(self._device_panel, "set_preview_state"):
            self._device_panel.set_preview_state(False)  # type: ignore[attr-defined]
        if hasattr(self._device_panel, "set_status_message"):
            self._device_panel.set_status_message("Error", is_error=True)  # type: ignore[attr-defined]

    def _on_afm_preview_error(self, err: str) -> None:
        if self._device_panel and hasattr(self._device_panel, "set_preview_state"):
            self._device_panel.set_preview_state(False)  # type: ignore[attr-defined]
            if hasattr(self._device_panel, "set_preview_progress"):
                self._device_panel.set_preview_progress(0, f"Error: {err}")  # type: ignore[attr-defined]
        self.log_panel.log(f"AFM Preview ERROR: {err}")
        self._afm_preview_cleanup()

    def _handle_afm_preview_progress(self, pct: int, msg: str) -> None:
        """Handle progress updates safely across thread boundaries."""
        self._afm_preview_progress_val = pct
        self.log_panel.log(f"{pct}% - {msg}")
        if hasattr(self._device_panel, "set_preview_progress"):
            self._device_panel.set_preview_progress(pct, msg)  # type: ignore[attr-defined]

    def _on_afm_preview_cancel_clicked(self) -> None:
        """Cancel AFM preview or batch run, whichever is active."""
        cancelled_something = False

        if hasattr(self, "_afm_preview_timer"):
            self._afm_preview_timer.stop()

        if self._afm_preview_worker:
            self._afm_preview_worker.cancel()
            self.log_panel.log("Preview AFM: Cancelling...")
            cancelled_something = True

        if hasattr(self, "_afm_run_timer"):
            self._afm_run_timer.stop()

        if self._afm_run_worker is not None:
            self._afm_run_worker.cancel()
            self.batch.stop()
            self.log_panel.log("AFM RUN: Stop requested...")
            cancelled_something = True

        if cancelled_something and hasattr(self._device_panel, "set_status_message"):
            self._device_panel.set_status_message("Cancelling...", is_error=True)  # type: ignore[attr-defined]

    def _cleanup_afm_preview_thread(self) -> None:
        if self._afm_preview_thread is not None:
            try:
                self._afm_preview_thread.deleteLater()
            except RuntimeError:
                pass
            self._afm_preview_thread = None

    # ============================================================ #
    #  AFM RUN — threaded batch with progress bar (same UX as Preview)
    # ============================================================ #

    def _handle_afm_run_progress(self, pct: int, msg: str) -> None:
        """Handle progress updates from AfmRunWorker."""
        # Never go backward (protects the QTimer smooth range)
        current = getattr(self, '_afm_run_progress_val', 0)
        if pct < current and pct < 100:
            return
        self._afm_run_progress_val = pct
        self.log_panel.log(f"RUN {pct}% — {msg}")
        if hasattr(self._device_panel, 'set_preview_progress'):
            self._device_panel.set_preview_progress(pct, msg)  # type: ignore[attr-defined]

        # Start smooth timer when entering inference phase (20%)
        if pct >= 20 and pct < 80:
            if hasattr(self, '_afm_run_timer') and not self._afm_run_timer.isActive():
                self._afm_run_timer.start(500)
        # Stop smooth timer when inference done (>=80%)
        if pct >= 80:
            if hasattr(self, '_afm_run_timer'):
                self._afm_run_timer.stop()

    def _afm_run_on_timer(self) -> None:
        """Smooth increment 20->79 during inference."""
        val = getattr(self, '_afm_run_progress_val', 0)
        if 20 <= val < 79:
            val += 1
            self._afm_run_progress_val = val
            if hasattr(self._device_panel, 'set_preview_progress'):
                self._device_panel.set_preview_progress(val, "RUN: computing...")  # type: ignore[attr-defined]

    def _afm_run_done(self) -> None:
        """AFM RUN completed successfully."""
        if hasattr(self, '_afm_run_timer'):
            self._afm_run_timer.stop()

        self.log_panel.log("AFM RUN: DONE ✅")

        if hasattr(self._device_panel, 'set_preview_progress'):
            self._device_panel.set_preview_progress(100, "RUN: Done")  # type: ignore[attr-defined]
        if hasattr(self._device_panel, 'reset_preview_progress'):
            self._device_panel.reset_preview_progress()  # type: ignore[attr-defined]
        if hasattr(self._device_panel, 'set_run_state'):
            self._device_panel.set_run_state(False)  # type: ignore[attr-defined]
        if hasattr(self._device_panel, 'set_status_message'):
            self._device_panel.set_status_message("RUN: Done")  # type: ignore[attr-defined]

    def _afm_run_failed(self, tb_str: str) -> None:
        """AFM RUN failed with error."""
        if hasattr(self, '_afm_run_timer'):
            self._afm_run_timer.stop()

        self.log_panel.log("AFM RUN: ERROR")
        for line in tb_str.splitlines():
            self.log_panel.log(line)

        if hasattr(self._device_panel, 'reset_preview_progress'):
            self._device_panel.reset_preview_progress()  # type: ignore[attr-defined]
        if hasattr(self._device_panel, 'set_run_state'):
            self._device_panel.set_run_state(False)  # type: ignore[attr-defined]
        if hasattr(self._device_panel, 'set_status_message'):
            self._device_panel.set_status_message(f"RUN Error", is_error=True)  # type: ignore[attr-defined]

    def _cleanup_afm_run_thread(self) -> None:
        """Clean up RUN thread after it finishes."""
        if self._afm_run_thread is not None:
            try:
                self._afm_run_thread.deleteLater()
            except RuntimeError:
                pass
            self._afm_run_thread = None
            self._afm_run_worker = None

