"""Küçük, yeniden kullanılabilir arayüz parçaları."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..core.models import RiskLevel, human_size
from . import theme


class UsageBar(QWidget):
    """Dolu alan (mürekkep) + içinden geri kazanılabilecek kısım (yeşil) çubuğu."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._used = 0.0
        self._reclaim = 0.0
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_values(self, used_ratio: float, reclaim_ratio: float) -> None:
        self._used = max(0.0, min(1.0, used_ratio))
        self._reclaim = max(0.0, min(self._used, reclaim_ratio))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 4, 4)
        p.setClipPath(clip)
        p.fillRect(r, QColor(theme.SURFACE_SUNK))
        used_w = r.width() * self._used
        danger = self._used > 0.9
        p.fillRect(QRectF(0, 0, used_w, r.height()),
                   QColor(theme.risk_fg(RiskLevel.DANGER) if danger else theme.INK_SOFT))
        if self._reclaim > 0:
            rw = r.width() * self._reclaim
            p.fillRect(QRectF(used_w - rw, 0, rw, r.height()),
                       QColor(theme.risk_fg(RiskLevel.SAFE)))
        p.end()


class ClickableCard(QFrame):
    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class DriveCard(ClickableCard):
    """Bir sürücünün doluluğu; tıklanınca derin tarama hedefi olarak seçilir."""

    def __init__(self, mount: str, total: int, used: int, free: int, parent=None) -> None:
        super().__init__(parent)
        self.mount = mount
        self._total = total
        self._used = used
        self.setMinimumWidth(190)
        self.setToolTip(f"{mount} sürücüsünü derin tarama için seç")

        letter = QLabel(mount.rstrip("\\"))
        letter.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}'; font-size:16pt; font-weight:700;")
        pct = used / total if total else 0
        pct_label = QLabel(f"%{pct * 100:.0f}")
        color = theme.risk_fg(RiskLevel.DANGER) if pct > 0.9 else theme.INK_SOFT
        pct_label.setStyleSheet(f"color:{color}; font-weight:700;")
        top = QHBoxLayout()
        top.addWidget(letter)
        top.addStretch()
        top.addWidget(pct_label)

        self.bar = UsageBar()
        self.bar.set_values(pct, 0)
        self.free_label = QLabel(f"{human_size(free)} boş · {human_size(total)}")
        self.free_label.setObjectName("Muted")
        self.reclaim_label = QLabel("")
        self.reclaim_label.setStyleSheet(
            f"color:{theme.risk_fg(RiskLevel.SAFE)}; font-weight:600; font-size:9pt;")
        self.reclaim_label.hide()

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 12, 14, 12)
        self._lay.setSpacing(6)
        self._lay.addLayout(top)
        self._lay.addWidget(self.bar)
        self._lay.addWidget(self.free_label)
        self._lay.addWidget(self.reclaim_label)

    def set_compact(self, compact: bool) -> None:
        self._lay.setContentsMargins(14, 7, 14, 7) if compact else self._lay.setContentsMargins(14, 12, 14, 12)
        self._lay.setSpacing(3 if compact else 6)

    def set_reclaimable(self, size: int) -> None:
        ratio = size / self._total if self._total else 0
        self.bar.set_values(self._used / self._total if self._total else 0, ratio)
        self.reclaim_label.setText(f"+{human_size(size)} açılabilir" if size else "")
        self.reclaim_label.setVisible(bool(size))


class RiskTile(ClickableCard):
    """Bir risk seviyesinin toplamı; tıklanınca listeyi o seviyeye filtreler."""

    def __init__(self, level: RiskLevel, caption: str, parent=None) -> None:
        super().__init__(parent)
        self.level = level
        fg, bg = theme.risk_fg(level), theme.risk_bg(level)
        self.setStyleSheet(
            f"QFrame#Card {{ background:{bg}; border:1px solid {bg}; border-radius:10px; }}"
            f"QFrame#Card[active='true'] {{ border:2px solid {fg}; }}")

        name = QLabel(f"{level.label.upper()}")
        name.setStyleSheet(f"color:{fg}; font-size:8.5pt; font-weight:700; letter-spacing:1.4px;")
        self._fg = fg
        self.amount = QLabel("—")
        self.detail = QLabel(caption)
        self.detail.setStyleSheet(f"color:{theme.INK_SOFT}; font-size:9pt;")
        self.detail.setWordWrap(True)
        self.setToolTip(f"{caption}. Listeyi bu seviyeye göre filtrelemek için tıkla.")

        self._lay = QVBoxLayout(self)
        self._lay.setSpacing(2)
        self._lay.addWidget(name)
        self._lay.addWidget(self.amount)
        self._lay.addWidget(self.detail)
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        size = 18 if compact else 24
        self.amount.setStyleSheet(
            f"color:{self._fg}; font-family:'{theme.FONT_DISPLAY}'; font-size:{size}pt; font-weight:700;")
        margin = 8 if compact else 12
        self._lay.setContentsMargins(16, margin, 16, margin)

    def set_unscanned(self) -> None:
        self.amount.setText("—")
        self.detail.setText("Henüz taranmadı")

    def set_values(self, total: int, count: int, selected: int | None = None) -> None:
        self.amount.setText(human_size(total) if count else "0 B")
        parts = [f"{count} öğe"]
        if selected is not None and self.level is not RiskLevel.DANGER:
            parts.append(f"{human_size(selected)} seçili")
        self.detail.setText(" · ".join(parts))


def section_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("SectionLabel")
    return label
