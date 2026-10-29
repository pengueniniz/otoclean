"""İçeriği birebir aynı olan dosyaları bulur.

Aşamalar: boyuta göre grupla → ilk 64 KB hash → tam hash. Hardlink'ler (aynı
fiziksel dosya) kopya sayılmaz çünkü silmek yer açmaz.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable

from ..fsutil import is_cloud_only
from ..models import Finding
from ..protected import ProtectionPolicy
from ..rules.catalog import DUPLICATES

DEFAULT_MIN_SIZE = 10 * 1024 * 1024
HEAD_BYTES = 64 * 1024
CHUNK = 4 * 1024 * 1024


def _hash(path: str, limit: int | None, cancel: threading.Event | None,
          on_read: Callable[[int], None] | None = None) -> str | None:
    digest = hashlib.blake2b(digest_size=20)
    remaining = limit
    try:
        with open(path, "rb") as fh:
            while True:
                if cancel is not None and cancel.is_set():
                    return None
                size = CHUNK if remaining is None else min(CHUNK, remaining)
                if size <= 0:
                    break
                block = fh.read(size)
                if not block:
                    break
                digest.update(block)
                if on_read:
                    on_read(len(block))
                if remaining is not None:
                    remaining -= len(block)
    except OSError:
        return None
    return digest.hexdigest()


def _sample_hash(path: str, size: int) -> str | None:
    """Dosyanın başından, ortasından ve sonundan 64 KB'lık örneklerin hash'i."""
    digest = hashlib.blake2b(digest_size=20)
    offsets = sorted({0, max(0, size // 2 - HEAD_BYTES // 2), max(0, size - HEAD_BYTES)})
    try:
        with open(path, "rb") as fh:
            for offset in offsets:
                fh.seek(offset)
                digest.update(fh.read(HEAD_BYTES))
    except OSError:
        return None
    return digest.hexdigest()


def _group_by(paths: list[str], key_fn) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        key = key_fn(path)
        if key is not None:
            groups[key].append(path)
    return [g for g in groups.values() if len(g) > 1]


def _drop_hardlinks(paths: list[str]) -> list[str]:
    """Hardlink'leri tekilleştirir; yalnızca bulutta duran dosyaları (indirmeyi tetiklememek için) atar."""
    seen: dict[tuple[int, int], str] = {}
    for path in paths:
        try:
            st = os.stat(path)
        except OSError:
            continue
        if is_cloud_only(st):
            continue
        seen.setdefault((st.st_dev, st.st_ino), path)
    return list(seen.values())


def find_duplicates(files: Iterable[tuple[str, int, float, float]], policy: ProtectionPolicy, *,
                    min_size: int = DEFAULT_MIN_SIZE,
                    cancel: threading.Event | None = None,
                    progress: Callable[[int, int], None] | None = None,
                    originals_out: set[str] | None = None) -> list[Finding]:
    """Kopyaları bulur. `progress(okunan, toplam)` tam doğrulama sırasında byte bazında çağrılır.
    `originals_out` verilirse her grupta tutulan asıl kopyanın yolu buna eklenir."""
    by_size: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for path, size, _atime, mtime in files:
        if size >= min_size:
            by_size[size].append((path, mtime))
    mtimes = {p: m for group in by_size.values() for p, m in group}

    # 1) Ucuz eleme: boyut → hardlink → örnek hash
    candidates: list[tuple[int, list[str]]] = []
    for size, entries in by_size.items():
        if len(entries) < 2:
            continue
        unique = _drop_hardlinks([p for p, _ in entries])
        for group in _group_by(unique, lambda p, s=size: _sample_hash(p, s)):
            candidates.append((size, group))
        if cancel is not None and cancel.is_set():
            return []

    # 2) Kesin doğrulama: tam içerik hash'i
    total = sum(size * len(group) for size, group in candidates)
    read = [0]

    def on_read(n: int) -> None:
        read[0] += n
        if progress:
            progress(read[0], total)

    findings: list[Finding] = []
    for size, group in candidates:
        for same in _group_by(group, lambda p: _hash(p, None, cancel, on_read)):
            if cancel is not None and cancel.is_set():
                return findings
            original, dups = _group_findings(same, size, mtimes, policy)
            if originals_out is not None:
                originals_out.add(original)
            findings.extend(dups)
    return findings


def _group_findings(group: list[str], size: int, mtimes: dict[str, float],
                    policy: ProtectionPolicy) -> tuple[str, list[Finding]]:
    """Grupta tutulacak asıl kopyayı seçer; (asıl, diğerlerinin bulguları) döner."""
    def keep_rank(p: str) -> tuple:
        return (not policy.is_protected(p), p.count(os.sep), mtimes.get(p, 0.0), p)

    ordered = sorted(group, key=keep_rank)
    original = ordered[0]
    group_id = hashlib.blake2b(original.encode(), digest_size=6).hexdigest()
    return original, [
        Finding(path=p, size=size, category=DUPLICATES, last_modified=mtimes.get(p),
                note=f"Asıl kopya: {original}", group_id=group_id)
        for p in ordered[1:] if not policy.is_protected(p)
    ]
