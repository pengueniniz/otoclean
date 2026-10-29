"""Giriş noktası.

    otoclean                 → masaüstü uygulaması
    otoclean --auto-safe     → arayüzsüz haftalık güvenli temizlik (zamanlanmış görev)
    otoclean --schedule on   → haftalık görevi kur / off: kaldır
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .core.settings import data_dir


def _setup_logging() -> None:
    try:
        handler: logging.Handler = logging.FileHandler(
            os.path.join(data_dir(), "otoclean.log"), encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()  # Profil klasörü yazılamıyorsa yine de çalış
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[handler])


def _notify(title: str, message: str) -> None:
    """Windows bildirim alanında kısa bir balon gösterir; masaüstü yoksa sessizce geçer."""
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QStyle, QSystemTrayIcon

        app = QApplication.instance() or QApplication(sys.argv)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(app.style().standardIcon(QStyle.SP_TrashIcon))
        tray.show()
        tray.showMessage(title, message, QSystemTrayIcon.Information, 8000)
        QTimer.singleShot(9000, app.quit)
        app.exec()
        tray.hide()
    except Exception:  # Bildirim isteğe bağlı; temizlik sonucunu etkilemesin
        logging.exception("Bildirim gösterilemedi")


def run_auto() -> int:
    from .core.auto import run_auto_safe
    from .core.models import human_size

    try:
        result = run_auto_safe()
    except Exception:
        logging.exception("Otomatik temizlik başarısız")
        _notify("OtoClean", "Otomatik temizlik başarısız oldu. Ayrıntılar günlükte.")
        return 1
    if result.freed > 0:
        _notify("OtoClean", f"Haftalık temizlik: {human_size(result.freed)} yer açıldı.")
    return 0


def run_schedule(state: str) -> int:
    from .core import scheduler
    from .core.settings import load_settings

    s = load_settings()
    if state == "on":
        scheduler.enable(s.schedule_day, s.schedule_time)
    else:
        scheduler.disable()
    logging.info("Zamanlanmış görev: %s", state)
    return 0


def run_gui() -> int:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from .core.settings import load_settings
    from .gui import theme
    from .gui.main_window import MainWindow

    theme.use(load_settings().theme)
    app = QApplication(sys.argv)
    app.setApplicationName("OtoClean")
    app.setFont(QFont(theme.FONT_UI, 10))
    app.setStyleSheet(theme.STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="otoclean", description="Akıllı disk temizleme")
    parser.add_argument("--auto-safe", action="store_true", help="Arayüzsüz güvenli temizlik")
    parser.add_argument("--schedule", choices=("on", "off"), help="Haftalık görevi kur/kaldır")
    args = parser.parse_args(argv)
    _setup_logging()
    if args.auto_safe:
        return run_auto()
    if args.schedule:
        return run_schedule(args.schedule)
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
