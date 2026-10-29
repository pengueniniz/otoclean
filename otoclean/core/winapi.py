"""Windows'a özgü küçük yardımcılar (ctypes)."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

SHERB_NOCONFIRMATION = 0x1
SHERB_NOPROGRESSUI = 0x2
SHERB_NOSOUND = 0x4


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_int64),
                ("i64NumItems", ctypes.c_int64)]


def recycle_bin_info() -> tuple[int, int]:
    """Tüm sürücülerdeki Geri Dönüşüm Kutusu (boyut, öğe sayısı)."""
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
    result = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if result != 0:
        raise OSError(f"SHQueryRecycleBinW başarısız: 0x{result & 0xFFFFFFFF:08X}")
    return int(info.i64Size), int(info.i64NumItems)


def empty_recycle_bin() -> None:
    flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    # 0x8000FFFF (E_UNEXPECTED) kutu zaten boşken döner
    if result not in (0, -2147418113):
        raise OSError(f"SHEmptyRecycleBinW başarısız: 0x{result & 0xFFFFFFFF:08X}")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin(args: list[str]) -> bool:
    """Uygulamayı yönetici olarak yeniden başlatır (UAC penceresi açılır)."""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, args
    else:
        exe, params = sys.executable, ["-m", "otoclean", *args]
    joined = " ".join(f'"{a}"' for a in params)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, joined, os.getcwd(), 1)
    return rc > 32


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "_GUID":
        import uuid

        u = uuid.UUID(text)
        g = cls(u.time_low, u.time_mid, u.time_hi_version)
        g.Data4[:] = list(u.bytes[8:])
        return g


KNOWN_FOLDERS = {
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "Music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
}


def known_folder(name: str) -> str | None:
    """Yönlendirilmiş olsa bile (ör. Belgeler D:'de) bilinen klasörün gerçek yolu."""
    path_ptr = ctypes.c_wchar_p()
    try:
        guid = _GUID.parse(KNOWN_FOLDERS[name])
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                                        ctypes.byref(path_ptr))
    except (OSError, KeyError, AttributeError):
        return None
    try:
        return path_ptr.value if hr == 0 else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)


def fixed_drives() -> list[str]:
    import psutil

    drives = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        drives.append(part.mountpoint)
    return drives
