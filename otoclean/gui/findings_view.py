"""Risk → kategori → öğe şeklinde gruplanmış, onay kutulu bulgu ağacı."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from html import escape

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTreeWidget, QTreeWidgetItem

from ..core.junk import is_default_junk
from ..core.models import Category, Finding, RiskLevel, human_size
from . import theme

ROLE_PAYLOAD = Qt.UserRole
COL_NAME, COL_SIZE, COL_DATE, COL_NOTE = range(4)


# 🟢 öğeler varsayılan seçilidir; yönetici gerektirenler ve kalıcı silenler hariç
default_checked = is_default_junk


def _date(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y") if ts else ""


def _display_name(f: Finding) -> str:
    return "Geri Dönüşüm Kutusu" if f.path == "::RecycleBin" else f.path


class FindingsTree(QTreeWidget):
    checked_changed = Signal()
    current_changed = Signal(object)  # Finding | Category | None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHeaderLabels(["ÖĞE", "BOYUT", "DEĞİŞTİ", "NOT"])
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAnimated(True)
        self.setIndentation(18)
        self.setTextElideMode(Qt.ElideMiddle)  # Uzun yollarda dosya adı görünür kalsın
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col, width in ((COL_SIZE, 88), (COL_DATE, 88), (COL_NOTE, 190)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.setColumnWidth(col, width)
        self._emit_timer = QTimer(self, singleShot=True, interval=0)
        self._emit_timer.timeout.connect(self.checked_changed.emit)
        self.itemChanged.connect(lambda *_: self._emit_timer.start())
        self.currentItemChanged.connect(self._on_current)
        self._risk_items: dict[RiskLevel, QTreeWidgetItem] = {}

    # ---- veri ----

    def set_findings(self, findings: list[Finding], *, admin: bool) -> None:
        self.blockSignals(True)
        self.clear()
        self._risk_items = {}
        by_risk: dict[RiskLevel, dict[str, list[Finding]]] = defaultdict(lambda: defaultdict(list))
        cats: dict[str, Category] = {}
        for f in findings:
            by_risk[f.risk][f.category.key].append(f)
            cats[f.category.key] = f.category

        for level in RiskLevel:
            groups = by_risk.get(level)
            if not groups:
                continue
            risk_item = self._make_risk_item(level, groups)
            for key in sorted(groups, key=lambda k: -sum(f.size for f in groups[k])):
                self._make_category_item(risk_item, cats[key], groups[key], admin)
            risk_item.setExpanded(level is not RiskLevel.DANGER)
        self.blockSignals(False)
        self.checked_changed.emit()

    def _make_risk_item(self, level: RiskLevel, groups: dict) -> QTreeWidgetItem:
        total = sum(f.size for fs in groups.values() for f in fs)
        item = QTreeWidgetItem(self, [f"{level.icon}  {level.label}", human_size(total), "", ""])
        font = QFont(theme.FONT_DISPLAY, 11, QFont.Bold)
        item.setFont(COL_NAME, font)
        item.setFont(COL_SIZE, font)
        item.setForeground(COL_NAME, QBrush(QColor(theme.risk_fg(level))))
        item.setTextAlignment(COL_SIZE, Qt.AlignRight | Qt.AlignVCenter)
        item.setFirstColumnSpanned(False)
        item.setData(COL_NAME, ROLE_PAYLOAD, None)
        item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
        self._risk_items[level] = item
        return item

    def _make_category_item(self, parent: QTreeWidgetItem, cat: Category,
                            findings: list[Finding], admin: bool) -> None:
        total = sum(f.size for f in findings)
        note = "yönetici izni gerekir" if cat.needs_admin and not admin else ""
        if cat.native_cmd:
            note = (note + " · " if note else "") + f"komut: {cat.native_cmd[0]}"
        item = QTreeWidgetItem(parent, [f"{cat.name}  ({len(findings)})", human_size(total), "", note])
        item.setFont(COL_NAME, QFont(theme.FONT_UI, 10, QFont.DemiBold))
        item.setTextAlignment(COL_SIZE, Qt.AlignRight | Qt.AlignVCenter)
        item.setData(COL_NAME, ROLE_PAYLOAD, cat)
        selectable = cat.risk is not RiskLevel.DANGER
        if selectable:
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
        else:
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
        for f in sorted(findings, key=lambda x: -x.size):
            child = QTreeWidgetItem(item, [_display_name(f), human_size(f.size),
                                           _date(f.last_modified), f.note or ""])
            child.setTextAlignment(COL_SIZE, Qt.AlignRight | Qt.AlignVCenter)
            child.setData(COL_NAME, ROLE_PAYLOAD, f)
            child.setToolTip(COL_NAME, f"<span>{escape(f.path)}</span>")
            if f.note:
                child.setToolTip(COL_NOTE, f"<span>{escape(f.note)}</span>")
            if selectable:
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(COL_NAME, Qt.Checked if default_checked(f, admin) else Qt.Unchecked)
            else:
                child.setFlags(child.flags() & ~Qt.ItemIsUserCheckable)
                child.setForeground(COL_NAME, QBrush(QColor(theme.INK_SOFT)))

    # ---- sorgular ----

    def _iter_findings(self):
        for i in range(self.topLevelItemCount()):
            risk_item = self.topLevelItem(i)
            for j in range(risk_item.childCount()):
                cat_item = risk_item.child(j)
                for k in range(cat_item.childCount()):
                    yield cat_item.child(k)

    def all_findings(self) -> list[Finding]:
        return [it.data(COL_NAME, ROLE_PAYLOAD) for it in self._iter_findings()]

    def checked_findings(self) -> list[Finding]:
        result = []
        for it in self._iter_findings():
            f: Finding = it.data(COL_NAME, ROLE_PAYLOAD)
            if (f.selectable and it.flags() & Qt.ItemIsUserCheckable
                    and it.checkState(COL_NAME) == Qt.Checked):
                result.append(f)
        return result

    def checked_paths(self) -> set[str]:
        return {f.path for f in self.checked_findings()}

    def set_checked_paths(self, paths: set[str]) -> None:
        """Seçimi yol kümesine göre geri yükler (ör. tema değişince)."""
        for it in self._iter_findings():
            f: Finding = it.data(COL_NAME, ROLE_PAYLOAD)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(COL_NAME, Qt.Checked if f.path in paths else Qt.Unchecked)

    def set_all_checked(self, level: RiskLevel, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for it in self._iter_findings():
            f: Finding = it.data(COL_NAME, ROLE_PAYLOAD)
            if f.risk is level and it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(COL_NAME, state)

    def set_risk_filter(self, level: RiskLevel | None) -> None:
        for lvl, item in self._risk_items.items():
            item.setHidden(level is not None and lvl is not level)
            if level is not None and lvl is level:
                item.setExpanded(True)

    def _on_current(self, current: QTreeWidgetItem | None, _prev) -> None:
        payload = current.data(COL_NAME, ROLE_PAYLOAD) if current else None
        self.current_changed.emit(payload)
