"""Güvenlik incelemesinde bulunan senaryoların regresyon testleri (gerçek junction'larla)."""

import ctypes
import os
import subprocess

import pytest
from conftest import make_file, make_junction

from otoclean.core import classifier
from otoclean.core.cleaner import Cleaner, CleanOptions, permanent_delete, resolve_executable
from otoclean.core.models import Finding
from otoclean.core.protected import ProtectionPolicy
from otoclean.core.rules.catalog import OLD_DOWNLOADS, _cache

CACHE = _cache("c", "Cache").category


@pytest.fixture
def setup(tmp_path):
    docs = tmp_path / "Documents"
    make_file(docs / "tez.docx", 100)
    make_file(docs / "fotolar" / "a.jpg", 100)
    policy = ProtectionPolicy(roots=(str(tmp_path / "Windows"),), exceptions=(),
                              anchors=(str(tmp_path / "home"),), personal=(str(docs),))
    return tmp_path, docs, policy


def _cleaner(policy):
    return Cleaner(policy, trash=permanent_delete, which=lambda _: None)


def test_cache_folder_junction_to_documents_deletes_nothing(setup):
    tmp, docs, policy = setup
    cache = tmp / "home" / "npm-cache"
    cache.parent.mkdir(parents=True)
    make_junction(cache, docs)

    finding = Finding(str(cache), 200, CACHE, is_dir=True)
    assert classifier.guard_reason(finding, policy) is not None
    result = _cleaner(policy).clean([finding], CleanOptions(permanent_caches=True))

    assert result.deleted == ()
    assert (docs / "tez.docx").exists() and (docs / "fotolar" / "a.jpg").exists()


def test_junction_child_inside_cache_is_not_followed(setup):
    tmp, docs, policy = setup
    cache = tmp / "home" / "cache"
    make_file(cache / "old.tmp", 10, age_days=5)
    make_junction(cache / "evil", docs)

    result = _cleaner(policy).clean([Finding(str(cache), 10, CACHE, is_dir=True)],
                                    CleanOptions(permanent_caches=True))

    assert (docs / "tez.docx").exists()
    assert not (cache / "old.tmp").exists()
    assert any("Bağlantı" in why for _, why in result.skipped)


def test_permanent_delete_on_junction_removes_only_link(tmp_path):
    target = tmp_path / "target"
    make_file(target / "keep.txt", 5)
    make_junction(tmp_path / "link", target)
    permanent_delete(str(tmp_path / "link"))
    assert not (tmp_path / "link").exists() and (target / "keep.txt").exists()


@pytest.mark.parametrize("folder_fn", [
    lambda tmp: os.path.splitdrive(str(tmp))[0] + "\\",  # TEMP=C:\ senaryosu
    lambda tmp: str(tmp),                                   # Önemli klasörlerin üstü
])
def test_container_cannot_be_drive_root_or_ancestor(setup, folder_fn):
    tmp, _docs, policy = setup
    assert policy.container_reason(folder_fn(tmp)) is not None


@pytest.mark.parametrize("path", [
    r"\\?\{win}\System32\x.dll",
    r"//?/{win}/System32/x.dll",
    r"\\localhost\C$\Windows\x.dll",
])
def test_alternate_spellings_blocked(setup, path):
    tmp, _docs, policy = setup
    p = path.format(win=str(tmp / "Windows"))
    assert policy.deletion_reason(p) is not None


def test_short_8dot3_name_resolves_to_protected(setup):
    tmp, _docs, policy = setup
    long_dir = tmp / "Windows" / "VeryLongSystemFolderName"
    make_file(long_dir / "x.dll", 1)
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetShortPathNameW(str(long_dir / "x.dll"), buf, 1024)
    short = buf.value
    if not short or short.lower() == str(long_dir / "x.dll").lower():
        pytest.skip("Bu birimde 8.3 kısa adlar kapalı")
    assert policy.deletion_reason(short) is not None


def test_file_changed_after_scan_is_skipped(tmp_path):
    f = make_file(tmp_path / "dup.bin", 100, age_days=10)
    st = f.stat()
    finding = Finding(str(f), st.st_size, OLD_DOWNLOADS, last_modified=st.st_mtime)
    f.write_bytes(b"yeni icerik")  # Tarama sonrası değişti
    result = _cleaner(ProtectionPolicy((), (), ())).clean([finding])
    assert f.exists() and "değişmiş" in result.skipped[0][1]


def test_executable_planted_in_cwd_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    planted = str(tmp_path / "npm.cmd")
    assert resolve_executable("npm", which=lambda _: planted) is None
    assert resolve_executable("npm", which=lambda _: r"C:\nodejs\npm.cmd") == r"C:\nodejs\npm.cmd"


def test_native_runs_in_neutral_cwd(tmp_path):
    cache = tmp_path / "npm"
    make_file(cache / "a.bin", 100)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cwd"] = kw.get("cwd")
        (cache / "a.bin").unlink()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    cat = _cache("npm", "npm", native_cmd=("npm", "cache", "clean")).category
    Cleaner(ProtectionPolicy((), (), ()), run=fake_run, which=lambda n: r"C:\bin\npm.cmd").clean(
        [Finding(str(cache), 100, cat, is_dir=True)])
    assert seen["cwd"] and os.path.basename(seen["cwd"]).startswith("otoclean-")
    assert os.path.normcase(seen["cwd"]) != os.path.normcase(os.getcwd())


def test_ineffective_native_command_falls_back(tmp_path):
    cache = tmp_path / "pip"
    make_file(cache / "a.bin", 100)
    noop = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "")  # noqa: E731
    cat = _cache("pip", "pip", native_cmd=("python", "-m", "pip", "cache", "purge")).category
    result = Cleaner(ProtectionPolicy((), (), ()), run=noop, which=lambda n: r"C:\py\python.exe",
                     trash=permanent_delete).clean([Finding(str(cache), 100, cat, is_dir=True)])
    assert not (cache / "a.bin").exists() and result.freed == 100


def test_expand_escapes_glob_chars_in_env(tmp_path, monkeypatch):
    weird = tmp_path / "user[1]"
    (weird / "p" / "Cache").mkdir(parents=True)
    monkeypatch.setenv("OTO_WEIRD", str(weird))
    assert classifier.expand(r"%OTO_WEIRD%\*\Cache") == [str(weird / "p" / "Cache")]
