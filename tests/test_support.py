"""settings, history, scheduler ve auto modülleri."""

import subprocess

import pytest
from conftest import make_file

from otoclean.core import auto, scheduler
from otoclean.core.cleaner import Cleaner, permanent_delete
from otoclean.core.history import History
from otoclean.core.models import CleanResult
from otoclean.core.protected import ProtectionPolicy
from otoclean.core.rules.catalog import LOCATION_RULES, LocationRule, _cache, _cat, R
from otoclean.core.settings import Settings, load_settings, save_settings


# ---------- settings ----------

def test_settings_roundtrip(tmp_path):
    s = Settings().with_changes(permanent_caches=True, schedule_day="MON")
    save_settings(s, str(tmp_path))
    assert load_settings(str(tmp_path)) == s


def test_settings_missing_or_corrupt_returns_defaults(tmp_path):
    assert load_settings(str(tmp_path)) == Settings()
    (tmp_path / "settings.json").write_text("{bozuk", encoding="utf-8")
    assert load_settings(str(tmp_path)) == Settings()


def test_settings_ignores_unknown_and_wrong_types(tmp_path):
    (tmp_path / "settings.json").write_text(
        '{"permanent_caches": "evet", "hack": 1, "use_native": false}', encoding="utf-8")
    s = load_settings(str(tmp_path))
    assert s.permanent_caches is False and s.use_native is False


# ---------- history ----------

def test_history_record_and_recent(tmp_path):
    h = History(str(tmp_path / "h.db"))
    h.record(CleanResult(freed=100, deleted=("a", "b"), skipped=(("c", "kilitli"),)), "manual")
    h.record(CleanResult(freed=50, deleted=("d",)), "auto")
    entries = h.recent()
    assert [e.mode for e in entries] == ["auto", "manual"]
    assert entries[1].deleted_count == 2 and entries[1].skipped_count == 1
    assert h.total_freed() == 150


# ---------- scheduler ----------

class FakeRun:
    def __init__(self, codes):
        self.codes = list(codes)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, self.codes.pop(0), "", "hata")


def test_scheduler_enable_builds_weekly_task():
    run = FakeRun([0])
    scheduler.enable("sun", "09:30", run=run)
    cmd = run.calls[0]
    assert cmd[:3] == ["schtasks", "/Create", "/F"]
    assert cmd[cmd.index("/D") + 1] == "SUN" and cmd[cmd.index("/ST") + 1] == "09:30"
    assert "--auto-safe" in cmd[cmd.index("/TR") + 1]


@pytest.mark.parametrize("day,time_", [("XYZ", "10:00"), ("SUN", "25:00"), ("SUN", "9:00")])
def test_scheduler_rejects_bad_input(day, time_):
    with pytest.raises(ValueError):
        scheduler.enable(day, time_, run=FakeRun([0]))


def test_scheduler_enable_failure_raises():
    with pytest.raises(RuntimeError):
        scheduler.enable(run=FakeRun([1]))


def test_scheduler_is_enabled_and_disable():
    assert scheduler.is_enabled(run=FakeRun([0]))
    assert not scheduler.is_enabled(run=FakeRun([1]))
    scheduler.disable(run=FakeRun([1, 1]))  # zaten yoksa hata vermez
    with pytest.raises(RuntimeError):
        scheduler.disable(run=FakeRun([1, 0]))


# ---------- auto ----------

def test_auto_rules_only_safe_auto_ok_and_admin_filter():
    non_admin = auto.auto_rules(LOCATION_RULES, admin=False)
    assert non_admin
    for r in non_admin:
        assert r.category.auto_ok and not r.category.needs_admin
    assert len(auto.auto_rules(LOCATION_RULES, admin=True)) > len(non_admin)


def test_run_auto_safe_cleans_only_auto_categories(tmp_path, monkeypatch):
    monkeypatch.setenv("OTO_TEST", str(tmp_path))
    make_file(tmp_path / "safe" / "a.bin", 100, age_days=3)
    make_file(tmp_path / "review" / "b.bin", 100, age_days=3)
    rules = (
        _cache("s", "S", r"%OTO_TEST%\safe"),
        _cache("m", "Manual", r"%OTO_TEST%\safe2", auto_ok=False),
        LocationRule(_cat("r", "R", R, why="w", if_deleted="i", contents_only=True),
                     (r"%OTO_TEST%\review",)),
    )
    policy = ProtectionPolicy((), (), ())
    hist = History(str(tmp_path / "h.db"))
    result = auto.run_auto_safe(
        policy=policy, history=hist, settings=Settings(), rules=rules,
        cleaner=Cleaner(policy, trash=permanent_delete, which=lambda _: None))
    assert result.deleted == (str(tmp_path / "safe" / "a.bin"),)
    assert (tmp_path / "review" / "b.bin").exists()
    assert hist.recent()[0].mode == "auto"
