from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QLabel,
)

from barakuda.core.models import DatasetItem


class DatasetPanel(QWidget):
    item_selected = pyqtSignal(Path)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._items: List[DatasetItem] = []
        self._path_to_item: Dict[str, QListWidgetItem] = {}

        title = QLabel("Dataset")
        title.setStyleSheet("font-weight: 600;")

        # TLAČÍTKA (pořadí: Import -> Select All -> Remove -> Clear)
        self._btn_import = QPushButton("Import Files…")
        self._btn_import.clicked.connect(self._on_import)

        self._btn_select_all = QPushButton("Select All")
        self._btn_select_all.clicked.connect(self.select_all)

        self._btn_remove_selected = QPushButton("Remove Selected")
        self._btn_remove_selected.setToolTip("Odstraní označené položky ze seznamu (nesahá na disk)")
        self._btn_remove_selected.clicked.connect(self.remove_selected)

        self._btn_clear_list = QPushButton("Clear List")
        self._btn_clear_list.setToolTip("Vymaže celý seznam importovaných položek (nesahá na disk)")
        self._btn_clear_list.clicked.connect(self.clear_list)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._btn_import)
        header.addWidget(self._btn_select_all)
        header.addWidget(self._btn_remove_selected)
        header.addWidget(self._btn_clear_list)

        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(header)
        layout.addWidget(self._list, 1)

    def _on_import(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select data files",
            "",
            "Data files (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.csv *.txt *.mp4 *.avi);;All files (*.*)",
        )
        if not files:
            return

        for f in files:
            p = Path(f)
            key = str(p)

            # zabrání duplicitám
            if key in self._path_to_item:
                continue

            self._items.append(DatasetItem(path=p))

            item = QListWidgetItem(self._format_label(p.name, "idle"))
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

    # --- NOVÉ: mazání z listu (bez smazání souborů na disku) ---

    def remove_selected(self) -> None:
        """Odstraní vybrané položky ze seznamu (nesahá na disk)."""
        selected = self._list.selectedItems()
        if not selected:
            return

        # postup od konce kvůli indexům
        for it in selected:
            key = it.data(Qt.ItemDataRole.UserRole)

            row = self._list.row(it)
            self._list.takeItem(row)

            self._path_to_item.pop(key, None)

            # smaž i z _items
            self._items = [d for d in self._items if str(d.path) != key]

    def clear_list(self) -> None:
        """Vymaže celý seznam importovaných položek (nesahá na disk)."""
        self._list.clear()
        self._items.clear()
        self._path_to_item.clear()

    # --- STATUS API (volá MainWindow) ---

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
