"""Asla silinmemesi gereken yolların korunması.

Bu modül hem sınıflandırmada hem de silme anında (cleaner) kullanılır; bir kural
hatası korumalı bir yolu silmeye çalışsa bile ikinci kontrol bunu engeller.

Üç katman:
1. `reason`: yolun yazımına bakan hızlı kontrol (sistem kökleri, kişisel klasörler…).
2. `deletion_reason`: + yolda junction/symlink var mı, + gerçek (çözülmüş) yol da güvenli mi.
3. `container_reason`: içi boşaltılacak klasörler için; sürücü kökü veya önemli bir
   klasörün üstü olamaz.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from . import fsutil

PROTECTED_FILE_NAMES = frozenset({
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log.tmp",
    "bootmgr", "ntldr", "desktop.ini", "ntuser.dat",
})
PROTECTED_DIR_NAMES = frozenset({
    ".git", ".ssh", ".gnupg", "system volume information", "$recycle.bin",
    "recovery", "boot", "efi",
})
# Kişisel klasörlerde silinebilen tek şey: yanında projesini kanıtlayan işaret dosyası olan
# yeniden üretilebilir proje çıktıları. (klasör adı → (işaret dosyası, işaret klasörün içinde mi))
REPRODUCIBLE_MARKERS = {
    "node_modules": ("package.json", False),
    ".next": ("package.json", False),
    "target": ("Cargo.toml", False),
    ".venv": ("pyvenv.cfg", True),
    "venv": ("pyvenv.cfg", True),
}
PROBE = "_otoclean_probe_"


def norm(path: str) -> str:
    """Karşılaştırma için yolu normalleştirir (mutlak, küçük harf, sonda ayraç yok)."""
    path = fsutil.strip_long_prefix(path)
    return os.path.normcase(os.path.normpath(os.path.abspath(path))).rstrip("\\/") or path


def is_within(path: str, root: str) -> bool:
    p, r = norm(path), norm(root)
    return p == r or p.startswith(r + os.sep)


def _is_reproducible_artifact(root: str, rel_parts: list[str]) -> bool:
    """`root\\rel...` bir proje çıktısının (kendisi veya içi) mi?"""
    for i, part in enumerate(rel_parts):
        marker = REPRODUCIBLE_MARKERS.get(part)
        if marker is None:
            continue
        artifact = os.path.join(root, *rel_parts[: i + 1])
        name, inside = marker
        base = artifact if inside else os.path.dirname(artifact)
        if os.path.isfile(os.path.join(base, name)):
            return True
    return False


@dataclass(frozen=True)
class ProtectionPolicy:
    roots: tuple[str, ...]        # Bu köklerin altı korunur
    exceptions: tuple[str, ...]   # Korumalı kök içinde olsa da silinebilir alanlar
    anchors: tuple[str, ...]      # Kendisi silinemeyen ama altı serbest klasörler
    personal: tuple[str, ...] = ()  # Sadece proje çıktılarının silinebildiği kişisel alanlar

    def _important(self) -> tuple[str, ...]:
        return self.anchors + self.roots + self.exceptions + self.personal

    def reason(self, path: str) -> str | None:
        """Yol (yazımına göre) korumalıysa Türkçe sebep döner, değilse None."""
        if fsutil.is_unc(path):
            return "Ağ yolları desteklenmez"
        p = norm(path)
        _drive, tail = os.path.splitdrive(p)
        if tail in ("", os.sep):
            return "Sürücü kökü silinemez"

        parts = [x for x in tail.split(os.sep) if x]
        if parts and parts[-1] in PROTECTED_FILE_NAMES:
            return f"Sistem dosyası ({parts[-1]})"
        for part in parts:
            if part in PROTECTED_DIR_NAMES:
                return f"Korumalı klasör ({part})"

        for anchor in self._important():
            a = norm(anchor)
            if a == p or a.startswith(p + os.sep):
                return "Önemli bir klasörü veya onun üst klasörünü içeriyor"

        if any(is_within(p, e) for e in self.exceptions):
            return None
        for root in self.roots:
            if is_within(p, root):
                return f"Sistem/uygulama alanı: {root}"
        for root in self.personal:
            if is_within(p, root):
                r = norm(root)
                rel = [x for x in p[len(r):].split(os.sep) if x]
                if _is_reproducible_artifact(r, rel):
                    return None
                return f"Kişisel klasör: {root}"
        return None

    def is_protected(self, path: str) -> bool:
        return self.reason(path) is not None

    def deletion_reason(self, path: str) -> str | None:
        """Silme anı kontrolü: yazım + bağlantı zinciri + çözülmüş gerçek yol."""
        why = self.reason(path)
        if why:
            return why
        link = fsutil.link_in_chain(path)
        if link:
            return f"Bağlantı (junction/symlink) üzerinden: {link}"
        real = os.path.realpath(fsutil.strip_long_prefix(path))
        if norm(real) != norm(path):
            why = self.reason(real)
            if why:
                return f"Gerçek konumu korumalı ({real}): {why}"
        return None

    def container_reason(self, folder: str) -> str | None:
        """İçi boşaltılacak klasör kontrolü (önbellek/temp)."""
        if fsutil.is_unc(folder):
            return "Ağ yolları desteklenmez"
        p = norm(folder)
        _drive, tail = os.path.splitdrive(p)
        if tail in ("", os.sep):
            return "Sürücü kökünün içi toptan boşaltılamaz"
        for important in self._important():
            a = norm(important)
            if a.startswith(p + os.sep):
                return f"İçinde önemli bir klasör var: {important}"
        link = fsutil.link_in_chain(folder)
        if link:
            return f"Bağlantı (junction/symlink) üzerinden: {link}"
        probe = self.deletion_reason(os.path.join(folder, PROBE))
        if probe:
            return probe
        # Bağlantı yoksa fark yalnızca 8.3 kısa ad gibi yazım farkıdır; uzun hâlini de kontrol et
        real = os.path.realpath(fsutil.strip_long_prefix(folder))
        if norm(real) != p:
            return self.container_reason(real)
        return None


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name) or default


def _known(name: str, fallback: str) -> str:
    from . import winapi  # ctypes; yalnızca Windows'ta

    return winapi.known_folder(name) or fallback


@lru_cache(maxsize=1)
def default_policy() -> ProtectionPolicy:
    home = _env("USERPROFILE") or os.path.expanduser("~")
    if not home or not os.path.isabs(home) or os.path.splitdrive(norm(home))[1] in ("", os.sep):
        # Ev klasörü belirlenemiyorsa göreli yollarla yanlış koruma kurmak yerine dur
        raise RuntimeError("Kullanıcı klasörü belirlenemedi (USERPROFILE)")
    windir = _env("WINDIR", r"C:\Windows")
    local = _env("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    roaming = _env("APPDATA", os.path.join(home, "AppData", "Roaming"))
    program_data = _env("PROGRAMDATA", r"C:\ProgramData")

    roots = [
        windir,
        _env("PROGRAMFILES", r"C:\Program Files"),
        _env("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        program_data,
        os.path.join(home, ".ssh"),
    ]
    # Hem varsayılan konum hem de (OneDrive/D: gibi) yönlendirilmiş gerçek konum korunur
    personal = [p for name in ("Documents", "Desktop", "Pictures", "Videos", "Music")
                for p in (os.path.join(home, name), _known(name, os.path.join(home, name)))]
    personal += [
        os.path.join(home, "Saved Games"), os.path.join(home, "Contacts"),
        os.path.join(home, "Favorites"), os.path.join(home, "Links"),
        os.path.join(home, "OneDrive"),
    ] + [v for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial") if (v := _env(k))]
    exceptions = [
        os.path.join(windir, "Temp"),
        os.path.join(windir, "SoftwareDistribution", "Download"),
        os.path.join(windir, "ServiceProfiles", "NetworkService", "AppData", "Local",
                     "Microsoft", "Windows", "DeliveryOptimization", "Cache"),
        os.path.join(program_data, "Microsoft", "Windows", "WER"),
    ]
    anchors = [
        home, local, roaming, os.path.join(home, "AppData"), os.path.join(home, "Downloads"),
        _known("Downloads", os.path.join(home, "Downloads")), os.path.dirname(home),
        os.path.join(local, "Temp"),
    ]
    return ProtectionPolicy(tuple(roots), tuple(exceptions), tuple(anchors), tuple(personal))
