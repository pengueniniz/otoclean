"""Kuralları ve dedektörleri çalıştırıp bulguları üreten tarama orkestrasyonu."""

from __future__ import annotations

import glob
import logging
import os
import re
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from . import winapi
from .detectors.content_filter import is_user_content
from .detectors.downloads import find_old_downloads
from .detectors.duplicates import find_duplicates
from .detectors.large_old import find_large_old
from .detectors.stale_projects import find_stale_artifacts
from .models import Category, Finding, RiskLevel, ScanResult
from .protected import ProtectionPolicy, default_policy, norm
from .rules.catalog import LOCATION_RULES, LocationRule
from .scanner import folder_stats, scan_tree

log = logging.getLogger(__name__)
StatusFn = Callable[[str], None]
DEEP_SCAN_FILE_THRESHOLD = 10 * 1024 * 1024
MEASURE_WORKERS = 8
MB = 1024 * 1024
LARGE_OLD_MIN_SIZE = 500 * MB


def expand(template: str) -> list[str]:
    """Ortam değişkenli/glob desenli şablonu mevcut yollara çevirir."""
    is_glob = any(ch in template for ch in "*?[")
    missing = False

    def substitute(match: re.Match) -> str:
        nonlocal missing
        value = os.environ.get(match.group(1))
        if not value:
            missing = True
            return match.group(0)
        # Kullanıcı adındaki "[" gibi karakterler glob deseni sanılmasın
        return glob.escape(value) if is_glob else value

    path = re.sub(r"%([^%]+)%", substitute, template)
    if missing:
        return []  # Tanımsız ortam değişkeni
    if is_glob:
        return sorted(glob.glob(path))
    return [path] if os.path.exists(path) else []


def guard_reason(finding: Finding, policy: ProtectionPolicy) -> str | None:
    """Bulgunun silinmesi korumaya takılıyorsa sebebini döner."""
    if finding.category.contents_only:
        return policy.container_reason(finding.path)
    return policy.deletion_reason(finding.path)


def _measure(path: str, category: Category,
             cancel: threading.Event | None) -> Finding | None:
    try:
        if os.path.isdir(path):
            stats = folder_stats(path, cancel)
            return Finding(path=path, size=stats.size, category=category,
                           file_count=stats.file_count, last_modified=stats.last_modified,
                           is_dir=True)
        st = os.stat(path)
        return Finding(path=path, size=st.st_size, category=category,
                       last_modified=st.st_mtime, last_access=st.st_atime)
    except OSError:
        return _measure_via_parent(path, category)


def _measure_via_parent(path: str, category: Category) -> Finding | None:
    """pagefile.sys gibi kilitli dosyaların boyutunu üst klasör listesinden okur."""
    parent, name = os.path.split(path)
    try:
        with os.scandir(parent) as it:
            for entry in it:
                if entry.name.lower() == name.lower():
                    st = entry.stat(follow_symlinks=False)
                    return Finding(path=path, size=st.st_size, category=category,
                                   last_modified=st.st_mtime)
    except OSError as exc:
        log.debug("Ölçülemedi %s: %s", path, exc)
    return None


def _recycle_bin_finding(category: Category) -> Finding | None:
    try:
        size, items = winapi.recycle_bin_info()
    except OSError as exc:
        log.warning("Geri Dönüşüm Kutusu okunamadı: %s", exc)
        return None
    if size <= 0:
        return None
    return Finding(path="::RecycleBin", size=size, category=category, file_count=items,
                   is_dir=True, note=f"{items} öğe")


def evaluate_location_rules(rules: Iterable[LocationRule], *,
                            cancel: threading.Event | None = None,
                            status: StatusFn | None = None) -> list[Finding]:
    findings: list[Finding] = []
    tasks: list[tuple[str, Category]] = []
    for rule in rules:
        if rule.category.special == "recycle_bin":
            found = _recycle_bin_finding(rule.category)
            if found:
                findings.append(found)
            continue
        tasks += [(path, rule.category) for t in rule.paths for path in expand(t)]

    def measure(task: tuple[str, Category]) -> Finding | None:
        if cancel is not None and cancel.is_set():
            return None
        if status:
            status(task[1].name)
        return _measure(task[0], task[1], cancel)

    with ThreadPoolExecutor(max_workers=MEASURE_WORKERS) as pool:
        findings += [f for f in pool.map(measure, tasks) if f and f.size > 0]
    return findings


def apply_protection(findings: Iterable[Finding], policy: ProtectionPolicy) -> list[Finding]:
    """Korumaya takılan seçilebilir bulguları ayıklar (🔴 bilgi kayıtları kalır)."""
    kept = []
    for f in findings:
        if f.risk is RiskLevel.DANGER or f.path.startswith("::"):
            kept.append(f)
            continue
        reason = guard_reason(f, policy)
        if reason:
            log.info("Korumalı yol listeden çıkarıldı: %s (%s)", f.path, reason)
            continue
        kept.append(f)
    return kept


def dedupe(findings: Iterable[Finding]) -> list[Finding]:
    """Aynı yolu veya başka bir bulgunun içinde kalan yolları tekilleştirir."""
    ordered = sorted(findings, key=lambda f: (len(norm(f.path)), f.risk.order))
    kept: list[Finding] = []
    taken: list[str] = []
    for f in ordered:
        key = norm(f.path) if not f.path.startswith("::") else f.path
        if any(key == t or key.startswith(t + os.sep) for t in taken):
            continue
        taken.append(key)
        kept.append(f)
    return sorted(kept, key=lambda f: (f.risk.order, -f.size))


def default_project_roots() -> list[str]:
    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    system_drive = os.environ.get("SYSTEMDRIVE", "C:") + "\\"
    roots = [home]
    try:
        roots += [d for d in winapi.fixed_drives() if norm(d) != norm(system_drive)]
    except Exception as exc:  # psutil yoksa veya sürücü listesi alınamazsa
        log.warning("Sürücüler listelenemedi: %s", exc)
    return roots


def quick_scan(*, policy: ProtectionPolicy | None = None,
               cancel: threading.Event | None = None, status: StatusFn | None = None,
               rules: Iterable[LocationRule] = LOCATION_RULES,
               project_roots: Iterable[str] | None = None,
               downloads_dir: str | None = None) -> list[Finding]:
    """Bilinen konumları, İndirilenler'i ve eski projeleri hızla tarar."""
    policy = policy or default_policy()
    findings = evaluate_location_rules(rules, cancel=cancel, status=status)

    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    downloads_dir = downloads_dir or os.path.join(home, "Downloads")
    if status:
        status("İndirilenler klasörü")
    findings += find_old_downloads(downloads_dir, cancel=cancel)

    if status:
        status("Eski projeler (node_modules, .venv, target)")
    roots = list(project_roots) if project_roots is not None else default_project_roots()
    findings += find_stale_artifacts(roots, cancel=cancel)

    return dedupe(apply_protection(findings, policy))


def deep_scan(root: str, *, policy: ProtectionPolicy | None = None,
              cancel: threading.Event | None = None,
              progress: Callable[[int, int, str], None] | None = None,
              status: StatusFn | None = None) -> tuple[ScanResult, list[Finding]]:
    """Bir sürücünün tamamını tarar: büyük klasörler, büyük-eski dosyalar, kopyalar."""
    policy = policy or default_policy()
    if status:
        status(f"{root} taranıyor")
    result = scan_tree(root, cancel=cancel, progress=progress,
                       large_threshold=DEEP_SCAN_FILE_THRESHOLD)
    if result.cancelled:
        return result, []
    if status:
        status("Kopya dosyalar karşılaştırılıyor")

    def dup_progress(done: int, total: int) -> None:
        if progress:  # MB cinsinden: Qt ilerleme çubuğu 32-bit int kullanır
            progress(done // MB, max(1, total // MB), "kopya doğrulama")

    user_files = [f for f in result.large_files if is_user_content(f[0], root)]
    originals: set[str] = set()
    findings = find_duplicates(user_files, policy, min_size=DEEP_SCAN_FILE_THRESHOLD,
                               cancel=cancel, progress=dup_progress, originals_out=originals)
    # Bir kopya grubunun asıl dosyası "büyük-eski" olarak önerilmez; yoksa kullanıcı
    # hem kopyaları hem aslını seçip verinin tamamını silebilir.
    kept_originals = {norm(p) for p in originals}
    findings += [f for f in find_large_old(user_files, policy, min_size=LARGE_OLD_MIN_SIZE)
                 if norm(f.path) not in kept_originals]
    return result, dedupe(apply_protection(findings, policy))


def remeasure(findings: Iterable[Finding]) -> list[Finding]:
    """Temizlik sonrası bulguların gerçek durumunu ölçer.

    Silinmiş yollar düşer; kısmen temizlenen klasörler yeni boyutlarıyla kalır;
    atlanan (kilitli vb.) dosyalar olduğu gibi listede kalır.
    """
    remaining = []
    for f in findings:
        if f.category.special == "recycle_bin":
            found = _recycle_bin_finding(f.category)
            if found:
                remaining.append(found)
            continue
        if not os.path.lexists(f.path):
            continue
        if f.is_dir:
            stats = folder_stats(f.path)
            if stats.size > 0:
                remaining.append(replace(f, size=stats.size, file_count=stats.file_count))
            continue
        remaining.append(f)
    return remaining


def summarize(findings: Iterable[Finding]) -> dict[RiskLevel, int]:
    totals = {level: 0 for level in RiskLevel}
    for f in findings:
        totals[f.risk] += f.size
    return totals
