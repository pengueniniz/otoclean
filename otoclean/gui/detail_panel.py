"""Seçili bulgunun veya kategorinin ayrıntılı açıklaması."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout)

from ..core.models import Category, Finding, RiskLevel, human_size
from . import theme


def _rich(text: str) -> str:
    """Düz metni kaçışlar; `komut` biçimindeki parçaları eş aralıklı yazı yapar."""
    return re.sub(r"`([^`]+)`",
                  lambda m: f"<span style='font-family:\"{theme.FONT_MONO}\"; font-size:9pt;"
                            f" background:{theme.SURFACE_SUNK}'>&nbsp;{m.group(1)}&nbsp;</span>",
                  escape(text))


def _block(title: str, body: str, color: str | None = None) -> str:
    style = f"color:{color};" if color else ""
    return (f"<p style='margin:14px 0 2px 0; color:{theme.INK_FAINT}; font-size:8.5pt;"
            f" font-weight:600; letter-spacing:1px'>{escape(title.upper())}</p>"
            f"<p style='margin:0; {style}'>{_rich(body)}</p>")


class DetailPanel(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(300)
        self._path: str | None = None

        self.badge = QLabel()
        self.title = QLabel("Bir öğe seç")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.PlainText)  # Dosya adları HTML gibi yorumlanmasın
        self.title.setStyleSheet(f"font-family:'{theme.FONT_DISPLAY}'; font-size:14pt; font-weight:700;")
        self.body = QLabel(
            "Soldaki listeden bir kategori veya dosya seçtiğinde neden bu gruba girdiğini "
            "ve silersen ne olacağını burada görürsün.")
        self.body.setObjectName("Muted")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.reveal_btn = QPushButton("Klasörde göster")
        self.reveal_btn.setObjectName("Ghost")
        self.reveal_btn.clicked.connect(self._reveal)
        self.reveal_btn.hide()
        actions = QHBoxLayout()
        actions.addWidget(self.reveal_btn)
        actions.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(self.body)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 12)
        lay.setSpacing(6)
        lay.addWidget(self.badge, alignment=Qt.AlignLeft)
        lay.addWidget(self.title)
        lay.addWidget(scroll, 1)
        lay.addLayout(actions)
        self._set_badge(None)

    def _set_badge(self, level: RiskLevel | None) -> None:
        if level is None:
            self.badge.hide()
            return
        self.badge.show()
        self.badge.setText(f"{level.icon} {level.label.upper()}")
        self.badge.setStyleSheet(
            f"background:{theme.risk_bg(level)}; color:{theme.risk_fg(level)}; font-weight:700;"
            f" font-size:8.5pt; letter-spacing:1px; padding:3px 8px; border-radius:4px;")

    def show_payload(self, payload) -> None:
        if isinstance(payload, Finding):
            self._show_finding(payload)
        elif isinstance(payload, Category):
            self._show_category(payload)

    def _category_html(self, cat: Category) -> str:
        html = _block("Neden bu grupta", cat.why) + _block("Silersen ne olur", cat.if_deleted)
        if cat.advice:
            html += _block("Doğru yöntem", cat.advice, theme.ACCENT)
        if cat.native_cmd:
            html += _block("Temizleme şekli", f"Önce aracın kendi komutu denenir: {' '.join(cat.native_cmd)}")
        if cat.needs_admin:
            html += _block("İzin", "Bu konum yönetici izni ister. Üstteki menüden yönetici olarak yeniden başlat.")
        if cat.auto_ok:
            html += _block("Otomatik", "Haftalık otomatik temizlik bu kategoriyi temizleyebilir.")
        return html

    def _show_category(self, cat: Category) -> None:
        self._path = None
        self.reveal_btn.hide()
        self._set_badge(cat.risk)
        self.title.setText(cat.name)
        self.body.setText(self._category_html(cat))

    def _show_finding(self, f: Finding) -> None:
        self._set_badge(f.risk)
        self.title.setText(os.path.basename(f.path.rstrip("\\")) or f.path
                           if f.path != "::RecycleBin" else "Geri Dönüşüm Kutusu")
        facts = [f"<b>{human_size(f.size)}</b>"]
        if f.file_count > 1:
            facts.append(f"{f.file_count:,} dosya".replace(",", "."))
        if f.last_modified:
            facts.append("son değişiklik " + datetime.fromtimestamp(f.last_modified).strftime("%d.%m.%Y"))
        html = f"<p style='margin:0'>{' · '.join(facts)}</p>"
        if not f.path.startswith("::"):
            html += (f"<p style='margin:6px 0 0 0; font-family:\"{theme.FONT_MONO}\"; font-size:8.5pt;"
                     f" color:{theme.INK_SOFT}'>{escape(f.path)}</p>")
        if f.note:
            html += _block("Not", f.note)
        if f.category.contents_only:
            html += _block("Kapsam", "Klasörün kendisi kalır, yalnızca içindekiler silinir.")
        html += self._category_html(f.category)
        self.body.setText(html)
        self._path = None if f.path.startswith("::") else f.path
        self.reveal_btn.setVisible(self._path is not None)

    def _reveal(self) -> None:
        if not self._path or not os.path.exists(self._path):
            return
        if os.path.isdir(self._path):
            os.startfile(self._path)  # noqa: S606 - kullanıcının kendi klasörünü açar
        else:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self._path)])
