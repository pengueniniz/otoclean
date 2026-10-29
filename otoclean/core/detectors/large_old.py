"""Büyük ve uzun süredir kullanılmayan dosyaları bulur."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable

from ..models import Finding
from ..protected import ProtectionPolicy
from ..rules.catalog import LARGE_OLD

DAY = 86400
DEFAULT_MIN_SIZE = 500 * 1024 * 1024


def _created(path: str) -> float | None:
    try:
        return os.stat(path).st_ctime
    except OSError:
        return None


def find_large_old(files: Iterable[tuple[str, int, float, float]], policy: ProtectionPolicy, *,
                   min_size: int = DEFAULT_MIN_SIZE, days: float = 180,
                   now: float | None = None) -> list[Finding]:
    """`files`: (yol, boyut, atime, mtime). Korumalı yollar atlanır.

    Windows'ta ctime oluşturma zamanıdır: yakın zamanda kopyalanmış eski tarihli bir dosya
    "kullanılmıyor" sayılmasın diye o da hesaba katılır.
    """
    now = time.time() if now is None else now
    findings = []
    for path, size, atime, mtime in files:
        if size < min_size:
            continue
        created = _created(path)
        if created is None:
            continue
        last_used = max(atime, mtime, created)
        age = (now - last_used) / DAY
        if age < days or policy.is_protected(path):
            continue
        findings.append(Finding(
            path=path, size=size, category=LARGE_OLD, last_access=atime,
            last_modified=mtime, note=f"{int(age)} gündür kullanılmamış",
        ))
    return findings
