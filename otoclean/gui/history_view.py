"""Temizlik geçmişi tablosu."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from ..core.history import History
from ..core.models import human_size

MODE_LABELS = {"manual": "Elle", "auto": "Otomatik"}


class HistoryTable(QTableWidget):
    def __init__(self, history: History, parent=None) -> None:
        super().__init__(0, 5, parent)
        self._history = history
        self.setHorizontalHeaderLabels(["TARİH", "TÜR", "AÇILAN ALAN", "SİLİNEN", "ATLANAN"])
        self.verticalHeader().hide()
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def refresh(self) -> None:
        entries = self._history.recent(50)
        self.setRowCount(len(entries))
        for row, e in enumerate(entries):
            values = [datetime.fromtimestamp(e.ts).strftime("%d.%m.%Y %H:%M"),
                      MODE_LABELS.get(e.mode, e.mode), human_size(e.freed),
                      str(e.deleted_count), str(e.skipped_count)]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.setItem(row, col, item)
