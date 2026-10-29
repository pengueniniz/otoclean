import os
import time

import pytest
from conftest import make_file

from otoclean.core.detectors.downloads import find_old_downloads
from otoclean.core.detectors.duplicates import find_duplicates
from otoclean.core.detectors.large_old import find_large_old
from otoclean.core.detectors.stale_projects import find_stale_artifacts
from otoclean.core.protected import ProtectionPolicy

MB = 1024 * 1024
NOW = time.time()


@pytest.fixture
def policy(tmp_path):
    return ProtectionPolicy(roots=(str(tmp_path / "Docs"),), exceptions=(), anchors=())


# ---------- stale_projects ----------

def _project(root, name, age_days, artifact="node_modules", size=2 * MB):
    proj = root / name
    make_file(proj / artifact / "pkg" / "index.js", size, age_days=age_days)
    make_file(proj / "package.json", 10, age_days=age_days)
    return proj


def test_stale_node_modules_found(tmp_path):
    _project(tmp_path, "old", 200)
    found = find_stale_artifacts([str(tmp_path)], now=NOW)
    assert [os.path.basename(os.path.dirname(f.path)) for f in found] == ["old"]
    assert found[0].category.key == "stale_node_modules"
    assert found[0].size == 2 * MB


def test_active_project_ignored(tmp_path):
    _project(tmp_path, "fresh", 5)
    assert find_stale_artifacts([str(tmp_path)], now=NOW) == []


def test_tiny_artifact_ignored(tmp_path):
    _project(tmp_path, "tiny", 200, size=100)
    assert find_stale_artifacts([str(tmp_path)], now=NOW) == []


def test_venv_requires_pyvenv_cfg(tmp_path):
    proj = tmp_path / "py"
    make_file(proj / ".venv" / "Lib" / "big.bin", 2 * MB, age_days=200)
    make_file(proj / "main.py", 10, age_days=200)
    assert find_stale_artifacts([str(tmp_path)], now=NOW) == []

    make_file(proj / ".venv" / "pyvenv.cfg", 10, age_days=200)
    os.utime(proj / "main.py", (NOW - 200 * 86400,) * 2)
    found = find_stale_artifacts([str(tmp_path)], now=NOW)
    assert found and found[0].category.key == "stale_venv"


def test_rust_target_requires_cargo_toml(tmp_path):
    proj = tmp_path / "rs"
    make_file(proj / "target" / "debug" / "app.exe", 2 * MB, age_days=120)
    assert find_stale_artifacts([str(tmp_path)], now=NOW) == []
    make_file(proj / "Cargo.toml", 10, age_days=120)
    found = find_stale_artifacts([str(tmp_path)], now=NOW)
    assert found and found[0].category.key == "stale_build"


def test_does_not_descend_into_node_modules(tmp_path):
    proj = _project(tmp_path, "old", 200)
    make_file(proj / "node_modules" / "dep" / "node_modules" / "x" / "a.js", 2 * MB, age_days=200)
    found = find_stale_artifacts([str(tmp_path)], now=NOW)
    assert len(found) == 1


def test_skips_appdata(tmp_path):
    _project(tmp_path / "AppData", "old", 200)
    assert find_stale_artifacts([str(tmp_path)], now=NOW) == []


def test_skips_program_files_backups(tmp_path):
    _project(tmp_path / "yedek" / "CProgram Files (x86)" / "Adobe", "js", 200)
    assert find_stale_artifacts([str(tmp_path)], now=NOW) == []


def test_node_modules_requires_package_json(tmp_path):
    make_file(tmp_path / "lib" / "node_modules" / "x.js", 2 * MB, age_days=200)
    assert find_stale_artifacts([str(tmp_path)], now=NOW) == []


# ---------- downloads ----------

def test_old_installer_flagged(tmp_path):
    make_file(tmp_path / "setup.exe", 5 * MB, age_days=40)
    make_file(tmp_path / "new.exe", 5 * MB, age_days=2)
    found = find_old_downloads(str(tmp_path), now=NOW)
    assert [os.path.basename(f.path) for f in found] == ["setup.exe"]
    assert found[0].category.key == "old_installers"


def test_old_other_file_flagged_after_180_days(tmp_path):
    make_file(tmp_path / "doc.pdf", MB, age_days=100)
    make_file(tmp_path / "ancient.pdf", MB, age_days=400)
    found = find_old_downloads(str(tmp_path), now=NOW)
    assert [os.path.basename(f.path) for f in found] == ["ancient.pdf"]
    assert found[0].category.key == "old_downloads"


def test_folder_in_downloads_uses_newest_content(tmp_path):
    make_file(tmp_path / "proj" / "old.txt", MB, age_days=400)
    make_file(tmp_path / "proj" / "new.txt", MB, age_days=1)
    os.utime(tmp_path / "proj", (NOW - 400 * 86400,) * 2)
    assert find_old_downloads(str(tmp_path), now=NOW) == []


def test_missing_downloads_folder(tmp_path):
    assert find_old_downloads(str(tmp_path / "none")) == []


# ---------- content_filter ----------

@pytest.mark.parametrize("path,expected", [
    (r"C:\Users\u\Downloads\video.mp4", True),
    (r"D:\MASAÜSTÜ\proje\render.mov", True),
    (r"C:\Users\u\AppData\Local\Programs\App\ffmpeg.exe", False),
    (r"C:\Users\u\.cache\whisper\small.pt", False),
    (r"C:\proj\backend\venv\Lib\site-packages\torch\lib\x.dll", False),
    (r"C:\Program Files (x86)\Steam\x.bin", False),
    (r"E:\SteamLibrary\steamapps\common\Game\data.pak", False),
    (r"D:\yedek\Program Files\App\x.dll", False),
])
def test_is_user_content(path, expected):
    from otoclean.core.detectors.content_filter import is_user_content
    assert is_user_content(path) is expected
    assert is_user_content(path, path[:3]) is expected


def test_is_user_content_only_checks_below_root():
    from otoclean.core.detectors.content_filter import is_user_content
    root = r"C:\Users\u\AppData\Local\Temp\scan"
    assert is_user_content(root + r"\videos\a.mp4", root)
    assert not is_user_content(root + r"\.cache\a.bin", root)


# ---------- large_old ----------

def test_large_old_filters_by_size_age_and_protection(tmp_path, policy, monkeypatch):
    old = NOW - 400 * 86400
    monkeypatch.setattr("otoclean.core.detectors.large_old._created", lambda p: old)
    files = [
        (str(tmp_path / "big_old.iso"), 600 * MB, old, old),
        (str(tmp_path / "big_new.iso"), 600 * MB, NOW, old),
        (str(tmp_path / "small_old.bin"), 10 * MB, old, old),
        (str(tmp_path / "Docs" / "big.vhd"), 600 * MB, old, old),
    ]
    found = find_large_old(files, policy, now=NOW)
    assert [os.path.basename(f.path) for f in found] == ["big_old.iso"]


def test_large_old_recently_copied_file_not_flagged(tmp_path, policy, monkeypatch):
    old = NOW - 400 * 86400
    monkeypatch.setattr("otoclean.core.detectors.large_old._created", lambda p: NOW - 86400)
    files = [(str(tmp_path / "copied.iso"), 600 * MB, old, old)]
    assert find_large_old(files, policy, now=NOW) == []


def test_large_old_missing_file_skipped(tmp_path, policy):
    old = NOW - 400 * 86400
    assert find_large_old([(str(tmp_path / "yok.iso"), 600 * MB, old, old)], policy, now=NOW) == []


# ---------- duplicates ----------

def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    st = path.stat()
    return (str(path), st.st_size, st.st_atime, st.st_mtime)


def test_duplicates_keep_one_copy(tmp_path, policy):
    data = os.urandom(200_000)
    files = [_write(tmp_path / "a" / "x.bin", data),
             _write(tmp_path / "b" / "c" / "x.bin", data),
             _write(tmp_path / "other.bin", os.urandom(200_000))]
    found = find_duplicates(files, policy, min_size=1)
    assert [f.path for f in found] == [str(tmp_path / "b" / "c" / "x.bin")]
    assert str(tmp_path / "a" / "x.bin") in found[0].note


def test_same_head_different_tail_not_duplicate(tmp_path, policy):
    head = os.urandom(70_000)
    files = [_write(tmp_path / "1.bin", head + b"A" * 10),
             _write(tmp_path / "2.bin", head + b"B" * 10)]
    assert find_duplicates(files, policy, min_size=1) == []


def test_protected_copy_is_kept_as_original(tmp_path, policy):
    data = os.urandom(100_000)
    files = [_write(tmp_path / "x.bin", data), _write(tmp_path / "Docs" / "deep" / "x.bin", data)]
    found = find_duplicates(files, policy, min_size=1)
    assert [f.path for f in found] == [str(tmp_path / "x.bin")]


def test_duplicates_report_progress_and_originals(tmp_path, policy):
    data = os.urandom(300_000)
    files = [_write(tmp_path / "a.bin", data), _write(tmp_path / "sub" / "b.bin", data)]
    seen, originals = [], set()
    find_duplicates(files, policy, min_size=1, progress=lambda d, t: seen.append((d, t)),
                    originals_out=originals)
    assert originals == {str(tmp_path / "a.bin")}
    assert seen[-1] == (600_000, 600_000)


def test_hardlinks_not_duplicates(tmp_path, policy):
    a = tmp_path / "a.bin"
    a.write_bytes(os.urandom(100_000))
    os.link(a, tmp_path / "b.bin")
    files = [(str(p), p.stat().st_size, 0, 0) for p in (a, tmp_path / "b.bin")]
    assert find_duplicates(files, policy, min_size=1) == []
