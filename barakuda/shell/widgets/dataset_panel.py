from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from PyQt6.QtCore import pyqtSignal, Qt, QDir
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QLabel,
    QStyle,
    QSizePolicy,
    QMessageBox,
    QListView,
    QTreeView,
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QCheckBox,
)

from barakuda.core.models import DatasetItem

_DIRECT_IMPORT_FILTER = (
    "Data files (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.csv *.txt *.mp4 *.avi *.mov *.mkv *.m4v *.spm *.raw *.json);;"
    "All files (*.*)"
)
_RECURSIVE_IMPORT_EXTS = {
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
    ".csv", ".txt",
    ".mp4", ".avi", ".mov", ".mkv", ".m4v",
    ".spm", ".raw",
}
_PRIMARY_IMPORT_EXTS = {
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
    ".mp4", ".avi", ".mov", ".mkv", ".m4v",
    ".spm", ".raw",
}
_OT_SIDECAR_SUFFIXES = (
    "_timestamps.csv",
    "_meta.json",
    "_qc.json",
    "_stage.json",
    "_stage_trace.csv",
)


def discover_importable_paths_from_roots(roots: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        item_jsons = sorted(root.rglob("item.json"))
        if item_jsons:
            for p in item_jsons:
                key = str(p.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(p)
            continue
        for p in sorted(root.rglob("*")):
            if not is_primary_dataset_input(p):
                continue
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def is_primary_dataset_input(path: Path) -> bool:
    if not path.is_file():
        return False
    low_name = path.name.lower()
    if low_name.endswith(_OT_SIDECAR_SUFFIXES):
        return False
    return path.suffix.lower() in _PRIMARY_IMPORT_EXTS


def detect_sidecar_status_for_input(path: Path) -> str:
    stem = path.stem
    parent = path.parent
    has_timestamps = (parent / f"{stem}_timestamps.csv").is_file()
    has_meta = (parent / f"{stem}_meta.json").is_file()
    has_qc = (parent / f"{stem}_qc.json").is_file()
    has_stage = (parent / f"{stem}_stage.json").is_file()
    has_stage_trace = (parent / f"{stem}_stage_trace.csv").is_file()
    if not has_timestamps:
        return "timing missing"
    return (
        f"timestamps {'✓' if has_timestamps else '-'} / "
        f"meta {'✓' if has_meta else '-'} / "
        f"qc {'✓' if has_qc else '-'} / "
        f"stage {'✓' if has_stage else '-'} / "
        f"trace {'✓' if has_stage_trace else '-'}"
    )


def discover_subfolders(parent: Path) -> list[Path]:
    if not parent.exists() or not parent.is_dir():
        return []
    return sorted(
        [p for p in parent.iterdir() if p.is_dir()],
        key=lambda p: str(p).lower(),
    )


def _folder_kind_tag(name: str) -> str:
    low = name.lower()
    if "brown" in low:
        return "brown"
    if "drag" in low:
        return "drag"
    return "unknown"


def build_subfolder_preview(folder: Path) -> tuple[str, int, str]:
    name = folder.name
    files = discover_importable_paths_from_roots([folder])
    return name, len(files), _folder_kind_tag(name)


def discover_from_parent_selected_subfolders(parent: Path, selected_subfolders: list[str]) -> list[Path]:
    _ = parent
    roots = [Path(p) for p in selected_subfolders if Path(p).is_dir()]
    return discover_importable_paths_from_roots(roots)


def summarize_master_check_state(flags: list[bool]) -> str:
    if not flags:
        return "unchecked"
    checked = sum(1 for f in flags if f)
    if checked == 0:
        return "unchecked"
    if checked == len(flags):
        return "checked"
    return "partial"


def remove_checked_state(
    ordered_keys: list[str],
    checked_map: dict[str, bool],
    current_key: str | None,
) -> tuple[list[str], str | None]:
    remaining = [k for k in ordered_keys if not bool(checked_map.get(k, False))]
    if not remaining:
        return [], None
    if current_key in remaining:
        return remaining, current_key
    return remaining, remaining[0]


class SubfolderSelectionDialog(QDialog):
    def __init__(self, parent_folder: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Select subfolders from: {parent_folder.name}")
        self.resize(760, 560)
        self._parent_folder = parent_folder
        self._rows: list[tuple[QListWidgetItem, str]] = []
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)

        for folder in discover_subfolders(parent_folder):
            name, count, kind = build_subfolder_preview(folder)
            label = f"{name}  ({kind}, files: {count})"
            it = QListWidgetItem(label)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, str(folder))
            self._list.addItem(it)
            self._rows.append((it, f"{name} {kind}".lower()))

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter folders (e.g. brown, drag, rep02)…")
        self._filter.textChanged.connect(self._on_filter_changed)

        self._btn_all = QPushButton("Check all")
        self._btn_none = QPushButton("Clear")
        self._btn_all.clicked.connect(self._check_all)
        self._btn_none.clicked.connect(self._check_none)
        actions = QHBoxLayout()
        actions.addWidget(self._btn_all)
        actions.addWidget(self._btn_none)
        actions.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._filter)
        layout.addLayout(actions)
        layout.addWidget(self._list, 1)
        layout.addWidget(buttons)

    def _check_all(self) -> None:
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Checked)

    def _check_none(self) -> None:
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _on_filter_changed(self, text: str) -> None:
        needle = text.strip().lower()
        for item, token in self._rows:
            item.setHidden(bool(needle) and needle not in token)

    def selected_folders(self) -> list[str]:
        out: list[str] = []
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(str(it.data(Qt.ItemDataRole.UserRole)))
        return out


class DatasetPanel(QWidget):
    item_selected = pyqtSignal(Path)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._items: List[DatasetItem] = []
        self._path_to_item: Dict[str, QListWidgetItem] = {}
        self._item_params: Dict[str, dict] = {}
        self._item_status: Dict[str, str] = {}
        self._item_pairing_status: Dict[str, str] = {}
        self._item_sidecar_status: Dict[str, str] = {}
        self._current_path_key: str | None = None

        # Buttons (order: Import -> Remove)
        self._btn_import = QPushButton("Import Files…")
        self._btn_import.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_import.setToolTip("Import individual data files into the dataset list.")
        self._btn_import.clicked.connect(self._on_import)

        self._btn_import_folder = QPushButton("Import Folder…")
        self._btn_import_folder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_import_folder.setToolTip("Import all supported files (or item.json manifests) from a folder.")
        self._btn_import_folder.clicked.connect(self._on_import_folder)
        self._btn_import_folders_recursive = QPushButton("Add from parent folder…")
        self._btn_import_folders_recursive.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_import_folders_recursive.setToolTip(
            "Pick one parent folder, then choose multiple subfolders in an internal checklist."
        )
        self._btn_import_folders_recursive.clicked.connect(self._on_import_folders_recursive)

        self._btn_remove_checked = QPushButton("Remove checked")
        self._btn_remove_checked.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._btn_remove_checked.setToolTip("Remove checked items from list (does not delete files from disk)")
        self._btn_remove_checked.clicked.connect(self.remove_checked)

        header = QHBoxLayout()
        header.addWidget(self._btn_import)
        header.addWidget(self._btn_import_folder)
        header.addWidget(self._btn_import_folders_recursive)
        header.addWidget(self._btn_remove_checked)

        self._master_checked = QCheckBox("Batch include all")
        self._master_checked.setTristate(True)
        self._master_checked.setToolTip("Check/uncheck all run items for batch. Partial = mixed state.")
        self._master_checked.stateChanged.connect(self._on_master_checked_changed)

        self._list = QListWidget()
        self.setMinimumWidth(260)
        self._list.setMinimumWidth(220)
        self._list.setToolTip(
            "Dataset items used for Preview Gate and batch runs.\n"
            "Checkbox = included in checked-path workflows."
        )
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setTextElideMode(Qt.TextElideMode.ElideMiddle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(header)
        layout.addWidget(self._master_checked)
        layout.addWidget(self._list, 1)
        self._sync_master_checkbox_state()
        self._sync_remove_checked_enabled()

    def _on_import(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select data files",
            "",
            _DIRECT_IMPORT_FILTER,
        )
        if not files:
            return

        self._add_paths([Path(f) for f in files])

    def _on_import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder to import", "")
        if not folder:
            return
        root = Path(folder)
        item_jsons = sorted(root.rglob("item.json"))
        if item_jsons:
            self._add_paths(item_jsons)
            return
        files = [
            p for p in sorted(root.rglob("*"))
            if is_primary_dataset_input(p)
        ]
        self._add_paths(files)

    def _on_import_folders_recursive(self) -> None:
        parent_folder = QFileDialog.getExistingDirectory(self, "Select parent folder", "")
        if not parent_folder:
            return
        parent_path = Path(parent_folder)
        dlg = SubfolderSelectionDialog(parent_path, self)
        if dlg.exec() != int(QDialog.DialogCode.Accepted):
            return
        selected = dlg.selected_folders()
        if not selected:
            return
        paths = discover_from_parent_selected_subfolders(parent_path, selected)
        self._add_paths(paths)

    def _add_paths(self, paths: List[Path]) -> None:
        for p in paths:
            key = str(Path(p))
            if key in self._path_to_item:
                continue

            self._items.append(DatasetItem(path=Path(p)))
            self._item_status[key] = "idle"
            self._item_sidecar_status[key] = detect_sidecar_status_for_input(Path(p))

            item = QListWidgetItem(
                self._format_label(
                    Path(p).name,
                    "idle",
                    None,
                    self._item_sidecar_status.get(key),
                )
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._list.addItem(item)
            self._path_to_item[key] = item
        self._sync_master_checkbox_state()
        self._sync_remove_checked_enabled()
        if self._current_path_key is None and self._list.count() > 0:
            first = self._list.item(0)
            if first is not None:
                self._list.setCurrentItem(first)

    def _on_selection_changed(self) -> None:
        current = self._list.currentItem()
        if current is None:
            return
        p = Path(current.data(Qt.ItemDataRole.UserRole))
        self.item_selected.emit(p)

    def _on_current_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        _ = previous
        if current is None:
            self._current_path_key = None
            return
        self._current_path_key = str(current.data(Qt.ItemDataRole.UserRole))
        self.item_selected.emit(Path(self._current_path_key))

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        self._sync_master_checkbox_state()
        self._sync_remove_checked_enabled()

    def get_selected_paths(self) -> List[Path]:
        selected = self._list.selectedItems()
        return [Path(it.data(Qt.ItemDataRole.UserRole)) for it in selected]

    def get_checked_paths(self) -> List[Path]:
        paths = []
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                paths.append(Path(it.data(Qt.ItemDataRole.UserRole)))
        return paths

    def get_current_path(self) -> Path | None:
        if not self._current_path_key:
            return None
        return Path(self._current_path_key)

    def set_checked(self, path: Path, checked: bool) -> None:
        it = self._find_item_by_path(path)
        if it:
            it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._sync_master_checkbox_state()

    def set_pairing_status(self, path: Path | str, pairing_status: str | None) -> None:
        key = str(Path(path))
        if pairing_status:
            self._item_pairing_status[key] = str(pairing_status)
        else:
            self._item_pairing_status.pop(key, None)
        self._refresh_item_text_by_key(key)

    def get_all_items(self) -> List[Dict]:
        res = []
        for i in range(self._list.count()):
            it = self._list.item(i)
            res.append({
                "path": str(it.data(Qt.ItemDataRole.UserRole)),
                "checked": (it.checkState() == Qt.CheckState.Checked),
                "text": it.text()
            })
        return res

    # --- PER-ITEM PARAMS API ---

    def get_item_params(self, path: Path | str) -> dict | None:
        key = str(Path(path))
        return self._item_params.get(key)

    def set_item_params(self, path: Path | str, params: dict) -> None:
        key = str(Path(path))
        self._item_params[key] = params

    def has_item(self, path: Path | str) -> bool:
        key = str(Path(path))
        return key in self._path_to_item

    # --- List item removal (files on disk are not affected) ---

    def remove_checked(self) -> None:
        """Remove checked items from the list (does not delete files from disk)."""
        checked_items = []
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                checked_items.append(it)
        if not checked_items:
            return

        # iterate from end to keep indices stable
        for it in checked_items:
            key = it.data(Qt.ItemDataRole.UserRole)

            row = self._list.row(it)
            self._list.takeItem(row)

            self._path_to_item.pop(key, None)
            self._item_params.pop(key, None)
            self._item_status.pop(key, None)
            self._item_pairing_status.pop(key, None)
            self._item_sidecar_status.pop(key, None)
            if self._current_path_key == key:
                self._current_path_key = None

            # also remove from _items
            self._items = [d for d in self._items if str(d.path) != key]
        if self._current_path_key is None and self._list.count() > 0:
            self._list.setCurrentItem(self._list.item(0))
        self._sync_master_checkbox_state()
        self._sync_remove_checked_enabled()

    def remove_selected(self) -> None:
        """Legacy alias kept for compatibility. Uses checked-items semantics."""
        self.remove_checked()

    def clear_list(self) -> None:
        """Clear the entire imported file list (does not delete files from disk)."""
        self._list.clear()
        self._items.clear()
        self._path_to_item.clear()
        self._item_params.clear()
        self._item_status.clear()
        self._item_pairing_status.clear()
        self._item_sidecar_status.clear()
        self._current_path_key = None
        self._sync_master_checkbox_state()
        self._sync_remove_checked_enabled()

    # --- STATUS API (called by MainWindow) ---

    def set_status(self, path: Path, status: str) -> None:
        """
        status: idle | running | done | failed | skipped
        """
        key = str(path)
        item = self._path_to_item.get(key)
        if item is None:
            return
        self._item_status[key] = str(status)
        self._refresh_item_text_by_key(key)

    @staticmethod
    def _format_label(name: str, status: str, pairing_status: str | None, sidecar_status: str | None) -> str:
        icon = {
            "idle": "•",
            "running": "⏳",
            "done": "✅",
            "failed": "❌",
            "skipped": "⚠️",
            "stopped": "⏹",
        }.get(status, "•")
        sidecar_suffix = f" | {sidecar_status}" if sidecar_status else ""
        pairing_suffix = f" [{pairing_status}]" if pairing_status else ""
        return f"{icon} {name}{sidecar_suffix}{pairing_suffix}"

    def _refresh_item_text_by_key(self, key: str) -> None:
        item = self._path_to_item.get(key)
        if item is None:
            return
        name = Path(key).name
        status = self._item_status.get(key, "idle")
        pairing_status = self._item_pairing_status.get(key)
        sidecar_status = self._item_sidecar_status.get(key)
        item.setText(self._format_label(name, status, pairing_status, sidecar_status))
        self._sync_master_checkbox_state()

    def _on_master_checked_changed(self, state: int) -> None:
        if self._list.count() == 0:
            return
        target_checked = state != int(Qt.CheckState.Unchecked)
        for i in range(self._list.count()):
            it = self._list.item(i)
            it.setCheckState(Qt.CheckState.Checked if target_checked else Qt.CheckState.Unchecked)
        self._sync_master_checkbox_state()
        self._sync_remove_checked_enabled()

    def _sync_master_checkbox_state(self) -> None:
        flags = []
        for i in range(self._list.count()):
            it = self._list.item(i)
            flags.append(it.checkState() == Qt.CheckState.Checked)
        state = summarize_master_check_state(flags)
        self._master_checked.blockSignals(True)
        if state == "checked":
            self._master_checked.setCheckState(Qt.CheckState.Checked)
        elif state == "partial":
            self._master_checked.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self._master_checked.setCheckState(Qt.CheckState.Unchecked)
        self._master_checked.blockSignals(False)

    def _sync_remove_checked_enabled(self) -> None:
        any_checked = any(
            self._list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self._list.count())
        )
        self._btn_remove_checked.setEnabled(any_checked)

    def configure_for_device(self, device_id: str) -> None:
        is_ot = str(device_id) == "optical_tweezers"
        self._btn_import_folders_recursive.setVisible(is_ot)
        self._btn_import.setVisible(not is_ot)
        self._btn_import_folder.setVisible(not is_ot)

    # --- GATE RESULT API (called by MainWindow) ---

    def _find_item_by_path(self, path: Path):
        p = str(Path(path))
        for i in range(self._list.count()):
            it = self._list.item(i)
            if str(it.data(Qt.ItemDataRole.UserRole)) == p:
                return it
        return None

    def set_gate_result(self, path: Path, passed: bool | None, reason: str = "") -> None:
        """
        passed:
          True  -> PASS (green/check icon)
          False -> FAIL (red/error icon)
          None  -> UNKNOWN (no icon)
        """
        item = self._find_item_by_path(path)
        if item is None:
            return

        if passed is True:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
            item.setIcon(icon)
            item.setToolTip("Preview Gate: PASS")
        elif passed is False:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
            item.setIcon(icon)
            msg = "Preview Gate: FAIL"
            if reason:
                msg += f"\n{reason}"
            item.setToolTip(msg)
        else:
            item.setIcon(QIcon())
            item.setToolTip("")

