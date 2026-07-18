import hashlib
import os
import xml.etree.ElementTree as ET
import zipfile

import pytest

from tools.build_repo import (
    build_addon_zip,
    build_addons_xml,
    copy_icon,
    get_addon_id,
    get_addon_version,
    iter_addon_files,
    write_addons_xml_md5,
)


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


def test_build_addon_zip_creates_zip_with_expected_arcnames(tmp_path):
    source_dir = tmp_path / "src"
    _write_addon_xml(source_dir, "example.addon", "1.0.0")
    (source_dir / "default.py").write_text("print('hi')\n")
    output_dir = tmp_path / "docs" / "example.addon"

    zip_path = build_addon_zip(
        str(source_dir),
        includes=["addon.xml", "default.py"],
        addon_id="example.addon",
        version="1.0.0",
        output_dir=str(output_dir),
    )

    assert zip_path == str(output_dir / "example.addon-1.0.0.zip")
    with zipfile.ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == [
            "example.addon/addon.xml",
            "example.addon/default.py",
        ]


def test_build_addon_zip_skips_if_already_exists(tmp_path):
    source_dir = tmp_path / "src"
    _write_addon_xml(source_dir, "example.addon", "1.0.0")
    output_dir = tmp_path / "docs" / "example.addon"
    output_dir.mkdir(parents=True)
    existing_zip = output_dir / "example.addon-1.0.0.zip"
    existing_zip.write_bytes(b"not-actually-a-zip")

    zip_path = build_addon_zip(
        str(source_dir),
        includes=["addon.xml"],
        addon_id="example.addon",
        version="1.0.0",
        output_dir=str(output_dir),
    )

    assert zip_path == str(existing_zip)
    assert existing_zip.read_bytes() == b"not-actually-a-zip"


def test_copy_icon(tmp_path):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "icon.png").write_bytes(b"fake-png")
    output_dir = tmp_path / "docs" / "example.addon"
    output_dir.mkdir(parents=True)

    copy_icon(str(source_dir), str(output_dir))

    assert (output_dir / "icon.png").read_bytes() == b"fake-png"


def test_build_addons_xml_concatenates_addons(tmp_path):
    addon_a = tmp_path / "a"
    addon_b = tmp_path / "b"
    _write_addon_xml(addon_a, "addon.a", "1.0.0")
    _write_addon_xml(addon_b, "addon.b", "2.0.0")
    docs_dir = tmp_path / "docs"

    addons_xml_path = build_addons_xml([str(addon_a), str(addon_b)], str(docs_dir))

    assert addons_xml_path == str(docs_dir / "addons.xml")
    root = ET.parse(addons_xml_path).getroot()
    assert root.tag == "addons"
    ids = [child.attrib["id"] for child in root.findall("addon")]
    assert ids == ["addon.a", "addon.b"]


def test_write_addons_xml_md5_matches_file_contents(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    addons_xml_path = docs_dir / "addons.xml"
    addons_xml_path.write_text("<addons></addons>\n")

    md5_path = write_addons_xml_md5(str(addons_xml_path))

    assert md5_path == str(addons_xml_path) + ".md5"
    expected = hashlib.md5(addons_xml_path.read_bytes()).hexdigest()
    assert (docs_dir / "addons.xml.md5").read_text() == expected
