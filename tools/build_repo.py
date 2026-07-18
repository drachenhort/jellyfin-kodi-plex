"""Build the Kodi addon repository under docs/ from the addons at repo root.

Regenerates docs/addons.xml, docs/addons.xml.md5, and per-addon zips. Run
directly (`python tools/build_repo.py`) or import build_repo() for tests.
Deliberately free of xbmc* imports so it runs under plain Python/CI.
"""

import hashlib
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile


def get_addon_id(source_dir):
    return ET.parse(os.path.join(source_dir, "addon.xml")).getroot().attrib["id"]


def get_addon_version(source_dir):
    return ET.parse(os.path.join(source_dir, "addon.xml")).getroot().attrib["version"]


def iter_addon_files(source_dir, includes, addon_id):
    names = includes if includes is not None else sorted(os.listdir(source_dir))
    for name in names:
        full_path = os.path.join(source_dir, name)
        if os.path.isdir(full_path):
            for dirpath, _dirnames, filenames in os.walk(full_path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    arcname = os.path.join(addon_id, os.path.relpath(file_path, source_dir))
                    yield file_path, arcname
        else:
            yield full_path, os.path.join(addon_id, name)
