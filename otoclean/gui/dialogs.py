"""Temizlik onayı ve sonuç pencereleri."""

from __future__ import annotations

from collections import Counter

from PySide6.QtWidgets import QMessageBox, QWidget

from ..core.cleaner import CleanOptions
from ..core.models import CleanResult, Finding, RiskLevel, human_size

MAX_DETAIL_LINES = 300


def confirm_clean(parent: QWidget, findings: list[Finding], options: CleanOptions) -> bool:
    by_risk = Counter()
    sizes = Counter()
    for f in findings:
        by_risk[f.risk] += 1
        sizes[f.risk] += f.size
    lines = [f"{lvl.icon} {lvl.label}: {by_risk[lvl]} öğe, {human_size(sizes[lvl])}"
             for lvl in (RiskLevel.SAFE, RiskLevel.REVIEW) if by_risk[lvl]]
    where = ("🟢 önbellekler KALICI silinir, 🟡 öğeler Geri Dönüşüm Kutusu'na gider."
             if options.permanent_caches else "Her şey Geri Dönüşüm Kutusu'na gönderilir.")
    if any(f.category.special == "recycle_bin" for f in findings):
        where += "\n⚠ Geri Dönüşüm Kutusu boşaltılacak — içindekiler geri alınamaz."
    if options.dry_run:
        where = "DENEME MODU: hiçbir dosya silinmeyecek, sadece ne olacağı hesaplanacak."

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Temizliği onayla")
    box.setText(f"Toplam {human_size(sum(sizes.values()))} temizlenecek.")
    box.setInformativeText("\n".join(lines) + "\n\n" + where)
    box.setDetailedText("\n".join(f.path for f in findings[:MAX_DETAIL_LINES]))
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
    box.button(QMessageBox.Yes).setText("Temizle" if not options.dry_run else "Hesapla")
    box.button(QMessageBox.Cancel).setText("Vazgeç")
    box.setDefaultButton(QMessageBox.Cancel)
    return box.exec() == QMessageBox.Yes


def show_result(parent: QWidget, result: CleanResult) -> None:
    verb = "temizlenebilir" if result.dry_run else "temizlendi"
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle("Temizlik tamamlandı" if not result.dry_run else "Deneme sonucu")
    box.setText(f"{human_size(result.freed)} {verb}.")
    info = f"{len(result.deleted)} öğe işlendi."
    if result.skipped:
        info += f"\n{len(result.skipped)} öğe atlandı (kullanımda, çok yeni veya izin yok)."
        box.setDetailedText("\n".join(f"{p}  →  {why}"
                                      for p, why in result.skipped[:MAX_DETAIL_LINES]))
    box.setInformativeText(info)
    box.exec()
