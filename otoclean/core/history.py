"""Temizlik geçmişi (SQLite)."""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass

from .models import CleanResult
from .settings import data_dir

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cleanups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    mode TEXT NOT NULL,
    freed INTEGER NOT NULL,
    deleted_count INTEGER NOT NULL,
    skipped_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cleanup_items (
    cleanup_id INTEGER NOT NULL REFERENCES cleanups(id),
    path TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);
"""


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    ts: float
    mode: str
    freed: int
    deleted_count: int
    skipped_count: int


class History:
    def __init__(self, db_path: str | None = None) -> None:
        self._db = db_path or os.path.join(data_dir(), "history.db")
        try:
            self._init_schema()
        except sqlite3.DatabaseError as exc:
            # Bozuk veritabanı uygulamayı açılmaz hale getirmesin: kenara al, yenisini oluştur
            backup = f"{self._db}.bozuk-{int(time.time())}"
            log.warning("Geçmiş veritabanı bozuk (%s), %s olarak saklanıp yeniden oluşturuluyor",
                        exc, backup)
            os.replace(self._db, backup)
            self._init_schema()

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db)

    def record(self, result: CleanResult, mode: str) -> int:
        """Gerçek (dry-run olmayan) bir temizliği kaydeder ve kimliğini döner."""
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO cleanups (ts, mode, freed, deleted_count, skipped_count) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), mode, result.freed, len(result.deleted), len(result.skipped)))
            cleanup_id = cur.lastrowid
            rows = [(cleanup_id, p, "deleted", None) for p in result.deleted]
            rows += [(cleanup_id, p, "skipped", why) for p, why in result.skipped]
            conn.executemany(
                "INSERT INTO cleanup_items (cleanup_id, path, status, detail) VALUES (?, ?, ?, ?)",
                rows)
        return cleanup_id

    def recent(self, limit: int = 20) -> list[HistoryEntry]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, ts, mode, freed, deleted_count, skipped_count FROM cleanups "
                "ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [HistoryEntry(*row) for row in rows]

    def total_freed(self) -> int:
        with closing(self._connect()) as conn:
            (total,) = conn.execute("SELECT COALESCE(SUM(freed), 0) FROM cleanups").fetchone()
        return int(total)
