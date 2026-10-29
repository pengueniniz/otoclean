"""Seçilen bulguları güvenli şekilde siler.

Kurallar:
- 🔴 bulgular ve korumalı yollar asla silinmez (sınıflandırmadan bağımsız 2. kontrol).
- Silme anında yolda junction/symlink varsa veya gerçek konum korumalıysa silinmez.
- Tarama sonrası boyutu/tarihi değişen dosyalar silinmez (TOCTOU).
- Varsayılan: Geri Dönüşüm Kutusu. Önbellekler için isteğe bağlı kalıcı silme.
- Aracın kendi temizleme komutu (npm cache clean vb.) varsa ve açıksa önce o denenir.
- Kullanımdaki/erişilemeyen dosyalar atlanır ve sebebiyle raporlanır.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from send2trash import send2trash

from . import fsutil, winapi
from .models import CleanResult, Finding, RiskLevel
from .protected import ProtectionPolicy, default_policy
from .scanner import folder_stats

log = logging.getLogger(__name__)
DAY = 86400
NATIVE_TIMEOUT = 600
NATIVE_MIN_EFFECT = 0.1  # Komut boyutun en az %10'unu düşürmediyse dosya silmeye geri dön
MTIME_TOLERANCE = 2.0
ProgressFn = Callable[[int, int, str], None]  # (tamamlanan, toplam, yol)


@dataclass(frozen=True)
class CleanOptions:
    dry_run: bool = False
    use_native: bool = True
    permanent_caches: bool = False  # 🟢 önbellekleri Geri Dönüşüm Kutusu'na göndermeden sil


def _on_rm_error(func, path, exc_info):
    """Salt okunur dosyaları yazılabilir yapıp tekrar dener; diğer hataları yükseltir."""
    if func in (os.remove, os.unlink, os.rmdir) and os.path.lexists(path):
        os.chmod(path, stat.S_IWRITE)
        func(path)
        return
    raise exc_info[1]


def permanent_delete(path: str) -> None:
    if fsutil.is_link(path):
        # Junction/symlink: yalnızca bağlantının kendisini kaldır, hedefe dokunma
        os.rmdir(path) if os.path.isdir(path) else os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path, onerror=_on_rm_error)
    else:
        try:
            os.remove(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)


def resolve_executable(name: str, which: Callable[[str], str | None] = shutil.which) -> str | None:
    """PATH'teki aracı bulur; çalışma dizinine bırakılmış sahte bir exe'yi kabul etmez."""
    exe = which(name)
    if exe is None:
        return None
    if os.path.normcase(os.path.dirname(os.path.abspath(exe))) == os.path.normcase(os.getcwd()):
        log.warning("Çalışma dizinindeki %s yok sayıldı", exe)
        return None
    return exe


class _Report:
    """Temizlik sırasında biriken sonuçlar (yalnızca bu modül içinde değişir)."""

    def __init__(self) -> None:
        self.freed = 0
        self.deleted: list[str] = []
        self.skipped: list[tuple[str, str]] = []
        self.by_category: dict[str, int] = {}

    def ok(self, path: str, size: int, category_key: str) -> None:
        self.freed += size
        self.deleted.append(path)
        self.by_category[category_key] = self.by_category.get(category_key, 0) + size

    def skip(self, path: str, reason: str) -> None:
        self.skipped.append((path, reason))


class Cleaner:
    def __init__(self, policy: ProtectionPolicy | None = None, *,
                 trash: Callable[[str], None] = send2trash,
                 delete: Callable[[str], None] = permanent_delete,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                 which: Callable[[str], str | None] = shutil.which,
                 empty_bin: Callable[[], None] = winapi.empty_recycle_bin,
                 now: Callable[[], float] = time.time) -> None:
        self._policy = policy or default_policy()
        self._trash = trash
        self._delete = delete
        self._run = run
        self._which = which
        self._empty_bin = empty_bin
        self._now = now
        self._cancel: threading.Event | None = None

    def _cancelled(self) -> bool:
        return self._cancel is not None and self._cancel.is_set()

    def clean(self, findings: Iterable[Finding], options: CleanOptions = CleanOptions(), *,
              cancel: threading.Event | None = None,
              progress: ProgressFn | None = None) -> CleanResult:
        items = list(findings)
        report = _Report()
        self._cancel = cancel
        for index, finding in enumerate(items):
            if self._cancelled():
                report.skip(finding.path, "İptal edildi")
                continue
            if progress:
                progress(index, len(items), finding.path)
            try:
                self._clean_one(finding, options, report)
            except Exception as exc:  # Tek bir bulgu tüm temizliği durdurmasın
                log.exception("Temizlenemedi: %s", finding.path)
                report.skip(finding.path, f"Beklenmeyen hata: {exc}")
        if progress:
            progress(len(items), len(items), "")
        return CleanResult(freed=report.freed, deleted=tuple(report.deleted),
                           skipped=tuple(report.skipped), dry_run=options.dry_run,
                           extra={"by_category": dict(report.by_category)})

    # ---- bulgu türüne göre ----

    def _clean_one(self, finding: Finding, options: CleanOptions, report: _Report) -> None:
        cat = finding.category
        if cat.risk is RiskLevel.DANGER:
            report.skip(finding.path, "🔴 Korumalı kategori, silinmez")
            return
        if cat.special == "recycle_bin":
            if not options.dry_run:
                self._empty_bin()
            report.ok(finding.path, finding.size, cat.key)
            return
        if cat.contents_only:
            why = self._policy.container_reason(finding.path)
            if why:
                report.skip(finding.path, f"Korumalı: {why}")
                return
        if options.use_native and cat.native_cmd and self._try_native(finding, options, report):
            return
        if cat.contents_only:
            self._clean_contents(finding, options, report)
        else:
            if self._changed_since_scan(finding):
                report.skip(finding.path, "Tarama sonrası değişmiş, güvenlik için atlandı")
                return
            self._remove(finding.path, finding.size, finding, options, report)

    def _changed_since_scan(self, finding: Finding) -> bool:
        if finding.is_dir or finding.last_modified is None:
            return False
        try:
            st = os.lstat(finding.path)
        except OSError:
            return False  # Yoksa _remove "Artık mevcut değil" der
        return (st.st_size != finding.size
                or abs(st.st_mtime - finding.last_modified) > MTIME_TOLERANCE)

    def _try_native(self, finding: Finding, options: CleanOptions, report: _Report) -> bool:
        cmd = finding.category.native_cmd
        exe = resolve_executable(cmd[0], self._which)
        if exe is None:
            return False
        if options.dry_run:
            report.ok(finding.path, finding.size, finding.category.key)
            return True
        try:
            # Proje klasöründe çalışıp proje önbelleğini (ör. Yarn .yarn/cache) silmesin
            with tempfile.TemporaryDirectory(prefix="otoclean-") as neutral_cwd:
                proc = self._run([exe, *cmd[1:]], capture_output=True, text=True,
                                 errors="replace", timeout=NATIVE_TIMEOUT, cwd=neutral_cwd,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("Araç komutu başarısız (%s): %s", " ".join(cmd), exc)
            return False
        if proc.returncode != 0:
            log.warning("Araç komutu hata kodu %s: %s", proc.returncode, proc.stderr)
            return False
        remaining = folder_stats(finding.path).size if os.path.exists(finding.path) else 0
        freed = max(0, finding.size - remaining)
        if finding.size and freed < finding.size * NATIVE_MIN_EFFECT:
            log.warning("Araç komutu yer açmadı (%s); dosyalar doğrudan temizlenecek", " ".join(cmd))
            return False
        report.ok(finding.path, freed, finding.category.key)
        return True

    def _clean_contents(self, finding: Finding, options: CleanOptions, report: _Report) -> None:
        min_age = finding.category.min_age_days * DAY
        try:
            with os.scandir(finding.path) as it:
                children = [(e.path, e.is_dir(follow_symlinks=False)) for e in it]
        except OSError as exc:
            report.skip(finding.path, exc.strerror or str(exc))
            return
        for child, is_dir in children:
            if self._cancelled():
                report.skip(child, "İptal edildi")
                continue
            try:
                stats = folder_stats(child, self._cancel) if is_dir else None
                st = os.lstat(child)
            except OSError as exc:
                report.skip(child, exc.strerror or str(exc))
                continue
            newest = max(st.st_mtime, stats.last_modified if stats else 0.0)
            if min_age and self._now() - newest < min_age:
                report.skip(child, "Çok yeni (kullanımda olabilir)")
                continue
            size = stats.size if stats else st.st_size
            self._remove(child, size, finding, options, report)

    def _remove(self, path: str, size: int, finding: Finding, options: CleanOptions,
                report: _Report) -> None:
        reason = self._policy.deletion_reason(path)
        if reason:
            report.skip(path, f"Korumalı: {reason}")
            return
        if not os.path.lexists(path):
            report.skip(path, "Artık mevcut değil")
            return
        if options.dry_run:
            report.ok(path, size, finding.category.key)
            return
        permanent = options.permanent_caches and finding.category.risk is RiskLevel.SAFE
        try:
            (self._delete if permanent else self._trash)(path)
        except OSError as exc:
            report.skip(path, _friendly(exc))
            return
        report.ok(path, size, finding.category.key)


def _friendly(exc: OSError) -> str:
    if isinstance(exc, PermissionError):
        return "Erişim reddedildi (kullanımda veya yönetici izni gerekli)"
    return exc.strerror or str(exc)
