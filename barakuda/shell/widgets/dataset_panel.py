from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from PyQt6.QtCore import pyqtSignal, Qt
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


class DatasetPanel(QWidget):
    item_selected = pyqtSignal(Path)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._items: List[DatasetItem] = []
        self._path_to_item: Dict[str, QListWidgetItem] = {}
        self._item_params: Dict[str, dict] = {}

        title = QLabel("Dataset")
        title.setStyleSheet("font-weight: 600;")

        # Buttons (order: Import -> Select All -> Remove -> Clear)
        self._btn_import = QPushButton("Import Files…")
        self._btn_import.clicked.connect(self._on_import)

        self._btn_import_folder = QPushButton("Import Folder…")
        self._btn_import_folder.clicked.connect(self._on_import_folder)

        self._btn_select_all = QPushButton("Select All")
        self._btn_select_all.clicked.connect(self.select_all)

        self._btn_remove_selected = QPushButton("Remove Selected")
        self._btn_remove_selected.setToolTip("Remove selected items from list (does not delete files from disk)")
        self._btn_remove_selected.clicked.connect(self.remove_selected)

        self._btn_clear_list = QPushButton("Clear List")
        self._btn_clear_list.setToolTip("Clear the entire imported file list (does not delete files from disk)")
        self._btn_clear_list.clicked.connect(self.clear_list)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._btn_import)
        header.addWidget(self._btn_import_folder)
        header.addWidget(self._btn_select_all)
        header.addWidget(self._btn_remove_selected)
        header.addWidget(self._btn_clear_list)

        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setTextElideMode(Qt.TextElideMode.ElideMiddle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(header)
        layout.addWidget(self._list, 1)

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
            if p.is_file() and p.suffix.lower() in _RECURSIVE_IMPORT_EXTS
        ]
        self._add_paths(files)

    def _add_paths(self, paths: List[Path]) -> None:
        for p in paths:
            key = str(Path(p))
            if key in self._path_to_item:
                continue

            self._items.append(DatasetItem(path=Path(p)))

            item = QListWidgetItem(self._format_label(Path(p).name, "idle"))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._list.addItem(item)
            self._path_to_item[key] = item

    def _on_selection_changed(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        p = Path(selected[0].data(Qt.ItemDataRole.UserRole))
        self.item_selected.emit(p)

    def select_all(self) -> None:
        self._list.selectAll()

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

    def set_checked(self, path: Path, checked: bool) -> None:
        it = self._find_item_by_path(path)
        if it:
            it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

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

    def remove_selected(self) -> None:
        """Remove selected items from the list (does not delete files from disk)."""
        selected = self._list.selectedItems()
        if not selected:
            return

        # iterate from end to keep indices stable
        for it in selected:
            key = it.data(Qt.ItemDataRole.UserRole)

            row = self._list.row(it)
            self._list.takeItem(row)

            self._path_to_item.pop(key, None)
            self._item_params.pop(key, None)

            # also remove from _items
            self._items = [d for d in self._items if str(d.path) != key]

    def clear_list(self) -> None:
        """Clear the entire imported file list (does not delete files from disk)."""
        self._list.clear()
        self._items.clear()
        self._path_to_item.clear()
        self._item_params.clear()

    # --- STATUS API (called by MainWindow) ---

    def set_status(self, path: Path, status: str) -> None:
        """
        status: idle | running | done | failed | skipped
        """
        key = str(path)
        item = self._path_to_item.get(key)
        if item is None:
            return
        name = Path(key).name
        item.setText(self._format_label(name, status))

    @staticmethod
    def _format_label(name: str, status: str) -> str:
        icon = {
            "idle": "•",
            "running": "⏳",
            "done": "✅",
            "failed": "❌",
            "skipped": "⚠️",
        }.get(status, "•")
        return f"{icon} {name}"

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
