"""İndirilenler klasöründeki eski kurulum dosyalarını ve unutulmuş dosyaları bulur."""

from __future__ import annotations

import os
import threading
import time

from ..models import Finding
from ..rules.catalog import OLD_DOWNLOADS, OLD_INSTALLERS
from ..scanner import is_reparse_dir, folder_stats

DAY = 86400
INSTALLER_EXTS = frozenset({
    ".exe", ".msi", ".msix", ".msixbundle", ".appx", ".iso", ".img",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".xz", ".cab", ".dmg", ".apk",
})


def find_old_downloads(folder: str, *, installer_days: float = 30, other_days: float = 180,
                       cancel: threading.Event | None = None,
                       now: float | None = None) -> list[Finding]:
    now = time.time() if now is None else now
    findings: list[Finding] = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return findings
    for entry in entries:
        if cancel is not None and cancel.is_set():
            break
        try:
            if entry.is_dir(follow_symlinks=False):
                if is_reparse_dir(entry):
                    continue
                stats = folder_stats(entry.path, cancel)
                size, count, mtime, is_dir = stats.size, stats.file_count, stats.last_modified, True
                mtime = max(mtime, entry.stat(follow_symlinks=False).st_mtime)
            else:
                st = entry.stat(follow_symlinks=False)
                size, count, mtime, is_dir = st.st_size, 1, st.st_mtime, False
        except OSError:
            continue
        age = (now - mtime) / DAY
        ext = os.path.splitext(entry.name)[1].lower()
        if not is_dir and ext in INSTALLER_EXTS and age >= installer_days:
            category = OLD_INSTALLERS
        elif age >= other_days:
            category = OLD_DOWNLOADS
        else:
            continue
        findings.append(Finding(
            path=entry.path, size=size, category=category, file_count=count,
            last_modified=mtime, is_dir=is_dir, note=f"{int(age)} gün önce indirildi/değişti",
        ))
    return findings
