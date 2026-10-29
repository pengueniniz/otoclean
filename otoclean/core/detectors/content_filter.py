"""Kopya ve büyük-eski dosya önerilerinin yalnızca kullanıcı içeriğine yapılmasını sağlar.

Programların kendi dosyaları (AppData, Program Files, paket depoları, sanal ortamlar)
birbirinin kopyası olabilir ama silinirse ilgili program bozulur. Bu yüzden dedektörler
bu alanlardaki dosyaları hiç görmez.
"""

from __future__ import annotations

import os

APP_DIR_NAMES = frozenset({
    "appdata", "programdata", "windows", "windows.old", "$recycle.bin",
    "system volume information", "node_modules", "site-packages", "venv",
    "steamapps", "epic games", "riot games", "xboxgames", "windowsapps",
})


def is_user_content(path: str, root: str | None = None) -> bool:
    """Yol (varsa `root` altındaki kısmıyla) bir uygulama/sistem alanında değilse True."""
    path = os.path.normcase(os.path.normpath(path))
    if root is not None:
        path = os.path.relpath(path, os.path.normcase(os.path.normpath(root)))
        folders = path.split(os.sep)[:-1]
    else:
        folders = path.split(os.sep)[1:-1]  # sürücü ve dosya adı hariç
    for part in folders:
        if part in APP_DIR_NAMES or part.startswith(".") or part.startswith("program files"):
            return False
    return True
