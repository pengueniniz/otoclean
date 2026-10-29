from otoclean.core import junk
from otoclean.core.models import Finding
from otoclean.core.rules.catalog import LOCATION_RULES, OLD_DOWNLOADS, PROTECTED, _cache

CHROME = next(r.category for r in LOCATION_RULES if r.category.key == "chrome_cache")
NPM = next(r.category for r in LOCATION_RULES if r.category.key == "npm_cache")
WIN_TEMP = next(r.category for r in LOCATION_RULES if r.category.key == "windows_temp")
BIN = next(r.category for r in LOCATION_RULES if r.category.special == "recycle_bin")


def test_select_junk_only_safe_and_never_review_or_danger():
    findings = [Finding("a", 1, CHROME), Finding("b", 1, OLD_DOWNLOADS),
                Finding("c", 1, PROTECTED), Finding("::RecycleBin", 1, BIN),
                Finding("d", 1, WIN_TEMP)]
    assert [f.path for f in junk.select_junk(findings, admin=False)] == ["a"]
    assert [f.path for f in junk.select_junk(findings, admin=True)] == ["a", "d"]


def test_group_junk_sorted_by_size():
    groups = junk.group_junk([Finding("a", 5, CHROME), Finding("b", 7, CHROME),
                              Finding("c", 100, NPM)])
    assert [(g.category.key, g.count, g.size) for g in groups] == [
        ("npm_cache", 1, 100), ("chrome_cache", 2, 12)]


def test_group_method_text():
    g_npm = junk.JunkGroup(NPM, 1, 1)
    g_chrome = junk.JunkGroup(CHROME, 1, 1)
    assert "npm cache clean" in g_npm.method(permanent=False, use_native=True)
    assert g_npm.method(permanent=True, use_native=False) == "Kalıcı silinir"
    assert g_chrome.method(permanent=False, use_native=True) == "Geri Dönüşüm Kutusu'na taşınır"


def test_running_blockers_detects_open_apps():
    findings = [Finding("a", 1, CHROME), Finding("b", 1, NPM)]
    assert junk.running_blockers(findings, process_names=lambda: {"chrome.exe", "x.exe"}) == [
        "Google Chrome"]
    assert junk.running_blockers(findings, process_names=lambda: {"x.exe"}) == []


def test_running_blockers_tolerates_errors():
    def boom():
        raise RuntimeError("psutil yok")
    assert junk.running_blockers([Finding("a", 1, CHROME)], process_names=boom) == []


def test_running_blockers_skips_when_no_app_caches():
    called = []
    junk.running_blockers([Finding("a", 1, _cache("x", "X").category)],
                          process_names=lambda: called.append(1) or set())
    assert called == []
