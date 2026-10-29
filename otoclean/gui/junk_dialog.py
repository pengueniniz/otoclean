"""'Gereksizleri Temizle' önizlemesi: silmeden önce neyin, nasıl silineceğini gösterir."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..core.junk import JunkGroup
from ..core.models import RiskLevel, human_size
from . import theme

COL_WHAT, COL_COUNT, COL_SIZE, COL_HOW = range(4)


class JunkPreviewDialog(QDialog):
    def __init__(self, groups: list[JunkGroup], *, permanent: bool, use_native: bool,
                 dry_run: bool, excluded_review: int, check_blockers: Callable[[], list[str]],
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gereksizleri Temizle")
        self.setMinimumSize(720, 560)
        self._groups = groups
        self._use_native = use_native
        self._check_blockers = check_blockers
        total = sum(g.size for g in groups)
        count = sum(g.count for g in groups)

        title = QLabel(f"{human_size(total)} gereksiz dosya buldum", objectName="EmptyTitle")
        subtitle = QLabel(
            f"Aşağıdaki {len(groups)} kategorideki {count} öğeyi temizleyeceğim. Bunların hepsi "
            "kendini yeniden oluşturan önbellek ve geçici dosyalar. Kişisel dosyalarına, "
            "🟡 İncele ve 🔴 Dokunma gruplarına dokunmayacağım.", objectName="Muted")
        subtitle.setWordWrap(True)

        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTreeWidget.NoSelection)
        self.table.setHeaderLabels(["NE SİLİNECEK", "ÖĞE", "BOYUT", "NASIL"])
        header = self.table.header()
        header.setSectionResizeMode(COL_WHAT, QHeaderView.Stretch)
        for col, width in ((COL_COUNT, 60), (COL_SIZE, 90), (COL_HOW, 250)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, width)
        for g in groups:
            item = QTreeWidgetItem([g.category.name, str(g.count), human_size(g.size), ""])
            item.setTextAlignment(COL_COUNT, Qt.AlignRight | Qt.AlignVCenter)
            item.setTextAlignment(COL_SIZE, Qt.AlignRight | Qt.AlignVCenter)
            item.setToolTip(COL_WHAT, f"{g.category.why}\nSilersen: {g.category.if_deleted}")
            self.table.addTopLevelItem(item)

        self.blocker_box = QFrame(objectName="Panel")
        fg, bg = theme.risk_fg(RiskLevel.REVIEW), theme.risk_bg(RiskLevel.REVIEW)
        self.blocker_box.setStyleSheet(f"QFrame#Panel {{ background:{bg}; border:1px solid {bg}; }}")
        self.blocker_label = QLabel()
        self.blocker_label.setWordWrap(True)
        self.blocker_label.setStyleSheet(f"color:{fg}; font-weight:600;")
        recheck = QPushButton("Kapattım, tekrar kontrol et")
        recheck.clicked.connect(self._refresh_blockers)
        box_lay = QHBoxLayout(self.blocker_box)
        box_lay.setContentsMargins(14, 10, 10, 10)
        box_lay.addWidget(self.blocker_label, 1)
        box_lay.addWidget(recheck)

        self.permanent_cb = QCheckBox("Kalıcı sil — alan hemen açılır (önerilir; bunlar zaten "
                                      "yeniden oluşan önbellekler)")
        self.permanent_cb.setChecked(permanent)
        self.permanent_cb.toggled.connect(self._refresh_methods)
        notes = []
        if excluded_review:
            notes.append(f"Dahil değil: 🟡 İncele grubundaki {human_size(excluded_review)} — "
                         "onlara sen karar vermelisin.")
        if dry_run:
            notes.append("DENEME MODU açık: hiçbir şey silinmeyecek, sadece hesaplanacak.")
        note = QLabel("\n".join(notes), objectName="Muted")
        note.setWordWrap(True)
        note.setVisible(bool(notes))

        cancel = QPushButton("Vazgeç")
        cancel.clicked.connect(self.reject)
        verb = "Hesapla" if dry_run else "temizle"
        self.go = QPushButton(f"{human_size(total)} {verb}" if not dry_run else "Deneme olarak hesapla",
                              objectName="Hero")
        self.go.clicked.connect(self.accept)
        self.go.setDefault(True)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.go)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(title)
        lay.addWidget(subtitle)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.blocker_box)
        lay.addWidget(self.permanent_cb)
        lay.addWidget(note)
        lay.addLayout(buttons)
        self._refresh_methods()
        self._refresh_blockers()

    @property
    def permanent(self) -> bool:
        return self.permanent_cb.isChecked()

    def _refresh_methods(self) -> None:
        for i, g in enumerate(self._groups):
            text = g.method(permanent=self.permanent, use_native=self._use_native)
            self.table.topLevelItem(i).setText(COL_HOW, text.replace("`", ""))

    def _refresh_blockers(self) -> None:
        apps = self._check_blockers()
        self.blocker_box.setVisible(bool(apps))
        if apps:
            self.blocker_label.setText(
                f"Şu uygulamalar açık: {', '.join(apps)}. Açıkken önbellek dosyaları kilitli "
                "olduğu için bir kısmı atlanır. En iyi sonuç için önce kapat.")
