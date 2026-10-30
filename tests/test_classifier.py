import os

import pytest
from conftest import make_file

from otoclean.core import classifier
from otoclean.core.models import Finding, RiskLevel
from otoclean.core.protected import ProtectionPolicy
from otoclean.core.rules.catalog import (ALL_CATEGORIES, LOCATION_RULES, LocationRule,
                                         OLD_DOWNLOADS, _cache, _cat)

MB = 1024 * 1024


@pytest.fixture
def policy(tmp_path):
    return ProtectionPolicy(roots=(str(tmp_path / "Windows"),),
                            exceptions=(str(tmp_path / "Windows" / "Temp"),), anchors=())


def test_catalog_keys_unique_and_described():
    keys = [c.key for c in ALL_CATEGORIES]
    assert len(keys) == len(set(keys))
    for c in ALL_CATEGORIES:
        assert c.why and c.if_deleted and c.name


def test_only_safe_categories_auto_ok():
    for c in ALL_CATEGORIES:
        if c.auto_ok:
            assert c.risk is RiskLevel.SAFE


def test_danger_rules_have_advice():
    for rule in LOCATION_RULES:
        if rule.category.risk is RiskLevel.DANGER:
            assert rule.category.advice


def test_expand_env_and_glob(tmp_path, monkeypatch):
    monkeypatch.setenv("OTO_TEST", str(tmp_path))
    (tmp_path / "p1" / "Cache").mkdir(parents=True)
    (tmp_path / "p2" / "Cache").mkdir(parents=True)
    assert len(classifier.expand(r"%OTO_TEST%\*\Cache")) == 2
    assert classifier.expand(r"%OTO_TEST%\missing") == []
    assert classifier.expand(r"%OTO_UNDEFINED_VAR%\x") == []


def test_evaluate_location_rules_measures_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("OTO_TEST", str(tmp_path))
    make_file(tmp_path / "cache" / "a.bin", 3 * MB)
    rule = _cache("t", "Test", r"%OTO_TEST%\cache")
    empty = _cache("e", "Empty", r"%OTO_TEST%\nothing")
    found = classifier.evaluate_location_rules([rule, empty])
    assert len(found) == 1 and found[0].size == 3 * MB and found[0].is_dir


def test_measure_single_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OTO_TEST", str(tmp_path))
    make_file(tmp_path / "thumbcache_1.db", 2 * MB)
    cat = _cat("f", "F", RiskLevel.SAFE, why="w", if_deleted="i")
    found = classifier.evaluate_location_rules([LocationRule(cat, (r"%OTO_TEST%\thumbcache_*.db",))])
    assert found[0].size == 2 * MB and not found[0].is_dir


def test_recycle_bin_rule_uses_winapi(monkeypatch):
    monkeypatch.setattr(classifier.winapi, "recycle_bin_info", lambda: (5 * MB, 3))
    rule = next(r for r in LOCATION_RULES if r.category.special == "recycle_bin")
    found = classifier.evaluate_location_rules([rule])
    assert found[0].size == 5 * MB and found[0].path == "::RecycleBin"


def test_recycle_bin_failure_is_skipped(monkeypatch):
    def boom():
        raise OSError("x")
    monkeypatch.setattr(classifier.winapi, "recycle_bin_info", boom)
    rule = next(r for r in LOCATION_RULES if r.category.special == "recycle_bin")
    assert classifier.evaluate_location_rules([rule]) == []


def test_contents_only_inside_exception_allowed(tmp_path, policy):
    cat = _cache("t", "T").category
    f = Finding(path=str(tmp_path / "Windows" / "Temp"), size=1, category=cat, is_dir=True)
    assert classifier.apply_protection([f], policy) == [f]


def test_protected_selectable_finding_removed(tmp_path, policy):
    f = Finding(path=str(tmp_path / "Windows" / "System32"), size=1, category=OLD_DOWNLOADS)
    assert classifier.apply_protection([f], policy) == []


def test_dedupe_removes_nested_and_identical(tmp_path):
    cat = OLD_DOWNLOADS
    outer = Finding(path=str(tmp_path / "a"), size=10, category=cat, is_dir=True)
    inner = Finding(path=str(tmp_path / "a" / "b.bin"), size=5, category=cat)
    same = Finding(path=str(tmp_path / "A"), size=10, category=cat, is_dir=True)
    sibling = Finding(path=str(tmp_path / "ab"), size=1, category=cat)
    result = classifier.dedupe([inner, outer, same, sibling])
    assert {f.path for f in result} == {outer.path, sibling.path}


def test_quick_scan_end_to_end(tmp_path, monkeypatch, policy):
    monkeypatch.setenv("OTO_TEST", str(tmp_path))
    make_file(tmp_path / "cache" / "a.bin", MB)
    make_file(tmp_path / "dl" / "setup.msi", MB, age_days=60)
    make_file(tmp_path / "code" / "app" / "node_modules" / "x.js", 2 * MB, age_days=300)
    make_file(tmp_path / "code" / "app" / "package.json", 1, age_days=300)
    statuses = []

    found = classifier.quick_scan(
        policy=policy, rules=[_cache("t", "Test", r"%OTO_TEST%\cache")],
        project_roots=[str(tmp_path / "code")], downloads_dir=str(tmp_path / "dl"),
        status=statuses.append)

    keys = [f.category.key for f in found]
    assert keys[0] == "t"  # 🟢 önce gelir
    assert set(keys) == {"t", "old_installers", "stale_node_modules"}
    assert statuses


def test_deep_scan_finds_large_old_and_duplicates(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(classifier, "DEEP_SCAN_FILE_THRESHOLD", 1)
    data = os.urandom(50_000)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "a.bin").write_bytes(data)
    (tmp_path / "b.bin").write_bytes(data)

    result, found = classifier.deep_scan(str(tmp_path), policy=policy)

    assert result.total_files == 2
    assert [f.category.key for f in found] == ["duplicates"]


def test_deep_scan_never_offers_duplicate_original_as_large_old(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(classifier, "DEEP_SCAN_FILE_THRESHOLD", 1)
    monkeypatch.setattr(classifier, "LARGE_OLD_MIN_SIZE", 1)
    old = 1_000_000_000  # 2001
    monkeypatch.setattr("otoclean.core.detectors.large_old._created", lambda p: old)
    data = os.urandom(50_000)
    other = tmp_path / "solo.bin"
    other.write_bytes(os.urandom(50_000))
    os.utime(other, (old, old))
    for p in (tmp_path / "a.bin", tmp_path / "x" / "b.bin"):
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(data)
        os.utime(p, (old, old))
    progress = []

    _, found = classifier.deep_scan(str(tmp_path), policy=policy,
                                    progress=lambda d, t, p: progress.append((d, t, p)))

    keys = {(os.path.basename(f.path), f.category.key) for f in found}
    assert keys == {("b.bin", "duplicates"), ("solo.bin", "large_old")}  # a.bin (asıl) yok
    assert any(p == "kopya doğrulama" for *_, p in progress)


def test_remeasure_after_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(classifier.winapi, "recycle_bin_info", lambda: (0, 0))
    gone = Finding(str(tmp_path / "gone.zip"), 10, OLD_DOWNLOADS)
    locked = make_file(tmp_path / "locked.zip", 10)
    partial = tmp_path / "cache"
    make_file(partial / "left.bin", 3)
    empty = tmp_path / "empty"
    empty.mkdir()
    cat = _cache("c", "C").category
    bin_cat = next(r.category for r in LOCATION_RULES if r.category.special == "recycle_bin")
    result = classifier.remeasure([
        gone, Finding(str(locked), 10, OLD_DOWNLOADS),
        Finding(str(partial), 999, cat, is_dir=True), Finding(str(empty), 5, cat, is_dir=True),
        Finding("::RecycleBin", 50, bin_cat)])
    assert [(os.path.basename(f.path), f.size) for f in result] == [("locked.zip", 10), ("cache", 3)]


def test_deep_scan_ignores_app_files(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(classifier, "DEEP_SCAN_FILE_THRESHOLD", 1)
    data = os.urandom(50_000)
    for p in (tmp_path / "AppData" / "Programs" / "a" / "ffmpeg.exe",
              tmp_path / "AppData" / "Programs" / "b" / "ffmpeg.exe"):
        p.parent.mkdir(parents=True)
        p.write_bytes(data)
    _, found = classifier.deep_scan(str(tmp_path), policy=policy)
    assert found == []


def test_summarize():
    fs = [Finding("a", 5, OLD_DOWNLOADS), Finding("b", 7, _cache("s", "S").category)]
    totals = classifier.summarize(fs)
    assert totals[RiskLevel.REVIEW] == 5 and totals[RiskLevel.SAFE] == 7


def test_deep_scan_includes_safe_and_danger_only_within_root(tmp_path, policy):
    from otoclean.core.rules.catalog import PROTECTED

    root = tmp_path / "drive"
    cache = make_file(root / "cache" / "small.bin", 12)
    protected = make_file(root / "pagefile.sys", 24)
    outside = make_file(tmp_path / "drive-other" / "cache" / "outside.bin", 48)
    rules = [
        _cache("cache", "Cache", str(cache.parent), str(outside.parent)),
        LocationRule(PROTECTED, (str(protected),)),
        next(r for r in LOCATION_RULES if r.category.special == "recycle_bin"),
    ]

    result, found = classifier.deep_scan(str(root), policy=policy, rules=rules)

    assert result.total_files == 2
    assert [(f.path, f.risk, f.size) for f in found] == [
        (str(cache.parent), RiskLevel.SAFE, 12),
        (str(protected), RiskLevel.DANGER, 24),
    ]


def test_deep_scan_cancel_during_location_rules(tmp_path, policy):
    import threading

    cancel = threading.Event()
    cache = make_file(tmp_path / "cache" / "small.bin", 12)
    rule = _cache("cache", "Cancel here", str(cache.parent))

    def status(message):
        if message == "Cancel here":
            cancel.set()

    result, found = classifier.deep_scan(str(tmp_path), policy=policy, rules=[rule],
                                         cancel=cancel, status=status)
    assert result.cancelled
    assert found == []
