"""Kalıcı kullanıcı ayarları (%LOCALAPPDATA%\\OtoClean\\settings.json)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, fields, replace

log = logging.getLogger(__name__)


def data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    path = os.path.join(base, "OtoClean")
    os.makedirs(path, exist_ok=True)
    return path


@dataclass(frozen=True)
class Settings:
    permanent_caches: bool = False
    use_native: bool = True
    schedule_day: str = "SUN"
    schedule_time: str = "12:00"
    theme: str = "paper"

    def with_changes(self, **changes) -> "Settings":
        return replace(self, **changes)


def _path(directory: str | None) -> str:
    return os.path.join(directory or data_dir(), "settings.json")


def load_settings(directory: str | None = None) -> Settings:
    path = _path(directory)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as exc:
        log.warning("Ayarlar okunamadı, varsayılanlar kullanılıyor: %s", exc)
        return Settings()
    if not isinstance(raw, dict):
        log.warning("Ayarlar dosyası beklenen biçimde değil, varsayılanlar kullanılıyor")
        return Settings()
    known = {f.name for f in fields(Settings)}
    defaults = Settings()
    clean = {k: v for k, v in raw.items()
             if k in known and isinstance(v, type(getattr(defaults, k)))}
    return Settings(**clean)


def save_settings(settings: Settings, directory: str | None = None) -> None:
    path = _path(directory)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(asdict(settings), fh, indent=2)
    os.replace(tmp, path)
