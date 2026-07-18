import os
import xml.etree.ElementTree as ET

import pytest

from tools.build_repo import get_addon_id, get_addon_version, iter_addon_files


def _write_addon_xml(dir_path, addon_id, version):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "addon.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<addon id="{}" name="Test" version="{}" provider-name="test">'
        "</addon>\n".format(addon_id, version)
    )


def test_get_addon_id(tmp_path):
    _write_addon_xml(tmp_path, "example.addon", "1.2.3")
    assert get_addon_id(str(tmp_path)) == "example.addon"


def test_get_addon_version(tmp_path):
    _write_addon_xml(tmp_path, "example.addon", "1.2.3")
    assert get_addon_version(str(tmp_path)) == "1.2.3"


def test_iter_addon_files_with_explicit_includes(tmp_path):
    _write_addon_xml(tmp_path, "example.addon", "1.0.0")
    (tmp_path / "default.py").write_text("print('hi')\n")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "helper.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("# dev only\n")

    pairs = sorted(
        iter_addon_files(
            str(tmp_path),
            includes=["addon.xml", "default.py", "lib"],
            addon_id="example.addon",
        )
    )
    arcnames = sorted(arcname for _, arcname in pairs)

    assert arcnames == [
        os.path.join("example.addon", "addon.xml"),
        os.path.join("example.addon", "default.py"),
        os.path.join("example.addon", "lib", "helper.py"),
    ]
    for full_path, _ in pairs:
        assert os.path.isfile(full_path)


def test_iter_addon_files_with_includes_none_takes_everything(tmp_path):
    _write_addon_xml(tmp_path, "example.addon", "1.0.0")
    (tmp_path / "icon.png").write_bytes(b"fake-png")

    arcnames = sorted(
        arcname
        for _, arcname in iter_addon_files(str(tmp_path), includes=None, addon_id="example.addon")
    )

    assert arcnames == [
        os.path.join("example.addon", "addon.xml"),
        os.path.join("example.addon", "icon.png"),
    ]
