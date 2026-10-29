import os
import subprocess
import time

import pytest


def make_file(path, size=0, age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        if size:
            fh.seek(size - 1)
            fh.write(b"\0")
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


def make_junction(link, target):
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"junction oluşturulamadı: {result.stderr}")
