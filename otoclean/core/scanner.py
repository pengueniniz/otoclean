"""Hızlı, iptal edilebilir dosya sistemi taraması.

- Sembolik bağlantı ve junction (reparse point) klasörleri asla takip edilmez;
  böylece aynı veri iki kez sayılmaz ve sonsuz döngüye girilmez.
- Kökün alt klasörleri bir thread havuzunda paralel taranır (os.scandir GIL'i bırakır).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .fsutil import is_link_stat
from .models import DirStat, ScanResult

DEFAULT_LARGE_FILE = 200 * 1024 * 1024
DEFAULT_MIN_DIR = 50 * 1024 * 1024
MAX_ERRORS = 500
PROGRESS_EVERY = 250

ProgressFn = Callable[[int, int, str], None]  # (taranan klasör, taranan dosya, mevcut yol)


class _Progress:
    """Thread'ler arası paylaşılan sayaç; geri çağırmayı seyrek tetikler."""

    def __init__(self, callback: ProgressFn | None) -> None:
        self._cb = callback
        self._lock = threading.Lock()
        self.dirs = 0
        self.files = 0

    def tick(self, files: int, current: str) -> None:
        with self._lock:
            self.dirs += 1
            self.files += files
            should_emit = self._cb is not None and self.dirs % PROGRESS_EVERY == 0
            dirs, total_files = self.dirs, self.files
        if should_emit:
            self._cb(dirs, total_files, current)


def is_reparse_dir(entry: os.DirEntry) -> bool:
    """Klasör bir junction/symlink mi? (OneDrive bulut klasörleri bağlantı sayılmaz.)"""
    try:
        if entry.is_symlink():
            return True
        return is_link_stat(os.lstat(entry.path))
    except OSError:
        return True


def _walk(top: str, cancel: threading.Event | None, large_threshold: int,
          progress: _Progress) -> tuple[dict, list, list]:
    """Tek bir alt ağacı tarar. Klasör başına (doğrudan boyut, dosya sayısı, son mtime) döner."""
    direct: dict[str, list] = {}
    large: list[tuple[str, int, float, float]] = []
    errors: list[str] = []
    stack = [top]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        current = stack.pop()
        acc = direct.setdefault(current, [0, 0, 0.0])
        files_here = 0
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not is_reparse_dir(entry):
                                stack.append(entry.path)
                            continue
                        if entry.is_symlink():
                            continue
                        st = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        if len(errors) < MAX_ERRORS:
                            errors.append(f"{entry.path}: {exc.strerror or exc}")
                        continue
                    acc[0] += st.st_size
                    acc[1] += 1
                    acc[2] = max(acc[2], st.st_mtime)
                    files_here += 1
                    if st.st_size >= large_threshold:
                        large.append((entry.path, st.st_size, st.st_atime, st.st_mtime))
        except OSError as exc:
            if len(errors) < MAX_ERRORS:
                errors.append(f"{current}: {exc.strerror or exc}")
        progress.tick(files_here, current)
    return direct, large, errors


def _aggregate(direct: dict[str, list], root: str) -> dict[str, list]:
    """Doğrudan boyutları üst klasörlere yayarak toplam boyutları hesaplar."""
    totals = {path: list(vals) for path, vals in direct.items()}
    root_key = os.path.normpath(root)
    for path in sorted(totals, key=len, reverse=True):
        if os.path.normpath(path) == root_key:
            continue
        parent = os.path.dirname(path)
        if parent in totals and parent != path:
            p = totals[parent]
            c = totals[path]
            p[0] += c[0]
            p[1] += c[1]
            p[2] = max(p[2], c[2])
    return totals


def scan_tree(root: str, *, cancel: threading.Event | None = None,
              progress: ProgressFn | None = None,
              large_threshold: int = DEFAULT_LARGE_FILE,
              min_dir_size: int = DEFAULT_MIN_DIR,
              workers: int = 8) -> ScanResult:
    """`root` altını tarar; büyük klasörleri ve büyük dosyaları döner."""
    root = os.path.normpath(root)
    prog = _Progress(progress)
    direct: dict[str, list] = {root: [0, 0, 0.0]}
    large: list = []
    errors: list[str] = []
    subdirs: list[str] = []

    try:
        with os.scandir(root) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if not is_reparse_dir(entry):
                            subdirs.append(entry.path)
                        continue
                    if entry.is_symlink():
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    errors.append(f"{entry.path}: {exc.strerror or exc}")
                    continue
                acc = direct[root]
                acc[0] += st.st_size
                acc[1] += 1
                acc[2] = max(acc[2], st.st_mtime)
                if st.st_size >= large_threshold:
                    large.append((entry.path, st.st_size, st.st_atime, st.st_mtime))
    except OSError as exc:
        return ScanResult(root=root, errors=(f"{root}: {exc.strerror or exc}",))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for d, lg, er in pool.map(lambda s: _walk(s, cancel, large_threshold, prog), subdirs):
            direct.update(d)
            large.extend(lg)
            errors.extend(er[: max(0, MAX_ERRORS - len(errors))])

    totals = _aggregate(direct, root)
    dirs = sorted(
        (DirStat(p, v[0], v[1], v[2]) for p, v in totals.items() if v[0] >= min_dir_size),
        key=lambda d: d.size, reverse=True,
    )
    root_total = totals.get(root, [0, 0, 0.0])
    return ScanResult(
        root=root,
        dirs=tuple(dirs),
        large_files=tuple(sorted(large, key=lambda x: x[1], reverse=True)),
        errors=tuple(errors),
        cancelled=bool(cancel is not None and cancel.is_set()),
        total_size=root_total[0],
        total_files=root_total[1],
    )


def folder_stats(path: str, cancel: threading.Event | None = None) -> DirStat:
    """Bir klasörün toplam boyutu, dosya sayısı ve en son değişiklik zamanı."""
    if os.path.isfile(path):
        st = os.stat(path)
        return DirStat(path, st.st_size, 1, st.st_mtime)
    direct, _, _ = _walk(path, cancel, 1 << 62, _Progress(None))
    size = sum(v[0] for v in direct.values())
    count = sum(v[1] for v in direct.values())
    mtime = max((v[2] for v in direct.values()), default=0.0)
    return DirStat(path, size, count, mtime)
