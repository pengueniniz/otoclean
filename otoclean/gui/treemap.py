"""Derin tarama sonucundaki klasörlerin 'squarified' kutu haritası.

Kutu alanı = klasör boyutu. Renk = o klasörün risk durumu (güvenli/incele/korumalı)
ya da nötr. Tıkla: içine gir; sağ tık veya Geri: üst klasör.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..core.models import DirStat, RiskLevel, ScanResult, human_size
from . import theme

Rect = tuple[float, float, float, float]
OTHER = "::other"
MAX_BOXES = 60


def _worst(row: list[float], short: float) -> float:
    s = sum(row)
    return max(max(row) * short * short / (s * s), (s * s) / (short * short * min(row)))


def squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[Rect]:
    """Büyükten küçüğe sıralı değerleri en kareye yakın dikdörtgenlere böler."""
    total = sum(values)
    if total <= 0 or w <= 0 or h <= 0:
        return []
    scaled = [v * w * h / total for v in values if v > 0]
    rects: list[Rect] = []
    while scaled:
        short = min(w, h)
        row = [scaled[0]]
        i = 1
        while i < len(scaled) and _worst(row + [scaled[i]], short) <= _worst(row, short):
            row.append(scaled[i])
            i += 1
        s = sum(row)
        if w >= h:
            col_w = s / h
            yy = y
            for v in row:
                rects.append((x, yy, col_w, v / col_w))
                yy += v / col_w
            x, w = x + col_w, w - col_w
        else:
            row_h = s / w
            xx = x
            for v in row:
                rects.append((xx, y, v / row_h, row_h))
                xx += v / row_h
            y, h = y + row_h, h - row_h
        scaled = scaled[i:]
    return rects


class TreemapWidget(QWidget):
    path_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(320)
        self._by_parent: dict[str, list[DirStat]] = {}
        self._sizes: dict[str, int] = {}
        self._root: str | None = None
        self._current: str | None = None
        self._boxes: list[tuple[QRectF, str, int]] = []
        self._color_fn: Callable[[str], RiskLevel | None] = lambda _p: None

    def set_scan(self, result: ScanResult, color_fn: Callable[[str], RiskLevel | None]) -> None:
        self._color_fn = color_fn
        self._by_parent = {}
        root = os.path.normpath(result.root)
        self._sizes = {root: result.total_size}
        for d in result.dirs:
            parent = os.path.dirname(d.path)
            if os.path.normpath(d.path) == root or parent == d.path:
                continue  # Sürücü kökünün dirname'i kendisidir; kendi çocuğu olmasın
            self._sizes[d.path] = d.size
            self._by_parent.setdefault(parent, []).append(d)
        self._root = root
        self.navigate(self._root)

    def has_path(self, path: str) -> bool:
        return path in self._sizes

    def navigate(self, path: str) -> None:
        self._current = path
        self.path_changed.emit(path)
        self._relayout()

    def go_up(self) -> None:
        if self._current and self._root and self._current != self._root:
            self.navigate(os.path.dirname(self._current))

    def _children(self) -> list[tuple[str, int]]:
        kids = sorted(self._by_parent.get(self._current or "", []), key=lambda d: -d.size)
        items = [(d.path, d.size) for d in kids[:MAX_BOXES]]
        rest = self._sizes.get(self._current or "", 0) - sum(s for _, s in items)
        if rest > 0:
            items.append((OTHER, rest))
        return sorted(items, key=lambda t: -t[1])

    def _relayout(self) -> None:
        items = self._children()
        r = self.rect().adjusted(1, 1, -1, -1)
        rects = squarify([s for _, s in items], r.x(), r.y(), r.width(), r.height())
        self._boxes = [(QRectF(*rc), p, s) for rc, (p, s) in zip(rects, items)]
        self.update()

    def resizeEvent(self, event) -> None:
        self._relayout()
        super().resizeEvent(event)

    def _fill(self, path: str) -> QColor:
        if path == OTHER:
            return QColor(theme.SURFACE_SUNK)
        level = self._color_fn(path)
        if level is None:
            return QColor(theme.MAP_NEUTRAL)
        return QColor(theme.risk_bg(level)).darker(108)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.SURFACE))
        if not self._boxes:
            p.setPen(QColor(theme.INK_SOFT))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Disk haritası için bir sürücü seçip 'Derin Tara'ya bas.")
            p.end()
            return
        name_font = QFont(theme.FONT_UI, 9, QFont.DemiBold)
        size_font = QFont(theme.FONT_UI, 8)
        for rect, path, size in self._boxes:
            box = rect.adjusted(1.5, 1.5, -1.5, -1.5)
            p.setPen(QPen(QColor(theme.SURFACE), 1))
            p.setBrush(self._fill(path))
            p.drawRoundedRect(box, 4, 4)
            if box.width() < 60 or box.height() < 34:
                continue
            name = "Diğer / dosyalar" if path == OTHER else os.path.basename(path)
            level = None if path == OTHER else self._color_fn(path)
            p.setPen(QColor(theme.risk_fg(level)) if level else QColor(theme.INK))
            text_rect = box.adjusted(8, 6, -8, -6)
            p.setFont(name_font)
            p.drawText(text_rect, Qt.AlignLeft | Qt.AlignTop,
                       p.fontMetrics().elidedText(name, Qt.ElideRight, int(text_rect.width())))
            p.setFont(size_font)
            p.setPen(QColor(theme.INK_SOFT))
            p.drawText(text_rect.adjusted(0, 16, 0, 0), Qt.AlignLeft | Qt.AlignTop, human_size(size))
        p.end()

    def _box_at(self, pos) -> tuple[QRectF, str, int] | None:
        for box in self._boxes:
            if box[0].contains(pos):
                return box
        return None

    def mouseMoveEvent(self, event) -> None:
        hit = self._box_at(event.position())
        if hit:
            _, path, size = hit
            label = "Bu klasördeki dosyalar ve küçük klasörler" if path == OTHER else path
            QToolTip.showText(event.globalPosition().toPoint(), f"{label}\n{human_size(size)}", self)
            self.setCursor(Qt.PointingHandCursor if path in self._by_parent else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            self.go_up()
            return
        hit = self._box_at(event.position())
        if hit and hit[1] in self._by_parent:
            self.navigate(hit[1])
