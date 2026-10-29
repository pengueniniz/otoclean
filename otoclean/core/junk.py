"""Tek tıkla "Gereksizleri Temizle": neyin gereksiz sayılacağı ve önizleme bilgisi.

Gereksiz = yalnızca 🟢 kategoriler. 🟡 öğeler bu akışa asla girmez; Geri Dönüşüm
Kutusu (kalıcı boşaltır) ve yönetici izni gerektiren konumlar (yönetici değilsek) hariç.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .models import Category, Finding, RiskLevel

log = logging.getLogger(__name__)

# Kategori → (uygulama adı, süreç adları): açıkken önbellek dosyaları kilitli olur
APP_PROCESSES: dict[str, tuple[str, tuple[str, ...]]] = {
    "chrome_cache": ("Google Chrome", ("chrome.exe",)),
    "edge_cache": ("Microsoft Edge", ("msedge.exe",)),
    "brave_cache": ("Brave", ("brave.exe",)),
    "opera_cache": ("Opera", ("opera.exe",)),
    "firefox_cache": ("Firefox", ("firefox.exe",)),
    "vscode_cache": ("VS Code", ("code.exe",)),
    "discord_cache": ("Discord", ("discord.exe",)),
    "teams_cache": ("Microsoft Teams", ("ms-teams.exe", "teams.exe")),
    "spotify_cache": ("Spotify", ("spotify.exe",)),
}


def is_default_junk(finding: Finding, admin: bool) -> bool:
    """Varsayılan olarak seçilen / tek tıkla temizlenen öğe mi?"""
    cat = finding.category
    if cat.risk is not RiskLevel.SAFE or cat.special == "recycle_bin":
        return False
    return admin or not cat.needs_admin


def select_junk(findings: Iterable[Finding], *, admin: bool) -> list[Finding]:
    return [f for f in findings if is_default_junk(f, admin)]


@dataclass(frozen=True)
class JunkGroup:
    category: Category
    count: int
    size: int

    def method(self, *, permanent: bool, use_native: bool) -> str:
        if use_native and self.category.native_cmd:
            return f"`{' '.join(self.category.native_cmd)}` komutu"
        if self.category.special == "recycle_bin":
            return "Kutu boşaltılır (kalıcı)"
        return "Kalıcı silinir" if permanent else "Geri Dönüşüm Kutusu'na taşınır"


def group_junk(findings: Iterable[Finding]) -> list[JunkGroup]:
    """Kategori bazında toplar, büyükten küçüğe sıralar."""
    sizes: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    cats: dict[str, Category] = {}
    for f in findings:
        sizes[f.category.key] += f.size
        counts[f.category.key] += 1
        cats[f.category.key] = f.category
    return sorted((JunkGroup(cats[k], counts[k], sizes[k]) for k in cats),
                  key=lambda g: -g.size)


def _running_process_names() -> set[str]:
    import psutil

    names = set()
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name")
        if name:
            names.add(name.lower())
    return names


def running_blockers(findings: Iterable[Finding], *,
                     process_names: Callable[[], set[str]] = _running_process_names) -> list[str]:
    """Temizlenecek önbellekleri kilitleyen, şu an açık uygulamaların adları."""
    keys = {f.category.key for f in findings}
    wanted = {k: APP_PROCESSES[k] for k in keys if k in APP_PROCESSES}
    if not wanted:
        return []
    try:
        running = process_names()
    except Exception as exc:  # Süreç listesi alınamazsa uyarısız devam et
        log.warning("Çalışan uygulamalar okunamadı: %s", exc)
        return []
    return sorted(name for name, exes in wanted.values() if any(e in running for e in exes))
