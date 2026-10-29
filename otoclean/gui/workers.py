"""Uzun işleri (tarama/temizlik) arayüzü dondurmadan arka planda çalıştırır."""

from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal

log = logging.getLogger(__name__)


class TaskThread(QThread):
    """`fn(cancel, status, progress)` fonksiyonunu ayrı thread'de çalıştırır.

    Sinyaller ana thread'e otomatik olarak kuyruklanır; bu yüzden fn içinden
    arayüze doğrudan dokunulmaz, yalnızca status/progress çağrılır.
    """

    status = Signal(str)
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[threading.Event, Callable, Callable], Any],
                 parent=None) -> None:
        super().__init__(parent)
        self._fn = fn
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            result = self._fn(self.cancel_event, self.status.emit, self.progress.emit)
        except Exception as exc:  # Arayüze anlaşılır hata göster, ayrıntıyı logla
            log.error("Arka plan görevi başarısız:\n%s", traceback.format_exc())
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(result)
