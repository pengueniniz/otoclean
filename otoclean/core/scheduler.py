"""Windows Görev Zamanlayıcı ile haftalık otomatik güvenli temizlik görevi."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable

TASK_NAME = r"OtoClean\HaftalikGuvenliTemizlik"
VALID_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

Runner = Callable[..., subprocess.CompletedProcess]


def launch_command() -> str:
    """Görevin çalıştıracağı komut satırı."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --auto-safe'
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    return f'"{exe}" -m otoclean --auto-safe'


def _schtasks(args: list[str], run: Runner) -> subprocess.CompletedProcess:
    # schtasks konsol kod sayfasıyla (Türkçe: cp857) yazar
    return run(["schtasks", *args], capture_output=True, text=True,
               encoding="oem", errors="replace",
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def enable(day: str = "SUN", time_of_day: str = "12:00", *,
           run: Runner = subprocess.run) -> None:
    day = day.upper()
    if day not in VALID_DAYS:
        raise ValueError(f"Geçersiz gün: {day}")
    if not TIME_RE.match(time_of_day):
        raise ValueError(f"Geçersiz saat: {time_of_day}")
    proc = _schtasks(["/Create", "/F", "/SC", "WEEKLY", "/D", day, "/ST", time_of_day,
                      "/TN", TASK_NAME, "/TR", launch_command()], run)
    if proc.returncode != 0:
        raise RuntimeError(f"Görev oluşturulamadı: {proc.stderr.strip() or proc.stdout.strip()}")


def disable(*, run: Runner = subprocess.run) -> None:
    proc = _schtasks(["/Delete", "/F", "/TN", TASK_NAME], run)
    if proc.returncode != 0 and is_enabled(run=run):
        raise RuntimeError(f"Görev silinemedi: {proc.stderr.strip()}")


def is_enabled(*, run: Runner = subprocess.run) -> bool:
    return _schtasks(["/Query", "/TN", TASK_NAME], run).returncode == 0
