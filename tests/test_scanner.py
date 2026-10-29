import threading

from conftest import make_file, make_junction

from otoclean.core.scanner import folder_stats, scan_tree

MB = 1024 * 1024


def test_scan_aggregates_sizes_bottom_up(tmp_path):
    make_file(tmp_path / "a" / "b" / "f1.bin", 3 * MB)
    make_file(tmp_path / "a" / "f2.bin", 2 * MB)
    make_file(tmp_path / "root.bin", 1 * MB)

    res = scan_tree(str(tmp_path), min_dir_size=0, large_threshold=10 * MB)

    sizes = {d.path: d.size for d in res.dirs}
    assert sizes[str(tmp_path / "a" / "b")] == 3 * MB
    assert sizes[str(tmp_path / "a")] == 5 * MB
    assert res.total_size == 6 * MB
    assert res.total_files == 3


def test_large_files_reported_sorted(tmp_path):
    make_file(tmp_path / "x" / "small.bin", 1 * MB)
    make_file(tmp_path / "x" / "big.bin", 5 * MB)
    make_file(tmp_path / "bigger.bin", 8 * MB)

    res = scan_tree(str(tmp_path), large_threshold=4 * MB)

    assert [p for p, *_ in res.large_files] == [
        str(tmp_path / "bigger.bin"), str(tmp_path / "x" / "big.bin")]


def test_junctions_are_not_followed(tmp_path):
    target = tmp_path / "real"
    make_file(target / "data.bin", 4 * MB)
    make_junction(tmp_path / "link", target)

    res = scan_tree(str(tmp_path), min_dir_size=0)

    assert res.total_size == 4 * MB
    assert str(tmp_path / "link") not in {d.path for d in res.dirs}


def test_min_dir_size_filters_small_dirs(tmp_path):
    make_file(tmp_path / "tiny" / "t.bin", 10)
    make_file(tmp_path / "huge" / "h.bin", 2 * MB)

    res = scan_tree(str(tmp_path), min_dir_size=MB)

    paths = {d.path for d in res.dirs}
    assert str(tmp_path / "huge") in paths
    assert str(tmp_path / "tiny") not in paths


def test_cancel_stops_scan(tmp_path):
    for i in range(20):
        make_file(tmp_path / f"d{i}" / "f.bin", 10)
    cancel = threading.Event()
    cancel.set()

    res = scan_tree(str(tmp_path), cancel=cancel, min_dir_size=0)

    assert res.cancelled
    assert res.total_files < 20


def test_progress_callback_invoked(tmp_path, monkeypatch):
    import otoclean.core.scanner as sc
    monkeypatch.setattr(sc, "PROGRESS_EVERY", 1)
    for i in range(3):
        make_file(tmp_path / f"d{i}" / "f.bin", 10)
    calls = []

    scan_tree(str(tmp_path), progress=lambda d, f, p: calls.append((d, f)))

    assert calls and calls[-1][0] == 3


def test_missing_root_returns_error(tmp_path):
    res = scan_tree(str(tmp_path / "yok"))
    assert res.errors and res.total_size == 0


def test_folder_stats(tmp_path):
    make_file(tmp_path / "c" / "1.bin", MB)
    make_file(tmp_path / "c" / "sub" / "2.bin", MB)

    st = folder_stats(str(tmp_path / "c"))

    assert (st.size, st.file_count) == (2 * MB, 2)


def test_folder_stats_on_file(tmp_path):
    f = make_file(tmp_path / "one.bin", 123)
    assert folder_stats(str(f)).size == 123
