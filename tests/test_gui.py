import os

import pytest
from PySide6.QtCore import Qt

from otoclean.core.models import DirStat, Finding, RiskLevel, ScanResult, human_size
from otoclean.core.rules.catalog import LOCATION_RULES, OLD_DOWNLOADS, PROTECTED, _cache
from otoclean.gui.findings_view import COL_NAME, FindingsTree, default_checked
from otoclean.gui.treemap import TreemapWidget, squarify

SAFE_CAT = _cache("c", "Cache").category
ADMIN_CAT = _cache("a", "Admin", needs_admin=True).category


# ---------- squarify ----------

def test_squarify_fills_area_exactly():
    rects = squarify([6, 6, 4, 3, 2, 2, 1], 0, 0, 6, 4)
    assert len(rects) == 7
    assert sum(w * h for _, _, w, h in rects) == pytest.approx(24)
    for x, y, w, h in rects:
        assert x >= -1e-9 and y >= -1e-9 and x + w <= 6 + 1e-9 and y + h <= 4 + 1e-9


def test_squarify_handles_empty_and_zero():
    assert squarify([], 0, 0, 10, 10) == []
    assert squarify([0, 0], 0, 0, 10, 10) == []
    assert squarify([5], 0, 0, 0, 10) == []


# ---------- findings tree ----------

def test_default_checked_rules():
    assert default_checked(Finding("a", 1, SAFE_CAT), admin=False)
    assert not default_checked(Finding("a", 1, ADMIN_CAT), admin=False)
    assert default_checked(Finding("a", 1, ADMIN_CAT), admin=True)
    assert not default_checked(Finding("a", 1, OLD_DOWNLOADS), admin=True)
    bin_cat = next(r.category for r in LOCATION_RULES if r.category.special == "recycle_bin")
    assert not default_checked(Finding("::RecycleBin", 1, bin_cat), admin=True)


@pytest.fixture
def tree(qtbot):
    t = FindingsTree()
    qtbot.addWidget(t)
    t.set_findings([Finding("C:\\x\\cache", 100, SAFE_CAT, is_dir=True),
                    Finding("C:\\dl\\a.zip", 50, OLD_DOWNLOADS),
                    Finding("C:\\pagefile.sys", 999, PROTECTED)], admin=False)
    return t


def test_tree_groups_and_default_selection(tree):
    assert tree.topLevelItemCount() == 3
    assert [f.path for f in tree.checked_findings()] == ["C:\\x\\cache"]
    assert len(tree.all_findings()) == 3


def test_danger_items_not_checkable(tree):
    tree.set_all_checked(RiskLevel.DANGER, True)
    assert all(f.risk is not RiskLevel.DANGER for f in tree.checked_findings())


def test_set_all_checked_review(tree, qtbot):
    with qtbot.waitSignal(tree.checked_changed, timeout=1000):
        tree.set_all_checked(RiskLevel.REVIEW, True)
    assert {f.path for f in tree.checked_findings()} == {"C:\\x\\cache", "C:\\dl\\a.zip"}


def test_risk_filter_hides_other_groups(tree):
    tree.set_risk_filter(RiskLevel.SAFE)
    hidden = [tree.topLevelItem(i).isHidden() for i in range(3)]
    assert hidden == [False, True, True]
    tree.set_risk_filter(None)
    assert not any(tree.topLevelItem(i).isHidden() for i in range(3))


def test_current_item_emits_payload(tree, qtbot):
    leaf = tree.topLevelItem(0).child(0).child(0)
    with qtbot.waitSignal(tree.current_changed) as sig:
        tree.setCurrentItem(leaf)
    assert sig.args[0].path == "C:\\x\\cache"


# ---------- treemap ----------

def test_treemap_navigation(qtbot, tmp_path):
    root = str(tmp_path)
    a, b = os.path.join(root, "a"), os.path.join(root, "a", "b")
    result = ScanResult(root=root, dirs=(DirStat(a, 80, 1, 0), DirStat(b, 50, 1, 0)), total_size=100)
    w = TreemapWidget()
    qtbot.addWidget(w)
    w.resize(400, 300)
    w.set_scan(result, lambda p: RiskLevel.SAFE if p == a else None)
    assert {p for _, p, _ in w._boxes} == {a, "::other"}
    w.navigate(a)
    assert {p for _, p, _ in w._boxes} == {b, "::other"}
    w.go_up()
    assert w._current == os.path.normpath(root)


def test_treemap_root_is_not_its_own_child(qtbot):
    result = ScanResult(root="D:\\", total_size=100,
                        dirs=(DirStat("D:\\", 100, 2, 0), DirStat("D:\\a", 60, 1, 0)))
    w = TreemapWidget()
    qtbot.addWidget(w)
    w.resize(400, 300)
    w.set_scan(result, lambda p: None)
    assert sorted((p, s) for _, p, s in w._boxes) == [("::other", 40), ("D:\\a", 60)]


# ---------- main window ----------

@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("otoclean.core.scheduler.is_enabled", lambda **kw: False)
    from otoclean.gui.main_window import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def test_main_window_shows_findings_and_totals(window):
    window._on_quick_done([Finding("C:\\x\\cache", 2048, SAFE_CAT, is_dir=True),
                           Finding("C:\\dl\\a.zip", 1024, OLD_DOWNLOADS)])
    assert window.tiles[RiskLevel.SAFE].amount.text() == "2,0 KB"
    assert "Seçili: 2,0 KB" == window.selected_label.text()
    assert window.clean_btn.isEnabled()


def test_main_window_filter_toggle(window):
    window._toggle_filter(RiskLevel.REVIEW)
    assert window._risk_filter is RiskLevel.REVIEW
    window._toggle_filter(RiskLevel.REVIEW)
    assert window._risk_filter is None


@pytest.mark.parametrize("level", [RiskLevel.SAFE, RiskLevel.REVIEW, RiskLevel.DANGER])
def test_risk_tile_opens_filtered_findings_after_deep_scan(window, qtbot, level):
    window._on_deep_done((ScanResult(root="C:\\", total_size=2149), [
        Finding("C:\\cache", 100, SAFE_CAT, is_dir=True),
        Finding("C:\\old.zip", 50, OLD_DOWNLOADS),
        Finding("C:\\pagefile.sys", 1999, PROTECTED),
    ]))
    assert window.tabs.currentIndex() == 1

    qtbot.mouseClick(window.tiles[level], Qt.LeftButton)

    assert window.tabs.currentWidget() is window.findings_stack
    assert window._risk_filter is level
    assert window.tiles[RiskLevel.SAFE].amount.text() == "100 B"
    assert window.tiles[RiskLevel.DANGER].amount.text() == human_size(1999)
    assert [window.tree.topLevelItem(i).isHidden() for i in range(3)] == [
        risk is not level for risk in RiskLevel
    ]
    window.tree.set_all_checked(RiskLevel.DANGER, True)
    assert all(f.risk is not RiskLevel.DANGER for f in window.tree.checked_findings())


def test_unscanned_state_shows_empty_page_and_dashes(window):
    assert window.findings_stack.currentIndex() == 0
    assert window.tiles[RiskLevel.SAFE].amount.text() == "—"
    window._on_quick_done([])
    assert window.findings_stack.currentIndex() == 1
    assert window.tiles[RiskLevel.SAFE].amount.text() == "0 B"


def test_theme_switch_keeps_findings_selection_and_saves(window, qtbot, tmp_path):
    from otoclean.core.settings import load_settings
    from otoclean.gui import theme
    window._on_quick_done([Finding("C:\\x\\cache", 2048, SAFE_CAT, is_dir=True),
                           Finding("C:\\dl\\a.zip", 1024, OLD_DOWNLOADS)])
    window.tree.set_all_checked(RiskLevel.REVIEW, True)
    window._toggle_filter(RiskLevel.SAFE)
    old_tree = window.tree
    try:
        window._switch_theme("white")
        qtbot.waitUntil(lambda: window.tree is not old_tree, timeout=2000)
        assert theme.PALETTE.key == "white" and theme.PAPER == "#FFFFFF"
        assert window.tree.checked_paths() == {"C:\\x\\cache", "C:\\dl\\a.zip"}
        assert window._risk_filter is RiskLevel.SAFE
        assert window.theme_buttons["white"].isChecked()
        assert not window.theme_buttons["paper"].isChecked()
        assert load_settings(str(tmp_path / "OtoClean")).theme == "white"
    finally:
        theme.use("paper")


def test_both_themes_build_stylesheets():
    from otoclean.gui import theme
    try:
        for key in theme.PALETTES:
            theme.use(key)
            assert theme.PALETTE.paper in theme.STYLESHEET and "check.svg" in theme.STYLESHEET
    finally:
        theme.use("paper")


def test_junk_flow_previews_then_cleans_only_safe(window, qtbot, tmp_path, monkeypatch):
    from otoclean.gui import main_window as mw
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "a.bin").write_bytes(b"x" * 10)
    review = tmp_path / "old.zip"
    review.write_bytes(b"y" * 10)
    window._on_quick_done([Finding(str(cache), 10, SAFE_CAT, is_dir=True),
                           Finding(str(review), 10, OLD_DOWNLOADS)])
    window.dry_cb.setChecked(True)
    seen = {}

    class FakeDialog:
        Accepted = 1

        def __init__(self, groups, **kw):
            seen["groups"] = [(g.category.key, g.size) for g in groups]
            seen["kw"] = kw
            self.permanent = False

        def exec(self):
            return 1

    monkeypatch.setattr(mw, "JunkPreviewDialog", FakeDialog)
    results = []
    monkeypatch.setattr("otoclean.gui.dialogs.show_result", lambda _w, r: results.append(r))
    window._start_junk()  # Tarama taze: doğrudan önizleme
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert seen["groups"] == [("c", 10)]
    assert seen["kw"]["excluded_review"] == 10 and seen["kw"]["dry_run"] is True
    assert results[0].dry_run and results[0].freed == 10
    assert review.exists() and (cache / "a.bin").exists()


def test_junk_flow_end_to_end_real_delete(window, qtbot, tmp_path, monkeypatch):
    """Sahte önbellekle gerçek silme: 🟢 gider, 🟡 kalır, geçmişe yazılır, liste güncellenir."""
    from otoclean.gui import main_window as mw
    from otoclean.core.protected import ProtectionPolicy
    window._policy = ProtectionPolicy((), (), ())
    cache = tmp_path / "sandbox_cache"
    for i in range(5):
        p = cache / f"sub{i}" / "blob.bin"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"z" * 100)
    old = __import__("time").time() - 3 * 86400
    for d in cache.iterdir():
        os.utime(d / "blob.bin", (old, old))
        os.utime(d, (old, old))
    review = tmp_path / "keep.zip"
    review.write_bytes(b"k" * 50)
    window._on_quick_done([Finding(str(cache), 500, SAFE_CAT, is_dir=True),
                           Finding(str(review), 50, OLD_DOWNLOADS)])

    class Accept:
        Accepted = 1

        def __init__(self, *a, **kw):
            self.permanent = True

        def exec(self):
            return 1

    monkeypatch.setattr(mw, "JunkPreviewDialog", Accept)
    results = []
    monkeypatch.setattr("otoclean.gui.dialogs.show_result", lambda _w, r: results.append(r))
    window._start_junk()
    qtbot.waitUntil(lambda: bool(results) and window._task is None, timeout=10000)

    assert results[0].freed == 500 and not results[0].dry_run
    assert cache.exists() and list(cache.iterdir()) == []   # Klasör kalır, içi boşalır
    assert review.exists()                                    # 🟡 dokunulmadı
    assert window.permanent_cb.isChecked()                    # Penceredeki tercih kaydedildi
    assert [f.path for f in window.tree.all_findings()] == [str(review)]
    assert window._history.recent()[0].freed == 500


def test_junk_flow_cancel_deletes_nothing(window, monkeypatch, tmp_path):
    from otoclean.gui import main_window as mw
    f = tmp_path / "c"
    f.mkdir()
    window._on_quick_done([Finding(str(f), 10, SAFE_CAT, is_dir=True)])

    class Reject:
        Accepted = 1

        def __init__(self, *a, **kw):
            self.permanent = False

        def exec(self):
            return 0

    monkeypatch.setattr(mw, "JunkPreviewDialog", Reject)
    started = []
    monkeypatch.setattr(window, "_execute_clean", lambda *a: started.append(a))
    window._start_junk()
    assert started == [] and "iptal" in window.status_label.text()


def test_junk_flow_scans_first_when_stale(window, monkeypatch):
    calls = []

    def fake_start():
        calls.append("scan")
        window._task = object()  # Tarama başladı

    monkeypatch.setattr(window, "_start_quick", fake_start)
    window._start_junk()
    assert calls == ["scan"] and window._junk_after_scan
    window._task = None


def test_junk_flag_not_set_when_scan_did_not_start(window, monkeypatch):
    monkeypatch.setattr(window, "_start_quick", lambda: None)
    window._start_junk()
    assert not window._junk_after_scan


def test_file_names_shown_as_plain_text(qtbot):
    from otoclean.gui.detail_panel import DetailPanel
    panel = DetailPanel()
    qtbot.addWidget(panel)
    # Windows adlarda < > yasak ama & serbest: "&amp;" HTML varlığı gibi yorumlanmamalı
    panel.show_payload(Finding("C:\\dl\\Tom &amp; Jerry.zip", 1, OLD_DOWNLOADS))
    assert panel.title.textFormat() == Qt.PlainText
    assert panel.title.text() == "Tom &amp; Jerry.zip"


def test_junk_preview_dialog_renders(qtbot):
    from otoclean.core.junk import group_junk
    from otoclean.gui.junk_dialog import JunkPreviewDialog
    groups = group_junk([Finding("a", 2048, SAFE_CAT)])
    dlg = JunkPreviewDialog(groups, permanent=False, use_native=True, dry_run=False,
                            excluded_review=5, check_blockers=lambda: ["Google Chrome"])
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.table.topLevelItemCount() == 1
    assert dlg.blocker_box.isVisible() and "Google Chrome" in dlg.blocker_label.text()
    assert "Geri Dönüşüm" in dlg.table.topLevelItem(0).text(3)
    dlg.permanent_cb.setChecked(True)
    assert dlg.table.topLevelItem(0).text(3) == "Kalıcı silinir" and dlg.permanent


def test_clean_flow_dry_run(window, qtbot, tmp_path, monkeypatch):
    f = tmp_path / "old.zip"
    f.write_bytes(b"x" * 10)
    window._on_quick_done([Finding(str(f), 10, OLD_DOWNLOADS)])
    window.tree.set_all_checked(RiskLevel.REVIEW, True)
    window.dry_cb.setChecked(True)
    monkeypatch.setattr("otoclean.gui.dialogs.confirm_clean", lambda *a: True)
    shown = []
    monkeypatch.setattr("otoclean.gui.dialogs.show_result", lambda _w, r: shown.append(r))
    window._start_clean()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)
    assert shown[0].dry_run and shown[0].freed == 10 and f.exists()
