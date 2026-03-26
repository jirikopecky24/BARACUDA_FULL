from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
)

from barakuda.core.run_protocol import (
    create_protocol_from_context,
    load_protocol,
    merge_protocol,
    save_protocol,
    protocol_path_for_run,
)


class RunProtocolDialog(QDialog):
    """MVP editor for run_protocol.json with read-only provenance."""

    def __init__(self, run_folder: str | Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run Protocol Editor")
        self.resize(980, 740)

        self._protocol_path: Path | None = None
        self._protocol_data: dict[str, Any] = create_protocol_from_context()
        self._field_widgets: dict[str, QWidget] = {}

        self._path_edit = QLineEdit("")
        self._path_edit.setPlaceholderText("Path to run_protocol.json or run folder")
        self._btn_browse = QPushButton("Browse…")
        self._btn_load = QPushButton("Load")
        self._btn_save = QPushButton("Save")
        self._status = QLabel("Ready.")
        self._status.setStyleSheet("color: #666;")

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Protocol path:"))
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(self._btn_browse)
        path_row.addWidget(self._btn_load)
        path_row.addWidget(self._btn_save)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_identity_tab(), "Identity")
        self._tabs.addTab(self._build_sample_tab(), "Sample")
        self._tabs.addTab(self._build_bead_tab(), "Bead")
        self._tabs.addTab(self._build_notes_status_tab(), "Notes / Status")
        self._tabs.addTab(self._build_read_only_tab(), "Read-only Provenance")

        layout = QVBoxLayout(self)
        layout.addLayout(path_row)
        layout.addWidget(self._tabs, 1)
        layout.addWidget(self._status)

        self._btn_browse.clicked.connect(self._on_browse)
        self._btn_load.clicked.connect(self._on_load)
        self._btn_save.clicked.connect(self._on_save)

        if run_folder is not None:
            self._path_edit.setText(str(protocol_path_for_run(run_folder)))
            self._on_load()
        else:
            self._bind_widgets_from_protocol()

    def _build_identity_tab(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        self._add_line_edit(form, "identity.experiment_id", "experiment_id")
        self._add_line_edit(form, "identity.session_id", "session_id")
        self._add_line_edit(form, "identity.run_id", "run_id / basename")
        self._add_line_edit(form, "identity.operator", "operator")
        return box

    def _build_sample_tab(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        self._add_line_edit(form, "sample.medium", "medium")
        self._add_line_edit(form, "sample.glycerol_percent", "glycerol_percent")
        self._add_line_edit(form, "sample.temperature_c", "temperature_c")
        self._add_line_edit(form, "sample.preparation_note", "preparation_note", multiline=True)
        self._add_line_edit(form, "sample.sample_note", "sample_note", multiline=True)
        return box

    def _build_bead_tab(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        self._add_line_edit(form, "bead.material", "material")
        self._add_line_edit(form, "bead.diameter_um", "diameter_um")
        self._add_line_edit(form, "bead.radius_um", "radius_um")
        self._add_line_edit(form, "bead.manufacturer", "manufacturer")
        self._add_line_edit(form, "bead.lot", "lot")
        self._add_line_edit(form, "bead.bead_note", "bead_note", multiline=True)
        return box

    def _build_notes_status_tab(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)
        self._add_line_edit(form, "human_notes.experiment_goal", "experiment_goal", multiline=True)
        self._add_line_edit(form, "human_notes.pre_run_note", "pre_run_note", multiline=True)
        self._add_line_edit(form, "human_notes.during_run_note", "during_run_note", multiline=True)
        self._add_line_edit(form, "human_notes.post_run_note", "post_run_note", multiline=True)
        self._add_line_edit(form, "human_notes.interpretation_note", "interpretation_note", multiline=True)
        self._add_bool_combo(form, "status.trust_run", "trust_run")
        self._add_bool_combo(form, "status.repeat_needed", "repeat_needed")
        self._add_bool_combo(form, "status.keep_for_analysis", "keep_for_analysis")
        self._add_bool_combo(form, "status.rejected", "rejected")
        self._add_line_edit(form, "status.rejection_reason", "rejection_reason", multiline=True)
        rejected_widget = self._field_widgets.get("status.rejected")
        if isinstance(rejected_widget, QComboBox):
            rejected_widget.currentIndexChanged.connect(self._on_rejected_changed)
        return box

    def _build_read_only_tab(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel("Acquisition / Motion / Analysis / Provenance (read-only):"))
        self._readonly_text = QPlainTextEdit()
        self._readonly_text.setReadOnly(True)
        self._readonly_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._readonly_text.setFont(self.font())
        layout.addWidget(self._readonly_text, 1)
        return box

    def _add_line_edit(
        self,
        form: QFormLayout,
        key: str,
        label: str,
        *,
        multiline: bool = False,
    ) -> None:
        if multiline:
            w = QPlainTextEdit()
            w.setFixedHeight(72)
        else:
            w = QLineEdit()
        self._field_widgets[key] = w
        form.addRow(label + ":", w)

    def _add_bool_combo(self, form: QFormLayout, key: str, label: str) -> None:
        c = QComboBox()
        c.addItem("unset", None)
        c.addItem("yes", True)
        c.addItem("no", False)
        self._field_widgets[key] = c
        form.addRow(label + ":", c)

    def _on_browse(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select run_protocol.json",
            self._path_edit.text() or "",
            "JSON files (*.json);;All files (*)",
        )
        if selected:
            self._path_edit.setText(selected)

    def _on_load(self) -> None:
        raw = self._path_edit.text().strip()
        if not raw:
            self._set_status("Provide protocol path or run folder.", error=True)
            return
        p = Path(raw)
        try:
            if p.is_dir():
                p = protocol_path_for_run(p)
            self._protocol_data = load_protocol(p)
            self._protocol_path = p
            self._bind_widgets_from_protocol()
            self._set_status(f"Loaded: {p}")
        except Exception as exc:
            self._set_status(f"Load failed: {exc}", error=True)

    def _on_save(self) -> None:
        raw = self._path_edit.text().strip()
        if not raw and self._protocol_path is None:
            self._set_status("Provide protocol path or run folder before save.", error=True)
            return

        target = Path(raw) if raw else self._protocol_path
        assert target is not None
        updates = self._collect_editable_updates()
        try:
            merged = merge_protocol(
                self._protocol_data,
                updates,
                allow_manual_overwrite=True,
            )
            saved_path = save_protocol(merged, target)
            self._protocol_data = load_protocol(saved_path)
            self._protocol_path = saved_path
            self._path_edit.setText(str(saved_path))
            self._bind_widgets_from_protocol()
            self._set_status(f"Saved: {saved_path}")
        except Exception as exc:
            self._set_status(f"Save failed: {exc}", error=True)

    def _collect_editable_updates(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, widget in self._field_widgets.items():
            value: Any
            if isinstance(widget, QLineEdit):
                value = widget.text().strip()
            elif isinstance(widget, QPlainTextEdit):
                value = widget.toPlainText().strip()
            elif isinstance(widget, QComboBox):
                value = widget.currentData(Qt.ItemDataRole.UserRole)
            else:
                continue
            self._set_nested_value(out, key, value)
        return out

    @staticmethod
    def _set_nested_value(out: dict[str, Any], dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        cursor = out
        for part in parts[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[parts[-1]] = value

    def _bind_widgets_from_protocol(self) -> None:
        for key, widget in self._field_widgets.items():
            value = self._get_nested_value(self._protocol_data, key)
            if isinstance(widget, QLineEdit):
                widget.setText("" if value is None else str(value))
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText("" if value is None else str(value))
            elif isinstance(widget, QComboBox):
                if value is True:
                    widget.setCurrentIndex(1)
                elif value is False:
                    widget.setCurrentIndex(2)
                else:
                    widget.setCurrentIndex(0)
        self._on_rejected_changed()

        readonly_payload = {
            "identity": {
                "created_at": self._get_nested_value(self._protocol_data, "identity.created_at"),
                "updated_at": self._get_nested_value(self._protocol_data, "identity.updated_at"),
                "app_version": self._get_nested_value(self._protocol_data, "identity.app_version"),
                "git_branch": self._get_nested_value(self._protocol_data, "identity.git_branch"),
                "git_commit": self._get_nested_value(self._protocol_data, "identity.git_commit"),
            },
            "acquisition": self._protocol_data.get("acquisition", {}),
            "motion": self._protocol_data.get("motion", {}),
            "analysis": self._protocol_data.get("analysis", {}),
            "provenance": self._protocol_data.get("provenance", {}),
        }
        self._readonly_text.setPlainText(
            json.dumps(readonly_payload, indent=2, ensure_ascii=False)
        )

    @staticmethod
    def _get_nested_value(payload: dict[str, Any], dotted_key: str) -> Any:
        cursor: Any = payload
        for part in dotted_key.split("."):
            if not isinstance(cursor, dict):
                return None
            cursor = cursor.get(part)
        return cursor

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self._status.setText(message)
        self._status.setStyleSheet("color: #b00020;" if error else "color: #666;")

    def _on_rejected_changed(self) -> None:
        rejected_widget = self._field_widgets.get("status.rejected")
        reason_widget = self._field_widgets.get("status.rejection_reason")
        if not isinstance(rejected_widget, QComboBox) or reason_widget is None:
            return
        rejected_value = rejected_widget.currentData(Qt.ItemDataRole.UserRole)
        enabled = rejected_value is True
        reason_widget.setEnabled(enabled)
        if not enabled and isinstance(reason_widget, QPlainTextEdit):
            # Keep content intact, only disable editing unless rejected=True.
            reason_widget.setPlaceholderText("Enable by setting rejected = yes.")
        elif isinstance(reason_widget, QPlainTextEdit):
            reason_widget.setPlaceholderText("")
