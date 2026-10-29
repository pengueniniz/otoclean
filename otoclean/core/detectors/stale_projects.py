"""Uzun süredir dokunulmamış projelerdeki yeniden üretilebilir klasörleri bulur."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterable

from ..models import Category, Finding
from ..rules.catalog import STALE_BUILD, STALE_NODE_MODULES, STALE_VENV
from ..scanner import is_reparse_dir, folder_stats

DAY = 86400
MIN_ARTIFACT_SIZE = 1024 * 1024
SKIP_DIRS = frozenset({
    "appdata", "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "windows.old", ".git",
})


def _should_descend(name: str) -> bool:
    lower = name.lower()
    # "program files" içeren klasörler (ör. yedeklenmiş Program Files) uygulama paketidir, proje değil
    return lower not in SKIP_DIRS and not lower.startswith(".") and "program files" not in lower


def _artifact_category(entry: os.DirEntry, parent: str) -> Category | None:
    """Klasör yeniden üretilebilir bir proje çıktısıysa kategorisini döner."""
    name = entry.name.lower()
    if name == "node_modules" and os.path.isfile(os.path.join(parent, "package.json")):
        return STALE_NODE_MODULES
    if name in (".venv", "venv") and os.path.isfile(os.path.join(entry.path, "pyvenv.cfg")):
        return STALE_VENV
    if name == "target" and os.path.isfile(os.path.join(parent, "Cargo.toml")):
        return STALE_BUILD
    if name == ".next" and os.path.isfile(os.path.join(parent, "package.json")):
        return STALE_BUILD
    return None


ACTIVITY_DEPTH = 3
ACTIVITY_MAX_ENTRIES = 5000
NOT_SOURCE = frozenset({"node_modules", ".venv", "venv", "target", ".next", ".git",
                        "__pycache__", "dist", "build"})


def _project_last_touched(project: str, artifact_names: set[str]) -> float:
    """Proje kaynaklarındaki (çıktılar hariç) en yeni değişiklik zamanı.

    Klasör mtime'ı iç içe bir dosya düzenlenince değişmediği için birkaç seviye iner.
    """
    newest = 0.0
    seen = 0
    stack = [(project, 0)]
    while stack and seen < ACTIVITY_MAX_ENTRIES:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            if current == project:
                return time.time()  # Okunamıyorsa aktif say (güvenli taraf)
            continue
        for entry in entries:
            name = entry.name.lower()
            if name in artifact_names or name in NOT_SOURCE:
                continue
            seen += 1
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            newest = max(newest, st.st_mtime)
            if depth < ACTIVITY_DEPTH and entry.is_dir(follow_symlinks=False) \
                    and not is_reparse_dir(entry):
                stack.append((entry.path, depth + 1))
    return newest


def find_stale_artifacts(roots: Iterable[str], *, stale_days: float = 90, max_depth: int = 6,
                         cancel: threading.Event | None = None,
                         now: float | None = None) -> list[Finding]:
    now = time.time() if now is None else now
    findings: list[Finding] = []
    stack = [(os.path.normpath(r), 0) for r in roots if os.path.isdir(r)]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        artifacts = []
        for entry in entries:
            try:
                if not entry.is_dir(follow_symlinks=False) or is_reparse_dir(entry):
                    continue
            except OSError:
                continue
            category = _artifact_category(entry, current)
            if category is not None:
                artifacts.append((entry, category))
            elif depth < max_depth and _should_descend(entry.name):
                stack.append((entry.path, depth + 1))
        if not artifacts:
            continue
        names = {e.name.lower() for e, _ in artifacts}
        last_touched = _project_last_touched(current, names)
        age_days = (now - last_touched) / DAY
        if age_days < stale_days:
            continue
        for entry, category in artifacts:
            stats = folder_stats(entry.path, cancel)
            if stats.size < MIN_ARTIFACT_SIZE:
                continue
            findings.append(Finding(
                path=entry.path, size=stats.size, category=category,
                file_count=stats.file_count, last_modified=last_touched, is_dir=True,
                note=f"Proje {int(age_days)} gündür değişmedi",
            ))
    return findings
