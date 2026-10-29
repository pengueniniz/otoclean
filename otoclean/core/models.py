"""Uygulama genelinde kullanılan değişmez (frozen) veri modelleri."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    SAFE = "safe"      # 🟢 Silmek güvenli
    REVIEW = "review"  # 🟡 Kullanıcı incelemeli
    DANGER = "danger"  # 🔴 Silinmemeli

    @property
    def label(self) -> str:
        return {
            RiskLevel.SAFE: "Güvenli",
            RiskLevel.REVIEW: "İncele",
            RiskLevel.DANGER: "Dokunma",
        }[self]

    @property
    def icon(self) -> str:
        return {RiskLevel.SAFE: "🟢", RiskLevel.REVIEW: "🟡", RiskLevel.DANGER: "🔴"}[self]

    @property
    def order(self) -> int:
        return {RiskLevel.SAFE: 0, RiskLevel.REVIEW: 1, RiskLevel.DANGER: 2}[self]


@dataclass(frozen=True)
class Category:
    """Bir bulgu grubunun açıklaması (ör. 'npm önbelleği')."""

    key: str
    name: str
    risk: RiskLevel
    why: str                       # Neden bu risk seviyesinde
    if_deleted: str                # Silinirse ne olur
    auto_ok: bool = False          # Zamanlanmış görev otomatik silebilir mi
    native_cmd: tuple[str, ...] | None = None  # Varsa aracın kendi temizleme komutu
    advice: str | None = None      # 🔴 için önerilen doğru araç
    needs_admin: bool = False
    contents_only: bool = False    # Klasörün kendisi değil sadece içi silinir
    min_age_days: float = 0        # Bundan yeni dosyalara dokunulmaz (ör. kullanımda temp)
    special: str | None = None     # Özel işlem (ör. "recycle_bin")


@dataclass(frozen=True)
class Finding:
    """Silinebilir (veya bilinçli olarak korunan) tek bir yol."""

    path: str
    size: int
    category: Category
    file_count: int = 1
    last_access: float | None = None
    last_modified: float | None = None
    is_dir: bool = False
    note: str | None = None
    group_id: str | None = None    # Kopya dosya grupları için

    @property
    def risk(self) -> RiskLevel:
        return self.category.risk

    @property
    def selectable(self) -> bool:
        return self.category.risk is not RiskLevel.DANGER


@dataclass(frozen=True)
class DirStat:
    """Bir klasörün toplam boyutu (treemap ve dedektörler için)."""

    path: str
    size: int
    file_count: int
    last_modified: float


@dataclass(frozen=True)
class ScanResult:
    root: str
    dirs: tuple[DirStat, ...] = ()
    large_files: tuple[tuple[str, int, float, float], ...] = ()  # (yol, boyut, atime, mtime)
    errors: tuple[str, ...] = ()
    cancelled: bool = False
    total_size: int = 0
    total_files: int = 0


@dataclass(frozen=True)
class CleanResult:
    freed: int = 0
    deleted: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()  # (yol, sebep)
    dry_run: bool = False
    extra: dict = field(default_factory=dict)


def human_size(num: float) -> str:
    """Byte değerini okunur metne çevirir (Türkçe ondalık virgülüyle)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            text = f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
            return text.replace(".", ",")
        num /= 1024
    return f"{num:.1f} TB"
