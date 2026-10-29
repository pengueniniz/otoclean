"""Windows dosya sistemi yardımcıları: bağlantı (junction/symlink) tespiti ve yol normalleştirme."""

from __future__ import annotations

import os
import stat as stat_mod

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
# Junction ve symlink gibi "başka bir yeri gösteren" reparse etiketlerinde bu bit set'tir.
# OneDrive bulut dosyalarının etiketlerinde set değildir; onlar gerçek klasör/dosyadır.
REPARSE_NAME_SURROGATE_BIT = 0x20000000
CLOUD_ONLY_ATTRS = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


def is_link_stat(st: os.stat_result) -> bool:
    """lstat sonucu bir junction/symlink'e mi ait?"""
    if stat_mod.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    if not attrs & FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    tag = getattr(st, "st_reparse_tag", None)
    if tag is None:
        return True  # Etiket okunamıyorsa güvenli tarafta kal
    return bool(tag & REPARSE_NAME_SURROGATE_BIT)


def is_link(path: str) -> bool:
    try:
        return is_link_stat(os.lstat(path))
    except OSError:
        return False


def is_cloud_only(st: os.stat_result) -> bool:
    """OneDrive gibi yalnızca bulutta duran (okununca indirilecek) dosya mı?"""
    return bool(getattr(st, "st_file_attributes", 0) & CLOUD_ONLY_ATTRS)


def link_in_chain(path: str) -> str | None:
    """Yolun kendisi veya üst klasörlerinden biri bağlantıysa o bileşeni döner."""
    current = os.path.abspath(path)
    while True:
        if is_link(current):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def strip_long_prefix(path: str) -> str:
    r"""`\\?\C:\x` → `C:\x` (UNC biçimi `\\?\UNC\` olduğu gibi kalır)."""
    for prefix in ("\\\\?\\", "//?/", "\\\\.\\", "//./"):
        if path.startswith(prefix) and not path[len(prefix):].upper().startswith("UNC"):
            return path[len(prefix):]
    return path


def is_unc(path: str) -> bool:
    p = strip_long_prefix(path)
    return p.startswith("\\\\") or p.startswith("//")
