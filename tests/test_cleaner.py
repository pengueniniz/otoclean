import os
import subprocess
import time

import pytest
from conftest import make_file

from otoclean.core.cleaner import Cleaner, CleanOptions, permanent_delete
from otoclean.core.models import Finding
from otoclean.core.protected import ProtectionPolicy
from otoclean.core.rules.catalog import LOCATION_RULES, OLD_DOWNLOADS, PROTECTED, _cache

MB = 1024 * 1024


@pytest.fixture
def policy(tmp_path):
    return ProtectionPolicy(roots=(str(tmp_path / "Windows"),), exceptions=(), anchors=())


@pytest.fixture
def trashed():
    return []


@pytest.fixture
def cleaner(policy, trashed):
    def fake_trash(path):
        trashed.append(path)
        permanent_delete(path)
    return Cleaner(policy, trash=fake_trash, which=lambda _: None,
                   empty_bin=lambda: trashed.append("::bin"))


def test_review_file_goes_to_trash(tmp_path, cleaner, trashed):
    f = make_file(tmp_path / "old.zip", MB)
    result = cleaner.clean([Finding(str(f), MB, OLD_DOWNLOADS)])
    assert trashed == [str(f)] and not f.exists()
    assert result.freed == MB and result.deleted == (str(f),)


def test_dry_run_deletes_nothing(tmp_path, cleaner, trashed):
    f = make_file(tmp_path / "old.zip", MB)
    cache_dir = tmp_path / "cache"
    make_file(cache_dir / "a.bin", MB)
    findings = [Finding(str(f), MB, OLD_DOWNLOADS),
                Finding(str(cache_dir), MB, _cache("c", "C").category, is_dir=True)]
    result = cleaner.clean(findings, CleanOptions(dry_run=True))
    assert trashed == [] and f.exists() and (cache_dir / "a.bin").exists()
    assert result.dry_run and result.freed == 2 * MB


def test_danger_category_never_deleted(tmp_path, cleaner, trashed):
    f = make_file(tmp_path / "x.bin", 10)
    result = cleaner.clean([Finding(str(f), 10, PROTECTED)])
    assert f.exists() and trashed == [] and result.skipped


def test_protected_path_blocked_even_if_rule_wrong(tmp_path, cleaner, trashed):
    f = make_file(tmp_path / "Windows" / "System32" / "k.dll", 10)
    result = cleaner.clean([Finding(str(f), 10, OLD_DOWNLOADS)])
    assert f.exists() and trashed == []
    assert "Korumalı" in result.skipped[0][1]


def test_contents_only_keeps_folder_and_respects_min_age(tmp_path, cleaner):
    cache_dir = tmp_path / "temp"
    make_file(cache_dir / "old.tmp", MB, age_days=5)
    make_file(cache_dir / "olddir" / "f.tmp", MB, age_days=5)
    old = time.time() - 5 * 86400
    os.utime(cache_dir / "olddir", (old, old))
    make_file(cache_dir / "fresh.tmp", MB)
    cat = _cache("t", "T", min_age_days=1).category
    result = cleaner.clean([Finding(str(cache_dir), 3 * MB, cat, is_dir=True)])
    assert cache_dir.exists() and (cache_dir / "fresh.tmp").exists()
    assert not (cache_dir / "old.tmp").exists() and not (cache_dir / "olddir").exists()
    assert result.freed == 2 * MB
    assert any("yeni" in why for _, why in result.skipped)


def test_permanent_caches_skips_trash_for_safe(tmp_path, policy, trashed):
    deleted = []
    c = Cleaner(policy, trash=trashed.append, delete=deleted.append, which=lambda _: None)
    cache_dir = tmp_path / "c"
    make_file(cache_dir / "a.bin", 10)
    review = make_file(tmp_path / "r.zip", 10)
    c.clean([Finding(str(cache_dir), 10, _cache("c", "C").category, is_dir=True),
             Finding(str(review), 10, OLD_DOWNLOADS)], CleanOptions(permanent_caches=True))
    assert deleted == [str(cache_dir / "a.bin")]
    assert trashed == [str(review)]  # 🟡 her zaman Geri Dönüşüm Kutusu'na


def test_in_use_file_is_skipped_with_reason(tmp_path, policy):
    def locked(_path):
        raise PermissionError(13, "denied")
    c = Cleaner(policy, trash=locked, which=lambda _: None)
    f = make_file(tmp_path / "x.zip", 10)
    result = c.clean([Finding(str(f), 10, OLD_DOWNLOADS)])
    assert result.freed == 0 and "Erişim reddedildi" in result.skipped[0][1]


def test_missing_path_skipped(tmp_path, cleaner):
    result = cleaner.clean([Finding(str(tmp_path / "gone"), 10, OLD_DOWNLOADS)])
    assert result.skipped[0][1] == "Artık mevcut değil"


def test_recycle_bin_emptied(cleaner, trashed):
    cat = next(r.category for r in LOCATION_RULES if r.category.special == "recycle_bin")
    result = cleaner.clean([Finding("::RecycleBin", 5 * MB, cat)])
    assert trashed == ["::bin"] and result.freed == 5 * MB


def test_native_command_used_and_freed_measured(tmp_path, policy):
    cache_dir = tmp_path / "npm"
    make_file(cache_dir / "a.bin", 2 * MB)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        os.remove(cache_dir / "a.bin")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    cat = _cache("npm", "npm", native_cmd=("npm", "cache", "clean")).category
    c = Cleaner(policy, run=fake_run, which=lambda n: f"C:\\bin\\{n}.cmd")
    result = c.clean([Finding(str(cache_dir), 2 * MB, cat, is_dir=True)])
    assert calls == [["C:\\bin\\npm.cmd", "cache", "clean"]]
    assert result.freed == 2 * MB


def test_native_failure_falls_back_to_file_delete(tmp_path, policy, trashed):
    cache_dir = tmp_path / "npm"
    make_file(cache_dir / "a.bin", MB)
    fail = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "err")  # noqa: E731
    cat = _cache("npm", "npm", native_cmd=("npm", "cache", "clean")).category
    c = Cleaner(policy, run=fail, which=lambda n: n, trash=trashed.append)
    c.clean([Finding(str(cache_dir), MB, cat, is_dir=True)])
    assert trashed == [str(cache_dir / "a.bin")]


def test_unexpected_error_does_not_stop_others(tmp_path, policy):
    calls = []

    def flaky(path):
        calls.append(path)
        if path.endswith("a.zip"):
            raise RuntimeError("boom")

    c = Cleaner(policy, trash=flaky, which=lambda _: None)
    a, b = make_file(tmp_path / "a.zip", 1), make_file(tmp_path / "b.zip", 1)
    result = c.clean([Finding(str(a), 1, OLD_DOWNLOADS), Finding(str(b), 1, OLD_DOWNLOADS)])
    assert len(calls) == 2 and result.deleted == (str(b),)


def test_progress_reported(tmp_path, cleaner):
    f = make_file(tmp_path / "a.zip", 1)
    seen = []
    cleaner.clean([Finding(str(f), 1, OLD_DOWNLOADS)], progress=lambda i, n, p: seen.append((i, n)))
    assert seen == [(0, 1), (1, 1)]


def test_permanent_delete_readonly(tmp_path):
    d = tmp_path / "ro"
    f = make_file(d / "x.txt", 5)
    os.chmod(f, 0o444)
    permanent_delete(str(d))
    assert not d.exists()
