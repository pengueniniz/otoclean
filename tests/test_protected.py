import os

import pytest

from otoclean.core.protected import ProtectionPolicy, default_policy, is_within


@pytest.fixture
def policy(tmp_path):
    sysroot = tmp_path / "Windows"
    return ProtectionPolicy(
        roots=(str(sysroot), str(tmp_path / "Docs")),
        exceptions=(str(sysroot / "Temp"),),
        anchors=(str(tmp_path / "home"),),
    )


def test_path_under_protected_root_is_protected(policy, tmp_path):
    assert policy.is_protected(str(tmp_path / "Windows" / "System32" / "x.dll"))


def test_exception_inside_protected_root_is_allowed(policy, tmp_path):
    assert not policy.is_protected(str(tmp_path / "Windows" / "Temp" / "a.tmp"))


def test_exception_root_itself_cannot_be_deleted(policy, tmp_path):
    assert policy.is_protected(str(tmp_path / "Windows" / "Temp"))


def test_ancestor_of_protected_root_is_protected(policy, tmp_path):
    assert policy.is_protected(str(tmp_path))


def test_anchor_itself_protected_but_children_free(policy, tmp_path):
    assert policy.is_protected(str(tmp_path / "home"))
    assert not policy.is_protected(str(tmp_path / "home" / "cache" / "f.bin"))


def test_drive_root_protected(policy):
    assert policy.reason("C:\\") == "Sürücü kökü silinemez"


@pytest.mark.parametrize("name", ["pagefile.sys", "hiberfil.sys", "NTUSER.DAT"])
def test_system_file_names_protected(policy, tmp_path, name):
    assert policy.is_protected(str(tmp_path / "other" / name))


@pytest.mark.parametrize("part", [".git", ".ssh", "System Volume Information"])
def test_protected_dir_components(policy, tmp_path, part):
    assert policy.is_protected(str(tmp_path / "proj" / part / "objects" / "ab"))


def test_unrelated_path_free(policy, tmp_path):
    assert policy.reason(str(tmp_path / "proj" / "node_modules" / "x.js")) is None


def test_case_insensitive(policy, tmp_path):
    upper = str(tmp_path / "WINDOWS" / "system32").upper()
    assert policy.is_protected(upper)


def test_personal_folder_allows_only_reproducible_artifacts(tmp_path):
    docs = tmp_path / "OneDrive"
    pol = ProtectionPolicy(roots=(), exceptions=(), anchors=(), personal=(str(docs),))
    (docs / "proje" / "node_modules").mkdir(parents=True)
    (docs / "proje" / "package.json").write_text("{}")
    (docs / "proje" / "backend" / "venv").mkdir(parents=True)
    (docs / "proje" / "backend" / "venv" / "pyvenv.cfg").write_text("")
    (docs / "Vergi" / "target").mkdir(parents=True)

    assert pol.is_protected(str(docs / "proje" / "rapor.docx"))
    assert pol.is_protected(str(docs / "proje"))
    assert pol.is_protected(str(docs))
    assert not pol.is_protected(str(docs / "proje" / "node_modules"))
    assert not pol.is_protected(str(docs / "proje" / "backend" / "venv" / "Lib" / "x.py"))
    # İşaret dosyası (Cargo.toml) olmayan "target" kişisel veridir
    assert pol.is_protected(str(docs / "Vergi" / "target" / "beyanname.pdf"))


def test_is_within_rejects_prefix_sibling(tmp_path):
    assert not is_within(str(tmp_path / "Windows2"), str(tmp_path / "Windows"))


def test_default_policy_real_windows():
    pol = default_policy()
    windir = os.environ.get("WINDIR", r"C:\Windows")
    assert pol.is_protected(os.path.join(windir, "System32"))
    assert pol.is_protected(os.path.join(windir, "Installer", "a.msi"))
    assert not pol.is_protected(os.path.join(windir, "Temp", "x.log"))
    home = os.environ["USERPROFILE"]
    assert pol.is_protected(home)
    assert pol.is_protected(os.path.join(home, "Documents", "cv.docx"))
    assert not pol.is_protected(os.path.join(home, "AppData", "Local", "npm-cache", "x"))
