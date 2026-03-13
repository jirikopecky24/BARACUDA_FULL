from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, QObject, QEvent, QLocale, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFormLayout, QHBoxLayout,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton, QComboBox,
    QScrollArea, QFrame, QSizePolicy, QAbstractSpinBox, QTabWidget
)
from barakuda.devices.base import DeviceSpec
from barakuda.devices.afm.core.afm_v2_pipeline import _HAS_CELLPOSE
from barakuda.devices.afm.core.compute import resolve_device


class NoWheelValueChangeFilter(QObject):
    """Event filter that blocks mouse wheel from changing values in scrollable panels."""
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return False


class AfmPanel(QWidget):
    run_batch_clicked = pyqtSignal()
    auto_preview_requested = pyqtSignal()
    value_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Use Czech locale for all spinboxes to ensure ',' is used for decimals
        self._loc = QLocale(QLocale.Language.Czech, QLocale.Country.CzechRepublic)
        self._afm_method = "rod_bacteria"
        self._method_options = [
            ("Rod Bacteria (Cellpose + Rod Fit)", "rod_bacteria", True),
            ("Hydrogel Porosity (coming soon)", "hydrogel_porosity", False),
        ]

        # ══════════════════════════════════════════════════════════
        # FIXED TOP: title + warning
        # ══════════════════════════════════════════════════════════
        top_bar = QVBoxLayout()
        top_bar.setContentsMargins(8, 6, 8, 2)

        title = QLabel("AFM Analysis Pipeline")
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        top_bar.addWidget(title)

        if not _HAS_CELLPOSE:
            warn = QLabel(
                "⚠ Cellpose is NOT installed. Segmentation will fail.\n"
                "Install via: pip install cellpose"
            )
            warn.setStyleSheet("color: #d32f2f; font-weight: 600; padding: 6px;")
            warn.setWordWrap(True)
            top_bar.addWidget(warn)

        layout.addLayout(top_bar)

        # ── Data ──────────────────────────────────────────────────
        self.lbl_method_value = QLabel(self._method_display_name(self._afm_method))
        self.lbl_method_value.setStyleSheet("color: #2e7d32; font-weight: 600;")
        self.lbl_method_settings_value = QLabel(self._method_display_name(self._afm_method))
        self.lbl_method_settings_value.setStyleSheet("color: #2e7d32; font-weight: 600;")
        self.lbl_channel = QLabel("Channel: unknown")
        self.lbl_channel.setStyleSheet("color: #555;")

        self.lbl_scale = QLabel("Scale: unknown")
        self.lbl_scale.setStyleSheet("color: #b71c1c; font-weight: 600;")

        self.lbl_status = QLabel("Status: idle")
        self.lbl_status.setStyleSheet("color: #0277bd; font-weight: 600; font-size: 11px;")
        
        from PyQt6.QtWidgets import QProgressBar
        self.pb_preview = QProgressBar()
        self.pb_preview.setRange(0, 100)
        self.pb_preview.setValue(0)
        self.pb_preview.setVisible(False)

        # ── Compute ───────────────────────────────────────────────
        self.cb_profile = QComboBox()
        self.cb_profile.addItems(["Auto", "GPU (force)", "CPU (force)"])
        self.cb_profile.setCurrentText("Auto")
        self.cb_profile.currentTextChanged.connect(self._on_profile_changed)

        self.lbl_dev_info = QLabel("Device: ?\nTorch: ?\nCellpose: ?")
        self.lbl_dev_info.setStyleSheet("color: #666; font-size: 11px;")
        self.lbl_dev_info.setWordWrap(True)

        self.chk_fast_preview = QCheckBox("Fast Preview (CPU recommended)")
        self.chk_fast_preview.setChecked(True)
        self.chk_fast_preview.stateChanged.connect(self._on_fast_preview_changed)

        self.cb_downscale = QComboBox()
        self.cb_downscale.addItems(["1.0", "0.75", "0.5", "0.33"])
        self.cb_downscale.setCurrentText("0.5")

        # ── Preprocessing ─────────────────────────────────────────
        self.cb_invert = QCheckBox("Invert (bacteria are dark)")
        self.cb_invert.setChecked(False)

        self.sp_clip_low = QDoubleSpinBox()
        self.sp_clip_low.setLocale(self._loc)
        self.sp_clip_low.setRange(0.0, 50.0)
        self.sp_clip_low.setDecimals(1)
        self.sp_clip_low.setSingleStep(0.5)
        self.sp_clip_low.setValue(1.0)

        self.sp_clip_high = QDoubleSpinBox()
        self.sp_clip_high.setLocale(self._loc)
        self.sp_clip_high.setRange(50.0, 100.0)
        self.sp_clip_high.setDecimals(1)
        self.sp_clip_high.setSingleStep(0.5)
        self.sp_clip_high.setValue(99.0)

        # ── Cellpose Segmentation ─────────────────────────────────
        self.cb_cp_model = QComboBox()
        self.cb_cp_model.addItems(["cyto3", "cyto2", "cyto", "nuclei"])
        self.cb_cp_model.setCurrentText("cyto3")

        self.sp_cp_diam = QDoubleSpinBox()
        self.sp_cp_diam.setLocale(self._loc)
        self.sp_cp_diam.setRange(0.0, 200.0)
        self.sp_cp_diam.setDecimals(1)
        self.sp_cp_diam.setSingleStep(1.0)
        self.sp_cp_diam.setValue(0.0)
        self.sp_cp_diam.setSpecialValueText("Auto")

        self.sp_cp_flow = QDoubleSpinBox()
        self.sp_cp_flow.setLocale(self._loc)
        self.sp_cp_flow.setRange(0.0, 1.0)
        self.sp_cp_flow.setSingleStep(0.05)
        self.sp_cp_flow.setDecimals(2)
        self.sp_cp_flow.setValue(0.4)

        self.sp_cp_prob = QDoubleSpinBox()
        self.sp_cp_prob.setLocale(self._loc)
        self.sp_cp_prob.setRange(-6.0, 6.0)
        self.sp_cp_prob.setSingleStep(0.10)
        self.sp_cp_prob.setDecimals(2)
        self.sp_cp_prob.setValue(-0.5)

        # ── Rod Geometry Filter ───────────────────────────────────
        self.cb_rods_only = QCheckBox("Rods only")
        self.cb_rods_only.setChecked(True)

        self.sp_rods_min_major = QDoubleSpinBox()
        self.sp_rods_min_major.setLocale(self._loc)
        self.sp_rods_min_major.setRange(1.0, 500.0)
        self.sp_rods_min_major.setDecimals(0)
        self.sp_rods_min_major.setSingleStep(1.0)
        self.sp_rods_min_major.setValue(12.0)

        self.sp_rods_min_ar = QDoubleSpinBox()
        self.sp_rods_min_ar.setLocale(self._loc)
        self.sp_rods_min_ar.setRange(1.0, 20.0)
        self.sp_rods_min_ar.setDecimals(2)
        self.sp_rods_min_ar.setSingleStep(0.10)
        self.sp_rods_min_ar.setValue(1.8)

        self.sp_rods_min_ecc = QDoubleSpinBox()
        self.sp_rods_min_ecc.setLocale(self._loc)
        self.sp_rods_min_ecc.setRange(0.0, 0.99)
        self.sp_rods_min_ecc.setDecimals(2)
        self.sp_rods_min_ecc.setSingleStep(0.05)
        self.sp_rods_min_ecc.setValue(0.65)

        self.sp_min_area = QSpinBox()
        self.sp_min_area.setLocale(self._loc)
        self.sp_min_area.setRange(1, 100_000)
        self.sp_min_area.setSingleStep(1)
        self.sp_min_area.setValue(8)

        preset_row = QHBoxLayout()
        self.btn_preset_recall = QPushButton("High Recall")
        self.btn_preset_recall.setToolTip("min_major=10, min_ar=1.6, min_ecc=0.60, min_area=6")
        self.btn_preset_recall.clicked.connect(self._apply_preset_high_recall)
        preset_row.addWidget(self.btn_preset_recall)

        self.btn_preset_nature = QPushButton("Nature Overlay")
        self.btn_preset_nature.setToolTip("min_major=12, min_ar=1.8, min_ecc=0.65, min_area=8")
        self.btn_preset_nature.clicked.connect(self._apply_preset_nature)
        preset_row.addWidget(self.btn_preset_nature)
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_widget = QWidget()
        preset_widget.setLayout(preset_row)

        # ── Overlay ───────────────────────────────────────────────
        self.sp_ellipse_thick = QSpinBox()
        self.sp_ellipse_thick.setLocale(self._loc)
        self.sp_ellipse_thick.setRange(1, 10)
        self.sp_ellipse_thick.setSingleStep(1)
        self.sp_ellipse_thick.setValue(2)

        self.sp_ellipse_alpha = QDoubleSpinBox()
        self.sp_ellipse_alpha.setLocale(self._loc)
        self.sp_ellipse_alpha.setRange(0.20, 1.00)
        self.sp_ellipse_alpha.setDecimals(2)
        self.sp_ellipse_alpha.setSingleStep(0.05)
        self.sp_ellipse_alpha.setValue(0.60)

        ov_info = QLabel("Overlay renders ellipse fit from rod_table (no boundaries).")
        ov_info.setStyleSheet("color: #888; font-size: 11px; font-style: italic;")
        ov_info.setWordWrap(True)

        # ══════════════════════════════════════════════════════════
        # ACTIONS / BEHAVIOR
        # ══════════════════════════════════════════════════════════
        roi_hint = QLabel("Preview ROI defines the computation region.")
        roi_hint.setStyleSheet("color: #888; font-size: 11px;")
        roi_hint.setWordWrap(True)

        self.chk_auto_preview = QCheckBox("Auto Preview")
        self.chk_auto_preview.setChecked(True)
        self.chk_auto_preview.setToolTip(
            "Automatically run preview after any AFM parameter change.\n"
            "Uses 500 ms debounce to avoid redundant runs."
        )

        self.btn_preview = QPushButton("Preview AFM")

        self.btn_cancel = QPushButton("Cancel Preview")
        self.btn_cancel.setEnabled(False)

        self.btn_reset = QPushButton("Reset AFM defaults")
        self.btn_reset.clicked.connect(self.apply_afm_defaults)

        self.btn_run = QPushButton("Run AFM Batch")
        self.btn_run.clicked.connect(self.run_batch_clicked.emit)

        self._applying_defaults = True
        self._auto_preview_armed = False  # armed after 1st manual Preview

        # ══════════════════════════════════════════════════════════
        # RUN TAB (OT-style: plain widgets, no fancy card stylesheets)
        # ══════════════════════════════════════════════════════════
        run_box = QWidget()
        run_box_layout = QVBoxLayout(run_box)
        run_box_layout.setContentsMargins(0, 0, 0, 0)
        run_box_layout.setSpacing(10)

        run_input_header = QLabel("Dataset / Input")
        run_input_header.setStyleSheet("font-weight: bold; color: #555;")
        run_box_layout.addWidget(run_input_header)

        run_input_form = QFormLayout()
        run_input_form.setContentsMargins(0, 0, 0, 0)
        run_input_form.addRow("Selected method", self.lbl_method_value)
        run_input_form.addRow("Channel", self.lbl_channel)
        run_input_form.addRow("Scale", self.lbl_scale)
        run_input_form.addRow("Status", self.lbl_status)
        run_input_form.addRow("Preview progress", self.pb_preview)
        run_box_layout.addLayout(run_input_form)

        run_actions_header = QLabel("Run Actions")
        run_actions_header.setStyleSheet("font-weight: bold; color: #555;")
        run_box_layout.addWidget(run_actions_header)

        auto_save_note = QLabel("AFM outputs save automatically into the analysis layout when a run finishes.")
        auto_save_note.setStyleSheet("color: #666; font-size: 11px;")
        auto_save_note.setWordWrap(True)
        run_box_layout.addWidget(roi_hint)
        run_box_layout.addWidget(auto_save_note)
        run_box_layout.addWidget(self.btn_preview)
        run_box_layout.addWidget(self.btn_cancel)
        run_box_layout.addWidget(self.btn_run)
        run_box_layout.addStretch(1)

        # ══════════════════════════════════════════════════════════
        # SEGMENTATION TAB (OT-style)
        # ══════════════════════════════════════════════════════════
        seg_box = QWidget()
        seg_box_layout = QVBoxLayout(seg_box)
        seg_box_layout.setContentsMargins(0, 0, 0, 0)
        seg_box_layout.setSpacing(10)

        seg_header = QLabel("Segmentation")
        seg_header.setStyleSheet("font-weight: bold; color: #555;")
        seg_box_layout.addWidget(seg_header)

        self._seg_form = QFormLayout()
        self._seg_form.setContentsMargins(0, 0, 0, 0)

        self._seg_advanced = QCheckBox("Advanced options")
        self._seg_advanced.setToolTip("Show advanced segmentation parameters.")
        self._seg_advanced.setChecked(False)
        self._seg_form.addRow("", self._seg_advanced)

        self._seg_form.addRow("", self.cb_invert)
        self._seg_form.addRow("Model", self.cb_cp_model)
        self._seg_form.addRow("Diameter (px)", self.sp_cp_diam)

        self._seg_form.addRow("Clip percentile low", self.sp_clip_low)
        self._seg_form.addRow("Clip percentile high", self.sp_clip_high)
        self._seg_form.addRow("Flow threshold", self.sp_cp_flow)
        self._seg_form.addRow("Cellprob threshold", self.sp_cp_prob)

        seg_box_layout.addLayout(self._seg_form)
        seg_box_layout.addStretch(1)

        def _on_seg_advanced_toggled(checked: bool) -> None:
            self._set_row_visible(self._seg_form, self.sp_clip_low, checked)
            self._set_row_visible(self._seg_form, self.sp_clip_high, checked)
            self._set_row_visible(self._seg_form, self.sp_cp_flow, checked)
            self._set_row_visible(self._seg_form, self.sp_cp_prob, checked)

        _on_seg_advanced_toggled(False)

        # ══════════════════════════════════════════════════════════
        # FILTER TAB (OT-style)
        # ══════════════════════════════════════════════════════════
        filter_box = QWidget()
        filter_box_layout = QVBoxLayout(filter_box)
        filter_box_layout.setContentsMargins(0, 0, 0, 0)
        filter_box_layout.setSpacing(10)

        filter_header = QLabel("Rod Filter")
        filter_header.setStyleSheet("font-weight: bold; color: #555;")
        filter_box_layout.addWidget(filter_header)

        self._filter_form = QFormLayout()
        self._filter_form.setContentsMargins(0, 0, 0, 0)

        self._filter_advanced = QCheckBox("Advanced options")
        self._filter_advanced.setToolTip("Show advanced filter and overlay parameters.")
        self._filter_advanced.setChecked(False)
        self._filter_form.addRow("", self._filter_advanced)

        self._filter_form.addRow("", self.cb_rods_only)
        self._filter_form.addRow("Min major axis (px)", self.sp_rods_min_major)
        self._filter_form.addRow("Min aspect ratio", self.sp_rods_min_ar)
        self._filter_form.addRow("Presets", preset_widget)

        self._filter_form.addRow("Min eccentricity", self.sp_rods_min_ecc)
        self._filter_form.addRow("Min area (px)", self.sp_min_area)
        self._filter_form.addRow("Ellipse thickness (px)", self.sp_ellipse_thick)
        self._filter_form.addRow("Ellipse alpha", self.sp_ellipse_alpha)
        self._filter_form.addRow("", ov_info)

        filter_box_layout.addLayout(self._filter_form)
        filter_box_layout.addStretch(1)

        def _on_filter_advanced_toggled(checked: bool) -> None:
            self._set_row_visible(self._filter_form, self.sp_rods_min_ecc, checked)
            self._set_row_visible(self._filter_form, self.sp_min_area, checked)
            self._set_row_visible(self._filter_form, self.sp_ellipse_thick, checked)
            self._set_row_visible(self._filter_form, self.sp_ellipse_alpha, checked)
            self._set_row_visible(self._filter_form, ov_info, checked)

        _on_filter_advanced_toggled(False)

        # ══════════════════════════════════════════════════════════
        # SETTINGS TAB (OT-style)
        # ══════════════════════════════════════════════════════════
        settings_box = QWidget()
        settings_box_layout = QVBoxLayout(settings_box)
        settings_box_layout.setContentsMargins(0, 0, 0, 0)
        settings_box_layout.setSpacing(10)

        compute_header = QLabel("Compute / Graphics")
        compute_header.setStyleSheet("font-weight: bold; color: #555;")
        settings_box_layout.addWidget(compute_header)

        compute_form = QFormLayout()
        compute_form.setContentsMargins(0, 0, 0, 0)
        compute_form.addRow("Compute Profile", self.cb_profile)
        compute_form.addRow("Resolved runtime", self.lbl_dev_info)
        compute_form.addRow("", self.chk_fast_preview)
        compute_form.addRow("Preview downscale", self.cb_downscale)
        settings_box_layout.addLayout(compute_form)

        defaults_header = QLabel("Defaults / Method Behavior")
        defaults_header.setStyleSheet("font-weight: bold; color: #555;")
        settings_box_layout.addWidget(defaults_header)

        settings_form = QFormLayout()
        settings_form.setContentsMargins(0, 0, 0, 0)
        settings_form.addRow("Active method", self.lbl_method_settings_value)
        settings_form.addRow("", self.chk_auto_preview)
        settings_form.addRow("", self.btn_reset)
        settings_box_layout.addLayout(settings_form)
        settings_box_layout.addStretch(1)

        # ══════════════════════════════════════════════════════════
        # TABS ASSEMBLY (OT-style: QScrollArea with NoFrame)
        # ══════════════════════════════════════════════════════════
        def _make_scroll_tab(content_widget: QWidget) -> QWidget:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(8, 8, 8, 8)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(content_widget)
            tab_layout.addWidget(scroll)
            return tab

        self.tabs = QTabWidget()
        self.tabs.addTab(_make_scroll_tab(run_box), "Run")
        self.tabs.addTab(_make_scroll_tab(seg_box), "Segmentation")
        self.tabs.addTab(_make_scroll_tab(filter_box), "Filter")
        self.tabs.addTab(_make_scroll_tab(settings_box), "Settings")
        layout.addWidget(self.tabs, stretch=1)

        self._seg_advanced.toggled.connect(_on_seg_advanced_toggled)
        self._filter_advanced.toggled.connect(_on_filter_advanced_toggled)

        self.apply_afm_defaults()
        self.apply_afm_tooltips()
        self._refresh_method_labels()
        self._on_profile_changed() # Trigger initial hardware check
        self._applying_defaults = False

        # ── Debounce timer for auto-preview ───────────────────────
        self._auto_preview_timer = QTimer(self)
        self._auto_preview_timer.setSingleShot(True)
        self._auto_preview_timer.setInterval(500)
        self._auto_preview_timer.timeout.connect(self._fire_auto_preview)

        # Connect all AFM parameter widgets to debounce trigger
        for sb in (self.sp_clip_low, self.sp_clip_high,
                   self.sp_cp_diam, self.sp_cp_flow, self.sp_cp_prob,
                   self.sp_rods_min_major, self.sp_rods_min_ar,
                   self.sp_rods_min_ecc,
                   self.sp_ellipse_alpha):
            sb.valueChanged.connect(self._schedule_auto_preview)
        for sb_int in (self.sp_min_area, self.sp_ellipse_thick):
            sb_int.valueChanged.connect(self._schedule_auto_preview)
        for cb in (self.cb_invert, self.cb_rods_only):
            cb.stateChanged.connect(self._schedule_auto_preview)
        self.cb_cp_model.currentIndexChanged.connect(self._schedule_auto_preview)
        self.cb_profile.currentIndexChanged.connect(self._emit_value_changed)
        self.cb_downscale.currentIndexChanged.connect(self._emit_value_changed)
        self.cb_cp_model.currentIndexChanged.connect(self._emit_value_changed)
        for sb in (
            self.sp_clip_low,
            self.sp_clip_high,
            self.sp_cp_diam,
            self.sp_cp_flow,
            self.sp_cp_prob,
            self.sp_rods_min_major,
            self.sp_rods_min_ar,
            self.sp_rods_min_ecc,
            self.sp_ellipse_alpha,
        ):
            sb.valueChanged.connect(self._emit_value_changed)
        for sb_int in (self.sp_min_area, self.sp_ellipse_thick):
            sb_int.valueChanged.connect(self._emit_value_changed)
        for cb in (self.chk_fast_preview, self.cb_invert, self.cb_rods_only, self.chk_auto_preview):
            cb.stateChanged.connect(self._emit_value_changed)

        # ── Wheel Blocker ─────────────────────────────────────────
        self._wheel_blocker = NoWheelValueChangeFilter(self)
        for w in self.findChildren(QAbstractSpinBox):
            w.installEventFilter(self._wheel_blocker)
        for w in self.findChildren(QComboBox):
            w.installEventFilter(self._wheel_blocker)

    def _set_row_visible(self, form: QFormLayout, widget: QWidget, visible: bool) -> None:
        """OT-style helper to hide/show a form row by its field widget."""
        for row_idx in range(form.rowCount()):
            item = form.itemAt(row_idx, QFormLayout.ItemRole.FieldRole)
            if item is not None and item.widget() is widget:
                label_item = form.itemAt(row_idx, QFormLayout.ItemRole.LabelRole)
                if label_item is not None and label_item.widget() is not None:
                    label_item.widget().setVisible(visible)
                widget.setVisible(visible)
                return

    def available_afm_methods(self) -> list[tuple[str, str, bool]]:
        return list(self._method_options)

    def get_afm_method(self) -> str:
        return self._afm_method

    def set_afm_method(self, method_id: str, *, emit: bool = True) -> None:
        valid_ids = {mid for _label, mid, enabled in self._method_options if enabled}
        resolved_method = method_id if method_id in valid_ids else "rod_bacteria"
        changed = resolved_method != self._afm_method
        self._afm_method = resolved_method
        self._refresh_method_labels()
        if changed and emit and not getattr(self, "_applying_defaults", False):
            self.value_changed.emit()

    def _method_display_name(self, method_id: str) -> str:
        for label, mid, _enabled in self._method_options:
            if mid == method_id:
                return label
        return method_id

    def _refresh_method_labels(self) -> None:
        label = self._method_display_name(self._afm_method)
        self.lbl_method_value.setText(label)
        self.lbl_method_settings_value.setText(label)

    # ── Update Data section from loader metadata ──────────────────
    def update_loader_info(self, meta: dict | None) -> None:
        """Update the read-only Data section from loader metadata.

        Called by preview/batch after loading an .spm file.
        """
        if meta is None:
            self.lbl_channel.setText("–")
            self.lbl_scale.setText("unknown")
            self.lbl_scale.setStyleSheet("color: #b71c1c; font-weight: 600;")
            return

        ch = meta.get("selected_channel", "–")
        self.lbl_channel.setText(str(ch))

        um_per_px = float(meta.get("afm_um_per_px", 0.0))
        um_source = meta.get("afm_um_per_px_source", "unknown")
        px_to_nm = float(meta.get("pixel_to_nm", 0.0))
        px_source = meta.get("pixel_to_nm_source", "unknown")

        if um_per_px > 0 and px_to_nm > 0:
            self.lbl_scale.setText(f"{um_per_px:.6f} µm/px ({px_to_nm:.4f} nm/px, src={um_source})")
            self.lbl_scale.setStyleSheet("color: #2e7d32; font-weight: 600;")
        elif um_per_px > 0:
            self.lbl_scale.setText(f"{um_per_px:.6f} µm/px (src={um_source})")
            self.lbl_scale.setStyleSheet("color: #2e7d32; font-weight: 600;")
        elif px_to_nm > 0:
            self.lbl_scale.setText(f"{px_to_nm:.4f} nm/px (src={px_source})")
            self.lbl_scale.setStyleSheet("color: #2e7d32; font-weight: 600;")
        else:
            self.lbl_scale.setText("unknown")
            self.lbl_scale.setStyleSheet("color: #b71c1c; font-weight: 600;")

    # ── UI State Helpers ──────────────────────────────────────────
    def set_preview_progress(self, pct: int, text: str | None = None) -> None:
        pct = max(0, min(100, pct))
        self.pb_preview.setVisible(True)
        self.pb_preview.setValue(pct)
        if text:
            self.lbl_status.setText(f"Status: {text}")

    def reset_preview_progress(self) -> None:
        self.pb_preview.setValue(0)
        self.pb_preview.setVisible(False)
        self.lbl_status.setText("Status: idle")

    def set_preview_state(self, is_running: bool) -> None:
        """Called by MainWindow to toggle running state UI (disables Preview button)."""
        self.btn_preview.setEnabled(not is_running)
        self.btn_cancel.setEnabled(is_running)
        if is_running:
            self.btn_preview.setText("Preview AFM (running...)")
            self.btn_run.setEnabled(False)
            self.lbl_status.setText("Preview running... (Cellpose)")
            self.lbl_status.setStyleSheet("color: #e65100; font-weight: 600; font-size: 11px;")
        else:
            self.btn_preview.setEnabled(True)
            self.btn_preview.setText("Preview AFM")
            self.btn_cancel.setEnabled(False)
            self.btn_run.setEnabled(True)

    def set_run_state(self, is_running: bool) -> None:
        self.btn_run.setEnabled(not is_running)
        self.btn_preview.setEnabled(not is_running)
        self.btn_cancel.setEnabled(is_running)
        self.btn_reset.setEnabled(not is_running)
        if is_running:
            self.btn_run.setText("Run AFM Batch (running...)")
            self.lbl_status.setText("Batch running...")
            self.lbl_status.setStyleSheet("color: #e65100; font-weight: 600; font-size: 11px;")
        else:
            self.btn_run.setText("Run AFM Batch")
            self.btn_preview.setText("Preview AFM")
            self.btn_cancel.setEnabled(False)

    def set_status_message(self, text: str, is_error: bool = False):
        self.lbl_status.setText(text)
        if is_error:
            self.lbl_status.setStyleSheet("color: #d32f2f; font-weight: 600; font-size: 11px;")
        else:
            self.lbl_status.setStyleSheet("color: #2e7d32; font-weight: 600; font-size: 11px;")

    def _on_fast_preview_changed(self, state: int):
        self.cb_downscale.setEnabled(self.chk_fast_preview.isChecked())

    def _on_profile_changed(self, text: str = ""):
        txt = self.cb_profile.currentText()
        if "GPU" in txt:
            prof = "gpu"
        elif "CPU" in txt:
            prof = "cpu"
        else:
            prof = "auto"

        try:
            info = resolve_device(prof)
            dev = info.get("device", "unknown")
            t_ver = info.get("torch_version", "?")
            c_ver = info.get("cellpose_version", "?")
            gpu_n = info.get("gpu_name", "")
            
            if dev == "cuda" and gpu_n and gpu_n != "unknown":
                dev_str = f"cuda ({gpu_n})"
            else:
                dev_str = dev
                
            self.lbl_dev_info.setText(f"Device: {dev_str}\nTorch: {t_ver}\nCellpose: {c_ver}")
            
            # auto-apply sensible view defaults if the user switches compute engines
            if prof == "cpu" or dev == "cpu":
                self.chk_fast_preview.setChecked(True)
                self.cb_downscale.setCurrentText("0.5")
            else:
                self.chk_fast_preview.setChecked(False)
                self.cb_downscale.setCurrentText("1.0")

        except Exception as e:
            self.lbl_dev_info.setText(f"Device: Error\n{e}")
            self.lbl_dev_info.setStyleSheet("color: #d32f2f; font-size: 11px;")

    # ── Defaults (from kanalek-novy reference run) ──────────────────
    def apply_afm_defaults(self):
        # Compute default
        self.cb_profile.setCurrentText("Auto")
        self.chk_fast_preview.setChecked(False)
        self.cb_downscale.setCurrentText("1.0")
        # Preprocessing
        self.cb_invert.setChecked(False)
        self.sp_clip_low.setValue(1.0)
        self.sp_clip_high.setValue(99.0)

        # Cellpose
        self.cb_cp_model.setCurrentText("cyto3")
        self.sp_cp_diam.setValue(18.0)      # fixed 18 px
        self.sp_cp_flow.setValue(0.4)
        self.sp_cp_prob.setValue(0.3)

        # Rod filter
        self.cb_rods_only.setChecked(False)
        self.sp_rods_min_major.setValue(12.0)
        self.sp_rods_min_ar.setValue(1.8)
        self.sp_rods_min_ecc.setValue(0.65)
        self.sp_min_area.setValue(8)

        # Overlay
        self.sp_ellipse_thick.setValue(1)
        self.sp_ellipse_alpha.setValue(0.60)

    # ── Tooltips ──────────────────────────────────────────────────
    def apply_afm_tooltips(self):
        self.cb_invert.setToolTip(
            "Invert intensity.\n"
            "Use if bacteria appear DARK relative to background."
        )
        self.sp_clip_low.setToolTip(
            "Clip percentile low.\n"
            "Pixels below this percentile are clipped.\nDefault 1.0."
        )
        self.sp_clip_high.setToolTip(
            "Clip percentile high.\n"
            "Pixels above this percentile are clipped.\nDefault 99.0."
        )
        self.cb_cp_model.setToolTip(
            "Cellpose model.\n"
            "cyto3 = general cells/bacteria (recommended).\n"
            "cyto2 / cyto = older models.\n"
            "nuclei = for nuclei detection."
        )
        self.sp_cp_diam.setToolTip(
            "Cellpose Diameter [px].\n"
            "0 = Auto (slower but adaptive).\n"
            "Set manually if you know the cell size."
        )
        self.sp_cp_flow.setToolTip(
            "Flow threshold.\n"
            "Controls mask boundary strictness.\n"
            "Lower = stricter, Higher = more generous.\nDefault 0.4."
        )
        self.sp_cp_prob.setToolTip(
            "Cellprob threshold.\n"
            "Lower = more sensitive (larger masks).\n"
            "Default -0.5 (high recall)."
        )
        self.cb_rods_only.setToolTip(
            "Rods only.\n"
            "Filters output to keep only elongated rod-like shapes.\n"
            "Required for ellipse overlay and rod export."
        )
        self.sp_rods_min_major.setToolTip("Min major axis [px].\nRemoves short objects.")
        self.sp_rods_min_ar.setToolTip("Min aspect ratio (Major/Minor).\nRods typically > 1.8.")
        self.sp_rods_min_ecc.setToolTip("Min eccentricity [0–1].\nRods ecc ~ 0.85+.")
        self.sp_min_area.setToolTip("Min area [px²].\nRemoves tiny noise.")
        self.sp_ellipse_thick.setToolTip(
            "Ellipse thickness [px].\n1 = thin, 2 = recommended, 3 = thick."
        )
        self.sp_ellipse_alpha.setToolTip(
            "Ellipse alpha [0.2–1.0].\n"
            "0.6 = semi-transparent (Nature-grade).\n"
            "1.0 = fully opaque (legacy)."
        )

    # ── Parameter collection ──────────────────────────────────────
    def get_afm_params(self) -> dict:
        diam_val = float(self.sp_cp_diam.value())
        if diam_val == 0.0:
            cp_diam_mode = "auto"
            cp_diam_px = None
        else:
            cp_diam_mode = "fixed"
            cp_diam_px = int(diam_val)
            
        prof_txt = self.cb_profile.currentText()
        if "GPU" in prof_txt:
            prof = "gpu"
        elif "CPU" in prof_txt:
            prof = "cpu"
        else:
            prof = "auto"

        return {
            "afm_method": self.get_afm_method(),
            "compute_profile": prof,
            "preview_fast_mode": bool(self.chk_fast_preview.isChecked()),
            "preview_downscale": float(self.cb_downscale.currentText()),
            "invert": bool(self.cb_invert.isChecked()),
            "clip_p_low": float(self.sp_clip_low.value()),
            "clip_p_high": float(self.sp_clip_high.value()),
            "cp_model": str(self.cb_cp_model.currentText()),
            "cp_diameter_mode": cp_diam_mode,
            "cp_diameter_px": cp_diam_px,
            "cp_flow_threshold": float(self.sp_cp_flow.value()),
            "cp_cellprob_threshold": float(self.sp_cp_prob.value()),
            "rods_only": bool(self.cb_rods_only.isChecked()),
            "rods_min_major_axis_px": float(self.sp_rods_min_major.value()),
            "rods_min_aspect_ratio": float(self.sp_rods_min_ar.value()),
            "rods_min_eccentricity": float(self.sp_rods_min_ecc.value()),
            "rods_min_area_px": int(self.sp_min_area.value()),
            "ellipse_thickness_px": int(self.sp_ellipse_thick.value()),
            "ellipse_alpha": float(self.sp_ellipse_alpha.value()),
        }

    def load_afm_params(self, params: dict) -> None:
        self._applying_defaults = True
        try:
            method_id = str(params.get("afm_method", "rod_bacteria") or "rod_bacteria")
            self.set_afm_method(method_id, emit=False)

            profile = str(params.get("compute_profile", "auto")).strip().lower()
            if profile == "gpu":
                self.cb_profile.setCurrentText("GPU (force)")
            elif profile == "cpu":
                self.cb_profile.setCurrentText("CPU (force)")
            else:
                self.cb_profile.setCurrentText("Auto")

            self.chk_fast_preview.setChecked(bool(params.get("preview_fast_mode", False)))
            self.cb_downscale.setCurrentText(str(params.get("preview_downscale", "1.0")))
            self.cb_invert.setChecked(bool(params.get("invert", False)))
            self.sp_clip_low.setValue(float(params.get("clip_p_low", 1.0)))
            self.sp_clip_high.setValue(float(params.get("clip_p_high", 99.0)))
            self.cb_cp_model.setCurrentText(str(params.get("cp_model", "cyto3")))
            if str(params.get("cp_diameter_mode", "auto")).strip().lower() == "auto":
                self.sp_cp_diam.setValue(0.0)
            else:
                self.sp_cp_diam.setValue(float(params.get("cp_diameter_px", 18) or 18))
            self.sp_cp_flow.setValue(float(params.get("cp_flow_threshold", 0.4)))
            self.sp_cp_prob.setValue(float(params.get("cp_cellprob_threshold", 0.3)))
            self.cb_rods_only.setChecked(bool(params.get("rods_only", False)))
            self.sp_rods_min_major.setValue(float(params.get("rods_min_major_axis_px", 12.0)))
            self.sp_rods_min_ar.setValue(float(params.get("rods_min_aspect_ratio", 1.8)))
            self.sp_rods_min_ecc.setValue(float(params.get("rods_min_eccentricity", 0.65)))
            self.sp_min_area.setValue(int(params.get("rods_min_area_px", 8)))
            self.sp_ellipse_thick.setValue(int(params.get("ellipse_thickness_px", 1)))
            self.sp_ellipse_alpha.setValue(float(params.get("ellipse_alpha", 0.6)))
            self._on_profile_changed()
        finally:
            self._applying_defaults = False

    # ── Preset helpers ─────────────────────────────────────────────
    def _apply_preset_high_recall(self):
        self._applying_defaults = True
        self.sp_rods_min_major.setValue(10.0)
        self.sp_rods_min_ar.setValue(1.60)
        self.sp_rods_min_ecc.setValue(0.60)
        self.sp_min_area.setValue(6)
        self._applying_defaults = False
        self._schedule_auto_preview()

    def _apply_preset_nature(self):
        self._applying_defaults = True
        self.sp_rods_min_major.setValue(12.0)
        self.sp_rods_min_ar.setValue(1.80)
        self.sp_rods_min_ecc.setValue(0.65)
        self.sp_min_area.setValue(8)
        self._applying_defaults = False
        self._schedule_auto_preview()

    # ── Auto-preview debounce ─────────────────────────────────────
    def _schedule_auto_preview(self, *_args) -> None:
        """Restart debounce timer; will fire auto_preview_requested after 500 ms idle."""
        if getattr(self, "_applying_defaults", False):
            return
        if not self.chk_auto_preview.isChecked():
            return
        if not getattr(self, "_auto_preview_armed", False):
            return
        self._auto_preview_timer.stop()
        self._auto_preview_timer.start()

    def _fire_auto_preview(self) -> None:
        """Called when debounce timer expires — emit the signal."""
        if self.chk_auto_preview.isChecked() and self._auto_preview_armed:
            self.auto_preview_requested.emit()

    def _emit_value_changed(self, *_args) -> None:
        if getattr(self, "_applying_defaults", False):
            return
        self.value_changed.emit()

    def arm_auto_preview(self) -> None:
        """Call after first manual Preview to enable auto-preview."""
        self._auto_preview_armed = True

    def disarm_auto_preview(self) -> None:
        """Call on dataset change to reset auto-preview armed state."""
        self._auto_preview_armed = False
        self._auto_preview_timer.stop()


def get_device_spec() -> DeviceSpec:
    return DeviceSpec(
        device_id="afm",
        display_name="AFM",
        create_panel=lambda: AfmPanel(),
    )
