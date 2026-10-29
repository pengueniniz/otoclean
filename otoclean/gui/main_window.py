"""Ana pencere: sürücüler, tarama, bulgular, disk haritası, geçmiş ve temizlik."""

from __future__ import annotations

import logging
import os

import psutil
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter,
                               QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from ..core import junk, scheduler, winapi
from ..core.classifier import dedupe, deep_scan, quick_scan, remeasure, summarize
from ..core.cleaner import Cleaner, CleanOptions
from ..core.history import History
from ..core.models import Finding, RiskLevel, ScanResult, human_size
from ..core.protected import default_policy, is_within, norm
from ..core.settings import load_settings, save_settings
from . import dialogs, theme
from .detail_panel import DetailPanel
from .findings_view import FindingsTree
from .history_view import HistoryTable
from .junk_dialog import JunkPreviewDialog
from .treemap import TreemapWidget
from .widgets import DriveCard, RiskTile, section_label
from .workers import TaskThread

log = logging.getLogger(__name__)
TILE_CAPTIONS = {
    RiskLevel.SAFE: "Silmek güvenli",
    RiskLevel.REVIEW: "Kontrol edip karar ver",
    RiskLevel.DANGER: "Sistem için gerekli — doğru aracı kullan",
}
COMPACT_HEIGHT = 820  # Bundan alçak pencerelerde sıkı yerleşim
QUICK_SCAN_FRESH_SECONDS = 600  # Bu kadar yeni bir tarama varsa "Gereksizleri Temizle" tekrar taramaz


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OtoClean — Akıllı Disk Temizleme")
        self.resize(1280, 860)
        self.setMinimumSize(1040, 700)
        self._policy = default_policy()
        self._history = History()  # Bozuk veritabanını kendisi kurtarır
        self._settings = load_settings()
        self._admin = winapi.is_admin()
        self._quick: list[Finding] = []
        self._deep: list[Finding] = []
        self._task: TaskThread | None = None
        self._risk_filter: RiskLevel | None = None
        self._drive_cards: list[DriveCard] = []
        self._target_drive = os.environ.get("SYSTEMDRIVE", "C:") + "\\"
        self._scan_result: ScanResult | None = None
        self._has_scanned = False
        self._quick_at = 0.0
        self._junk_after_scan = False
        self._schedule_known: bool | None = None
        self._build_ui()

    # ------------------------------------------------------------------ yapı

    def _build_ui(self) -> None:
        """Tüm arayüzü kurar; tema değişince yeniden çağrılır."""
        root = QWidget(objectName="Root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 20, 28, 16)
        layout.setSpacing(12)
        layout.addLayout(self._build_header())
        self.drives_label = section_label("Sürücüler")
        layout.addWidget(self.drives_label)
        self._drives_row = QHBoxLayout()
        layout.addLayout(self._drives_row)
        layout.addLayout(self._build_actions())
        layout.addLayout(self._build_tiles())
        layout.addWidget(self._build_tabs(), 1)
        layout.addLayout(self._build_footer())
        self.setCentralWidget(root)
        self.status_label.setText("Başlamak için Gereksizleri Temizle'ye ya da Hızlı Tara'ya bas.")
        self._refresh_drives()
        self.history_table.refresh()
        self._update_totals()
        self._apply_density()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "subtitle"):
            self._apply_density()

    def _apply_density(self) -> None:
        """Alçak pencerelerde liste için yer açmak üzere ikincil başlıkları gizler."""
        compact = self.height() < COMPACT_HEIGHT
        self.subtitle.setVisible(not compact)
        self.drives_label.setVisible(not compact)
        for tile in self.tiles.values():
            tile.set_compact(compact)
        for card in self._drive_cards:
            card.set_compact(compact)

    def _build_header(self) -> QHBoxLayout:
        title = QLabel("OtoClean", objectName="AppTitle")
        self.subtitle = QLabel("Neyi silebileceğini, neyi silmemen gerektiğini açıklayarak gösterir.",
                               objectName="AppSubtitle")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(title)
        col.addWidget(self.subtitle)
        row = QHBoxLayout()
        row.addLayout(col)
        row.addStretch()
        row.addLayout(self._build_theme_switch(), 0)
        row.addSpacing(10)
        if not self._admin:
            admin_btn = QPushButton("Yönetici olarak yeniden başlat")
            admin_btn.setToolTip("Windows Temp ve Windows Update önbelleği gibi alanlar için gerekir")
            admin_btn.clicked.connect(self._relaunch_admin)
            row.addWidget(admin_btn, alignment=Qt.AlignTop)
        return row

    def _build_theme_switch(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignTop)
        self.theme_buttons: dict[str, QPushButton] = {}
        keys = list(theme.PALETTES)
        for i, key in enumerate(keys):
            btn = QPushButton(theme.PALETTES[key].name, objectName="Segment")
            btn.setCheckable(True)
            btn.setChecked(key == theme.PALETTE.key)
            btn.setProperty("first", "true" if i == 0 else "false")
            btn.setProperty("last", "true" if i == len(keys) - 1 else "false")
            btn.setToolTip(f"{theme.PALETTES[key].name} temasına geç")
            btn.clicked.connect(lambda _=False, k=key: self._switch_theme(k))
            self.theme_buttons[key] = btn
            lay.addWidget(btn)
        return lay

    def _build_actions(self) -> QHBoxLayout:
        self.junk_btn = QPushButton("Gereksizleri Temizle", objectName="Hero")
        self.junk_btn.setToolTip("Tarar, sadece 🟢 güvenli gereksizleri bulur, silmeden önce "
                                 "listeyi gösterip onayını ister")
        self.junk_btn.clicked.connect(self._start_junk)
        self.quick_btn = QPushButton("Hızlı Tara")
        self.quick_btn.setToolTip("Önbellekler, geçici dosyalar, İndirilenler ve eski projeler (~30 sn)")
        self.quick_btn.clicked.connect(self._start_quick)
        self.deep_btn = QPushButton()
        self.deep_btn.setToolTip("Seçili sürücünün tamamı: disk haritası, büyük-eski dosyalar, kopyalar")
        self.deep_btn.clicked.connect(self._start_deep)
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.clicked.connect(self._cancel_task)
        self.cancel_btn.hide()
        self.status_label = QLabel("", objectName="Muted")
        self.status_label.setTextFormat(Qt.PlainText)  # İçinde dosya yolları geçer
        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        self.progress.hide()
        row = QHBoxLayout()
        row.addWidget(self.junk_btn)
        row.addSpacing(6)
        for w in (self.quick_btn, self.deep_btn, self.cancel_btn):
            row.addWidget(w)
        row.addSpacing(12)
        row.addWidget(self.status_label, 1)
        row.addWidget(self.progress)
        self._update_deep_label()
        return row

    def _build_tiles(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.tiles: dict[RiskLevel, RiskTile] = {}
        for level in RiskLevel:
            tile = RiskTile(level, TILE_CAPTIONS[level])
            tile.clicked.connect(lambda lv=level: self._toggle_filter(lv))
            self.tiles[level] = tile
            row.addWidget(tile, 1)
        return row

    def _build_tabs(self) -> QTabWidget:
        self.tree = FindingsTree()
        self.detail = DetailPanel()
        self.tree.current_changed.connect(self.detail.show_payload)
        self.tree.checked_changed.connect(self._update_totals)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.tree)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([860, 340])

        self.treemap = TreemapWidget()
        self.crumb = QLabel("", objectName="Muted")
        self.crumb.setTextFormat(Qt.PlainText)
        self.treemap.path_changed.connect(self.crumb.setText)
        up_btn = QPushButton("↑ Üst klasör")
        up_btn.clicked.connect(self.treemap.go_up)
        legend = QLabel("Yeşil: güvenli · Amber: incele · Kırmızı: korumalı · Gri: sınıflandırılmamış",
                        objectName="Muted")
        map_page = QWidget()
        map_lay = QVBoxLayout(map_page)
        map_lay.setContentsMargins(0, 8, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(up_btn)
        bar.addWidget(self.crumb, 1)
        bar.addWidget(legend)
        map_lay.addLayout(bar)
        map_lay.addWidget(self.treemap, 1)

        self.findings_stack = QStackedWidget()
        self.findings_stack.addWidget(self._build_empty_state())
        self.findings_stack.addWidget(split)

        self.history_table = HistoryTable(self._history)
        tabs = QTabWidget()
        tabs.addTab(self.findings_stack, "Bulgular")
        tabs.addTab(map_page, "Disk Haritası")
        tabs.addTab(self.history_table, "Geçmiş")
        self.tabs = tabs
        return tabs

    def _build_empty_state(self) -> QWidget:
        panel = QFrame(objectName="Panel")
        title = QLabel("Henüz tarama yapılmadı", objectName="EmptyTitle")
        # Satır kaydırmalı etiketler hizalama bayrağıyla eklenince yükseklikleri yanlış
        # hesaplanıyor; bu yüzden sabit genişlikli bir kapsayıcıya konup o ortalanıyor.
        column = QWidget()
        column.setFixedWidth(560)
        col_lay = QVBoxLayout(column)
        col_lay.setContentsMargins(0, 0, 0, 0)
        col_lay.setSpacing(8)
        title.setAlignment(Qt.AlignHCenter)
        col_lay.addWidget(title)
        for text in (
            "<b>Gereksizleri Temizle</b> tek tıkla güvenli önbellek ve geçici dosyaları bulur, "
            "silmeden önce sana listeyi gösterir.",
            "<b>Hızlı Tara</b> her şeyi gruplar halinde listeler; ne silineceğini sen seçersin.",
            "<b>Derin Tara</b> seçili sürücünün tamamını tarar: disk haritası, büyük ve eski "
            "dosyalar, kopyalar.",
        ):
            para = QLabel(text, objectName="Muted")
            para.setWordWrap(True)
            para.setTextFormat(Qt.RichText)
            col_lay.addWidget(para)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(column)
        row.addStretch()
        lay = QVBoxLayout(panel)
        lay.addStretch(2)
        lay.addLayout(row)
        lay.addStretch(3)
        return panel

    def _build_footer(self) -> QHBoxLayout:
        s = self._settings
        self.permanent_cb = QCheckBox("Önbellekleri kalıcı sil (alan hemen açılır)")
        self.permanent_cb.setToolTip("Kapalıyken her şey Geri Dönüşüm Kutusu'na gider ve alan "
                                     "ancak kutu boşaltılınca açılır. 🟡 öğeler her zaman kutuya gider.")
        self.permanent_cb.setChecked(s.permanent_caches)
        self.native_cb = QCheckBox("Araçların kendi komutunu kullan (npm, pip…)")
        self.native_cb.setChecked(s.use_native)
        self.dry_cb = QCheckBox("Deneme modu")
        self.dry_cb.setToolTip("Hiçbir şey silmeden ne kadar yer açılacağını hesapla")
        self.schedule_cb = QCheckBox("Haftalık otomatik güvenli temizlik (Pazar 12:00)")
        self.schedule_cb.setToolTip("Sadece 🟢 ve otomatik işaretli kategoriler; 🟡 asla otomatik silinmez")
        if self._schedule_known is None:
            try:
                self._schedule_known = scheduler.is_enabled()
            except OSError as exc:
                log.warning("Zamanlanmış görev sorgulanamadı: %s", exc)
                self._schedule_known = False
        self.schedule_cb.setChecked(self._schedule_known)
        for cb in (self.permanent_cb, self.native_cb):
            cb.toggled.connect(self._save_settings)
        self.schedule_cb.toggled.connect(self._toggle_schedule)

        self.selected_label = QLabel("", objectName="Muted")
        self.clean_btn = QPushButton("Seçilenleri Temizle", objectName="Primary")
        self.clean_btn.clicked.connect(self._start_clean)
        opts = QGridLayout()
        opts.setHorizontalSpacing(28)
        opts.setVerticalSpacing(6)
        opts.addWidget(self.permanent_cb, 0, 0)
        opts.addWidget(self.native_cb, 0, 1)
        opts.addWidget(self.schedule_cb, 1, 0)
        opts.addWidget(self.dry_cb, 1, 1)
        opts.setColumnStretch(2, 1)
        row = QHBoxLayout()
        row.addLayout(opts, 1)
        row.addWidget(self.selected_label)
        row.addSpacing(10)
        row.addWidget(self.clean_btn)
        return row

    # ------------------------------------------------------------------ sürücüler

    def _refresh_drives(self) -> None:
        while self._drives_row.count():
            item = self._drives_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._drive_cards = []
        try:
            mounts = winapi.fixed_drives()
        except Exception as exc:  # psutil hatası arayüzü düşürmesin
            log.warning("Sürücüler okunamadı: %s", exc)
            mounts = []
        for mount in mounts:
            try:
                usage = psutil.disk_usage(mount)
            except OSError:
                continue
            card = DriveCard(mount, usage.total, usage.used, usage.free)
            card.clicked.connect(lambda m=mount: self._select_drive(m))
            card.set_active(norm(mount) == norm(self._target_drive))
            self._drive_cards.append(card)
            self._drives_row.addWidget(card, 1)
        if hasattr(self, "subtitle"):
            self._apply_density()
        self._update_reclaimable()

    def _select_drive(self, mount: str) -> None:
        self._target_drive = mount
        for card in self._drive_cards:
            card.set_active(norm(card.mount) == norm(mount))
        self._update_deep_label()

    def _update_deep_label(self) -> None:
        self.deep_btn.setText(f"Derin Tara: {self._target_drive.rstrip(chr(92))}")

    def _update_reclaimable(self) -> None:
        checked = self.tree.checked_findings() if hasattr(self, "tree") else []
        for card in self._drive_cards:
            size = sum(f.size for f in checked
                       if not f.path.startswith("::") and is_within(f.path, card.mount))
            card.set_reclaimable(size)

    # ------------------------------------------------------------------ tarama

    def _run_task(self, fn, on_done, label: str) -> None:
        if self._task is not None:
            return
        self._set_busy(True, label)
        task = TaskThread(fn, self)
        task.status.connect(self.status_label.setText)
        task.progress.connect(self._on_progress)
        task.done.connect(on_done)
        task.failed.connect(self._on_failed)
        task.finished.connect(self._on_task_finished)
        task.finished.connect(task.deleteLater)
        self._task = task
        task.start()

    def _set_busy(self, busy: bool, label: str = "") -> None:
        for w in (self.junk_btn, self.quick_btn, self.deep_btn, *self.theme_buttons.values()):
            w.setEnabled(not busy)
        if busy:
            self.clean_btn.setEnabled(False)  # Bitince _update_totals seçime göre açar
        self.cancel_btn.setVisible(busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)
        if label:
            self.status_label.setText(label)

    def _on_progress(self, done: int, total: int, current: str) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            count = f"{done:,}".replace(",", ".")
            self.status_label.setText(f"{count} klasör tarandı · …{current[-60:]}")

    def _on_failed(self, message: str) -> None:
        self._junk_after_scan = False
        QMessageBox.critical(self, "Hata", f"İşlem tamamlanamadı:\n{message}")

    def _on_task_finished(self) -> None:
        self._task = None
        self._set_busy(False)
        self._update_totals()
        if self._junk_after_scan:
            # Görev tamamen bittikten sonra aç: yoksa yeni temizlik görevi başlatılamaz
            self._junk_after_scan = False
            if self._quick_is_fresh():
                QTimer.singleShot(0, self._open_junk_preview)

    def _cancel_task(self) -> None:
        if self._task:
            self._task.cancel()
            self.status_label.setText("İptal ediliyor…")

    def _start_quick(self) -> None:
        policy = self._policy

        def work(cancel, status, _progress):
            findings = quick_scan(policy=policy, cancel=cancel,
                                  status=lambda s: status(f"Taranıyor: {s}"))
            return findings, cancel.is_set()
        self._run_task(work, self._on_quick_task_done, "Hızlı tarama başladı…")

    def _on_quick_task_done(self, payload) -> None:
        findings, cancelled = payload
        if cancelled:
            self._junk_after_scan = False
            self.status_label.setText("Hızlı tarama iptal edildi; önceki sonuçlar korunuyor.")
            return
        self._on_quick_done(findings)

    def _on_quick_done(self, findings: list[Finding]) -> None:
        self._quick = findings
        self._quick_at = time.time()
        self._has_scanned = True
        self._show_findings()
        total = summarize(findings)
        self.status_label.setText(f"Hızlı tarama bitti · {human_size(total[RiskLevel.SAFE])} güvenle silinebilir")

    def _start_deep(self) -> None:
        root, policy = self._target_drive, self._policy

        def work(cancel, status, progress):
            return deep_scan(root, policy=policy, cancel=cancel,
                             progress=lambda d, f, p: progress(d, 0, p), status=status)
        self._run_task(work, self._on_deep_done, f"{root} derin taranıyor…")

    def _on_deep_done(self, payload) -> None:
        result, findings = payload
        if result.cancelled:
            self.status_label.setText("Derin tarama iptal edildi.")
            return
        self._deep = findings
        self._has_scanned = True
        self._scan_result = result
        self._show_findings()
        self.treemap.set_scan(result, self._risk_of_path)
        self.tabs.setCurrentIndex(1)
        self.status_label.setText(
            f"Derin tarama bitti · {result.total_files:,} dosya, {human_size(result.total_size)}"
            .replace(",", ".") + (f" · {len(result.errors)} erişilemeyen yol" if result.errors else ""))

    def _show_findings(self) -> None:
        self.tree.set_findings(dedupe(self._quick + self._deep), admin=self._admin)
        self.tree.set_risk_filter(self._risk_filter)
        self.findings_stack.setCurrentIndex(1 if self._has_scanned else 0)
        self._update_totals()

    def _risk_of_path(self, path: str) -> RiskLevel | None:
        for f in self.tree.all_findings():
            if not f.path.startswith("::") and (is_within(path, f.path) or is_within(f.path, path)):
                return f.risk
        return RiskLevel.DANGER if self._policy.is_protected(path) else None

    # ------------------------------------------------------------------ özet / filtre

    def _toggle_filter(self, level: RiskLevel) -> None:
        self._risk_filter = None if self._risk_filter is level else level
        for lv, tile in self.tiles.items():
            tile.set_active(lv is self._risk_filter)
        self.tree.set_risk_filter(self._risk_filter)
        self.tabs.setCurrentWidget(self.findings_stack)

    def _update_totals(self) -> None:
        all_f = self.tree.all_findings()
        checked = self.tree.checked_findings()
        for level, tile in self.tiles.items():
            if not self._has_scanned:
                tile.set_unscanned()
                continue
            items = [f for f in all_f if f.risk is level]
            tile.set_values(sum(f.size for f in items), len(items),
                            sum(f.size for f in checked if f.risk is level))
        total = sum(f.size for f in checked)
        self.selected_label.setText(f"Seçili: {human_size(total)}" if checked else "Seçili öğe yok")
        self.clean_btn.setEnabled(bool(checked) and self._task is None)
        self._update_reclaimable()

    # ------------------------------------------------------------------ temizlik

    def _options(self) -> CleanOptions:
        return CleanOptions(dry_run=self.dry_cb.isChecked(), use_native=self.native_cb.isChecked(),
                            permanent_caches=self.permanent_cb.isChecked())

    def _start_clean(self) -> None:
        findings = self.tree.checked_findings()
        options = self._options()
        if not findings or not dialogs.confirm_clean(self, findings, options):
            return
        self._execute_clean(findings, options)

    # ---- Gereksizleri Temizle (tek tık) ----

    def _quick_is_fresh(self) -> bool:
        return bool(self._quick_at) and time.time() - self._quick_at < QUICK_SCAN_FRESH_SECONDS

    def _start_junk(self) -> None:
        """Gerekirse önce tarar, sonra önizleme penceresini açar."""
        if self._quick_is_fresh():
            self._open_junk_preview()
            return
        self._start_quick()
        self._junk_after_scan = self._task is not None  # Yalnızca tarama gerçekten başladıysa

    def _open_junk_preview(self) -> None:
        if self._task is not None:
            return  # Arada başka bir işlem başladıysa önizleme açılmasın
        all_findings = self.tree.all_findings()
        selected = junk.select_junk(all_findings, admin=self._admin)
        if not selected:
            QMessageBox.information(self, "Gereksizleri Temizle",
                                    "Temizlenecek güvenli gereksiz dosya bulunamadı. Bilgisayarın temiz!")
            return
        options = self._options()
        review_total = sum(f.size for f in all_findings if f.risk is RiskLevel.REVIEW)
        dialog = JunkPreviewDialog(
            junk.group_junk(selected), permanent=options.permanent_caches,
            use_native=options.use_native, dry_run=options.dry_run, excluded_review=review_total,
            check_blockers=lambda: junk.running_blockers(selected), parent=self)
        if dialog.exec() != JunkPreviewDialog.Accepted:
            self.status_label.setText("Gereksiz temizliği iptal edildi, hiçbir şey silinmedi.")
            return
        if dialog.permanent != self.permanent_cb.isChecked():
            self.permanent_cb.setChecked(dialog.permanent)  # Tercih kaydedilir
        self._execute_clean(selected, self._options())

    def _execute_clean(self, findings: list[Finding], options: CleanOptions) -> None:
        cleaner = Cleaner(self._policy)

        def work(cancel, status, progress):
            result = cleaner.clean(findings, options, cancel=cancel, progress=progress)
            if result.dry_run:
                return result, None
            status("Kalan boyutlar ölçülüyor…")
            # Atlanan/kilitli öğeler listede kalsın diye gerçek durumu yeniden ölç
            return result, (findings, remeasure(findings))
        self._run_task(work, self._on_clean_done, "Temizleniyor…")

    def _on_clean_done(self, payload) -> None:
        result, refreshed = payload
        if refreshed is not None:
            cleaned, still_there = refreshed
            self._apply_remeasured({f.path for f in cleaned}, {f.path: f for f in still_there})
            try:
                self._history.record(result, "manual")
            except Exception:
                log.exception("Temizlik geçmişe yazılamadı")
            self._refresh_drives()
            self.history_table.refresh()
        self.status_label.setText(f"{human_size(result.freed)} "
                                  + ("temizlenebilir (deneme)" if result.dry_run else "temizlendi"))
        dialogs.show_result(self, result)

    def _apply_remeasured(self, cleaned: set[str], current: dict[str, Finding]) -> None:
        def update(items: list[Finding]) -> list[Finding]:
            return [current[f.path] if f.path in current else f
                    for f in items if f.path not in cleaned or f.path in current]
        self._quick = update(self._quick)
        self._deep = update(self._deep)
        self._show_findings()

    # ------------------------------------------------------------------ tema

    def _switch_theme(self, key: str) -> None:
        for k, btn in self.theme_buttons.items():
            btn.setChecked(k == key)  # Segment kontrolü: tıklanan basılı kalsın
        if key == theme.PALETTE.key or self._task is not None:
            return
        self._settings = self._settings.with_changes(theme=key)
        try:
            save_settings(self._settings)
        except OSError as exc:
            log.warning("Tema tercihi kaydedilemedi: %s", exc)
        # Düğme kendi sinyali içindeyken silinmesin diye bir sonraki döngüde yeniden kur
        QTimer.singleShot(0, lambda: self._apply_theme(key))

    def _apply_theme(self, key: str) -> None:
        if self._task is not None:
            return  # Görev arada başladıysa arayüzü onun altından değiştirme
        state = {
            "schedule": self.schedule_cb.isChecked(),
            "checked": self.tree.checked_paths(),
            "tab": self.tabs.currentIndex(),
            "dry": self.dry_cb.isChecked(),
            "status": self.status_label.text(),
            "map_path": self.crumb.text(),
        }
        theme.use(key)
        QApplication.instance().setStyleSheet(theme.STYLESHEET)
        self._schedule_known = state["schedule"]  # schtasks'ı tekrar çağırıp pencereyi dondurma
        self._build_ui()
        if self._has_scanned:
            self._show_findings()
            self.tree.set_checked_paths(state["checked"])
        if self._scan_result is not None:
            self.treemap.set_scan(self._scan_result, self._risk_of_path)
            if self.treemap.has_path(state["map_path"]):
                self.treemap.navigate(state["map_path"])
        for lv, tile in self.tiles.items():
            tile.set_active(lv is self._risk_filter)
        self.dry_cb.setChecked(state["dry"])
        self.tabs.setCurrentIndex(state["tab"])
        self.status_label.setText(state["status"])
        self._update_totals()

    # ------------------------------------------------------------------ ayarlar

    def _save_settings(self) -> None:
        self._settings = self._settings.with_changes(
            permanent_caches=self.permanent_cb.isChecked(), use_native=self.native_cb.isChecked())
        try:
            save_settings(self._settings)
        except OSError as exc:
            QMessageBox.warning(self, "Ayarlar", f"Ayarlar kaydedilemedi: {exc}")

    def _toggle_schedule(self, on: bool) -> None:
        try:
            if on:
                scheduler.enable(self._settings.schedule_day, self._settings.schedule_time)
            else:
                scheduler.disable()
        except (RuntimeError, ValueError, OSError) as exc:
            self.schedule_cb.blockSignals(True)
            self.schedule_cb.setChecked(not on)
            self.schedule_cb.blockSignals(False)
            QMessageBox.warning(self, "Zamanlanmış görev", str(exc))
            return
        self._schedule_known = on
        self.status_label.setText("Haftalık otomatik temizlik " + ("açıldı." if on else "kapatıldı."))

    def _relaunch_admin(self) -> None:
        if winapi.relaunch_as_admin([]):
            self.close()

    def closeEvent(self, event) -> None:
        task = self._task
        if task is not None and not task.wait(0):
            # Silme yarıda kesilmesin: iptal iste, görev güvenli noktada bitince kapan
            task.cancel()
            self.status_label.setText("Kapanıyor: devam eden işlem güvenli şekilde durduruluyor…")
            task.finished.connect(self.close)
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)
