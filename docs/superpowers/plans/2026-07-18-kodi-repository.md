# Kodi Repository for Auto-Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Kodi auto-update `script.jellyfin.plex` by publishing a Kodi-compatible addon
repository (a `repository.jellyfinplex` addon + `addons.xml`/zips served via GitHub Pages) that's
regenerated automatically by CI whenever the addon's version is bumped.

**Architecture:** A new `repository.jellyfinplex/` addon at the repo root is the one-time-install
pointer Kodi uses to find updates. `tools/build_repo.py` is a pure-Python script (no `xbmc*`
imports) that reads both addons' `addon.xml` files, zips their source into
`docs/<id>/<id>-<version>.zip`, and writes `docs/addons.xml` + `docs/addons.xml.md5`. A GitHub
Actions workflow runs it on every push that changes an `addon.xml`, committing the regenerated
`docs/` output back to `master`, which GitHub Pages serves.

**Tech Stack:** Python 3 standard library only (`xml.etree.ElementTree`, `zipfile`, `hashlib`,
`shutil`, `os`) — no new dependencies. pytest for tests. GitHub Actions for CI.

## Global Constraints

- No `xbmc*` imports in `tools/build_repo.py` — keep it plain-Python and testable like
  `lib/jellyfin/*` (see `CLAUDE.md`).
- `docs/` contents (except `docs/superpowers/`) are **generated, not hand-edited** — never edit
  files under `docs/script.jellyfin.plex/`, `docs/repository.jellyfinplex/`, `docs/addons.xml`, or
  `docs/addons.xml.md5` directly; regenerate via `tools/build_repo.py`.
- `script.jellyfin.plex`'s addon source lives at the **repo root itself** (there is no
  `script.jellyfin.plex/` subfolder in this repo) — the packaged zip must include only
  `addon.xml`, `default.py`, `service.py`, `icon.png`, `lib/`, `resources/`, and exclude every
  other root-level entry (`tests/`, `docs/`, `tools/`, `.github/`, `README*.md`, `CLAUDE.md`,
  `requirements-dev.txt`, `pytest.ini`, `screenshots/`, `.venv/`, `.git/`, `.gitignore`,
  `.claude/`, `.pytest_cache/`).
- `repository.jellyfinplex`'s addon source lives in its own `repository.jellyfinplex/` subfolder —
  zip its entire contents.
- Per standing project convention, any `README.md` change must be mirrored in `README.de.md` in
  the same commit.
- Per project convention, run `pytest` before every commit that touches Python code.

---

### Task 1: `repository.jellyfinplex` addon

**Files:**
- Create: `repository.jellyfinplex/addon.xml`
- Create: `repository.jellyfinplex/icon.png` (copy of the root `icon.png`)
- Test: `tests/test_repository_addon.py`

**Interfaces:**
- Produces: a valid Kodi repository addon at `repository.jellyfinplex/addon.xml` with id
  `repository.jellyfinplex`, version `1.0.0`, and an `xbmc.addon.repository` extension whose
  `info`/`checksum`/`datadir` URLs point at
  `https://drachenhort.github.io/jellyfin-kodi-plex/`. Later tasks (`tools/build_repo.py`) read
  this file's `id` and `version` attributes and zip its directory as-is.

- [ ] **Step 1: Write the failing test**

Create `tests/test_repository_addon.py`:

```python
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_XML = REPO_ROOT / "repository.jellyfinplex" / "addon.xml"


def test_repository_addon_xml_is_well_formed():
    root = ET.parse(ADDON_XML).getroot()
    assert root.tag == "addon"
    assert root.attrib["id"] == "repository.jellyfinplex"
    assert root.attrib["version"] == "1.0.0"


def test_repository_addon_declares_repository_extension():
    root = ET.parse(ADDON_XML).getroot()
    ext = root.find("./extension[@point='xbmc.addon.repository']")
    assert ext is not None

    base_url = "https://drachenhort.github.io/jellyfin-kodi-plex/"
    info = ext.find("./dir/info")
    checksum = ext.find("./dir/checksum")
    datadir = ext.find("./dir/datadir")

    assert info.text == base_url + "addons.xml"
    assert checksum.text == base_url + "addons.xml.md5"
    assert datadir.text == base_url


def test_repository_addon_icon_exists():
    assert (REPO_ROOT / "repository.jellyfinplex" / "icon.png").is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repository_addon.py -v`
Expected: FAIL — `repository.jellyfinplex/addon.xml` does not exist
(`FileNotFoundError` or similar from `ET.parse`).

- [ ] **Step 3: Create the repository addon**

Create `repository.jellyfinplex/addon.xml`:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="repository.jellyfinplex"
       name="Jellyfin (Plex-style) Repository"
       version="1.0.0"
       provider-name="jellyfin-kodi-plex">
  <extension point="xbmc.addon.repository" name="Jellyfin (Plex-style) Repository">
    <dir>
      <info compressed="false">https://drachenhort.github.io/jellyfin-kodi-plex/addons.xml</info>
      <checksum>https://drachenhort.github.io/jellyfin-kodi-plex/addons.xml.md5</checksum>
      <datadir zip="true">https://drachenhort.github.io/jellyfin-kodi-plex/</datadir>
    </dir>
  </extension>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">Repository for the Jellyfin (Plex-style) Kodi addon</summary>
    <description lang="en_GB">
      Install this once to let Kodi automatically discover and install updates
      for the Jellyfin (Plex-style) addon.
    </description>
    <platform>all</platform>
    <license>MIT</license>
    <assets>
      <icon>icon.png</icon>
    </assets>
  </extension>
</addon>
```

Copy the icon:

```bash
cp icon.png repository.jellyfinplex/icon.png
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repository_addon.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add repository.jellyfinplex/addon.xml repository.jellyfinplex/icon.png tests/test_repository_addon.py
git commit -m "Add repository.jellyfinplex addon for Kodi auto-updates"
```

---

### Task 2: `tools/build_repo.py` — addon metadata and file selection

**Files:**
- Create: `tools/build_repo.py`
- Test: `tests/test_build_repo.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (reads arbitrary addon directories passed in by the
  caller/tests).
- Produces:
  - `get_addon_id(source_dir: str) -> str`
  - `get_addon_version(source_dir: str) -> str`
  - `iter_addon_files(source_dir: str, includes: list[str] | None, addon_id: str) -> Iterator[tuple[str, str]]`
    yielding `(absolute_file_path, arcname)` pairs, where `arcname` is rooted at `addon_id/...`.
    `includes=None` means "include everything directly under `source_dir`"; otherwise only the
    named top-level entries (files or directories) are walked.

  These are consumed by Task 3's `build_addon_zip` and `build_addons_xml`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_build_repo.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_build_repo.py -v`
Expected: FAIL — `tools.build_repo` module does not exist (`ModuleNotFoundError`).

- [ ] **Step 3: Write the minimal implementation**

Create `tools/__init__.py` (empty file, makes `tools` importable):

```python
```

Create `tools/build_repo.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_build_repo.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/__init__.py tools/build_repo.py tests/test_build_repo.py
git commit -m "Add addon metadata and file-selection helpers for repo builder"
```

---

### Task 3: `tools/build_repo.py` — zip building, addons.xml, and checksum

**Files:**
- Modify: `tools/build_repo.py`
- Modify: `tests/test_build_repo.py`

**Interfaces:**
- Consumes: `get_addon_id`, `get_addon_version`, `iter_addon_files` from Task 2.
- Produces:
  - `build_addon_zip(source_dir: str, includes: list[str] | None, addon_id: str, version: str, output_dir: str) -> str`
    (returns the zip path; no-ops and returns the existing path if the zip already exists).
  - `copy_icon(source_dir: str, output_dir: str) -> None`
  - `build_addons_xml(source_dirs: list[str], docs_dir: str) -> str` (returns
    `docs/addons.xml` path)
  - `write_addons_xml_md5(addons_xml_path: str) -> str` (returns
    `docs/addons.xml.md5` path)

  Consumed by Task 4's `build_repo()` orchestration function.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build_repo.py`:

```python
import zipfile

from tools.build_repo import (
    build_addon_zip,
    build_addons_xml,
    copy_icon,
    write_addons_xml_md5,
)


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
```

Add `import hashlib` to the top of `tests/test_build_repo.py` alongside the existing imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_build_repo.py -v`
Expected: FAIL — `build_addon_zip`, `copy_icon`, `build_addons_xml`, `write_addons_xml_md5` not
defined (`ImportError`).

- [ ] **Step 3: Write the minimal implementation**

Append to `tools/build_repo.py`:

```python
def build_addon_zip(source_dir, includes, addon_id, version, output_dir):
    zip_path = os.path.join(output_dir, "{}-{}.zip".format(addon_id, version))
    if os.path.exists(zip_path):
        return zip_path
    os.makedirs(output_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path, arcname in iter_addon_files(source_dir, includes, addon_id):
            zf.write(file_path, arcname)
    return zip_path


def copy_icon(source_dir, output_dir):
    icon_path = os.path.join(source_dir, "icon.png")
    if os.path.isfile(icon_path):
        os.makedirs(output_dir, exist_ok=True)
        shutil.copyfile(icon_path, os.path.join(output_dir, "icon.png"))


def build_addons_xml(source_dirs, docs_dir):
    root = ET.Element("addons")
    for source_dir in source_dirs:
        addon_root = ET.parse(os.path.join(source_dir, "addon.xml")).getroot()
        root.append(addon_root)
    os.makedirs(docs_dir, exist_ok=True)
    addons_xml_path = os.path.join(docs_dir, "addons.xml")
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(addons_xml_path, encoding="UTF-8", xml_declaration=True)
    return addons_xml_path


def write_addons_xml_md5(addons_xml_path):
    with open(addons_xml_path, "rb") as f:
        digest = hashlib.md5(f.read()).hexdigest()
    md5_path = addons_xml_path + ".md5"
    with open(md5_path, "w", encoding="utf-8") as f:
        f.write(digest)
    return md5_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_build_repo.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add tools/build_repo.py tests/test_build_repo.py
git commit -m "Add zip, addons.xml, and checksum generation to repo builder"
```

---

### Task 4: Orchestration entry point and initial `docs/` generation

**Files:**
- Modify: `tools/build_repo.py`
- Modify: `tests/test_build_repo.py`

**Interfaces:**
- Consumes: `get_addon_version`, `build_addon_zip`, `copy_icon`, `build_addons_xml`,
  `write_addons_xml_md5` from Tasks 2–3.
- Produces: `build_repo(addons: list[dict], docs_dir: str) -> None`, where each `addons` entry is
  `{"id": str, "source_dir": str, "includes": list[str] | None}`. Also produces the
  module-level `ADDONS` and `DOCS_DIR` constants and a `python -m tools.build_repo` /
  `python tools/build_repo.py` CLI entry point used directly by Task 5's GitHub Actions workflow.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_build_repo.py`:

```python
from tools.build_repo import build_repo


def test_build_repo_generates_zips_and_addons_xml(tmp_path):
    addon_a = tmp_path / "addon.a"
    addon_b = tmp_path / "addon.b"
    _write_addon_xml(addon_a, "addon.a", "1.0.0")
    (addon_a / "icon.png").write_bytes(b"fake-png-a")
    _write_addon_xml(addon_b, "addon.b", "2.0.0")

    docs_dir = tmp_path / "docs"
    addons = [
        {"id": "addon.a", "source_dir": str(addon_a), "includes": None},
        {"id": "addon.b", "source_dir": str(addon_b), "includes": None},
    ]

    build_repo(addons, str(docs_dir))

    assert (docs_dir / "addon.a" / "addon.a-1.0.0.zip").is_file()
    assert (docs_dir / "addon.a" / "icon.png").read_bytes() == b"fake-png-a"
    assert (docs_dir / "addon.b" / "addon.b-2.0.0.zip").is_file()
    assert (docs_dir / "addons.xml").is_file()
    assert (docs_dir / "addons.xml.md5").is_file()

    root = ET.parse(str(docs_dir / "addons.xml")).getroot()
    ids = [child.attrib["id"] for child in root.findall("addon")]
    assert ids == ["addon.a", "addon.b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_build_repo.py -v`
Expected: FAIL — `build_repo` not defined (`ImportError`).

- [ ] **Step 3: Write the minimal implementation**

Append to `tools/build_repo.py`:

```python
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(REPO_ROOT, "docs")

ADDONS = [
    {
        "id": "script.jellyfin.plex",
        "source_dir": REPO_ROOT,
        "includes": ["addon.xml", "default.py", "service.py", "icon.png", "lib", "resources"],
    },
    {
        "id": "repository.jellyfinplex",
        "source_dir": os.path.join(REPO_ROOT, "repository.jellyfinplex"),
        "includes": None,
    },
]


def build_repo(addons, docs_dir):
    for addon in addons:
        version = get_addon_version(addon["source_dir"])
        output_dir = os.path.join(docs_dir, addon["id"])
        build_addon_zip(
            addon["source_dir"], addon["includes"], addon["id"], version, output_dir
        )
        copy_icon(addon["source_dir"], output_dir)
    build_addons_xml([addon["source_dir"] for addon in addons], docs_dir)
    write_addons_xml_md5(os.path.join(docs_dir, "addons.xml"))


if __name__ == "__main__":
    build_repo(ADDONS, DOCS_DIR)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_build_repo.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest`
Expected: all tests pass (existing suite + new repo-builder tests).

- [ ] **Step 6: Generate the initial `docs/` output for real**

Run:

```bash
python tools/build_repo.py
```

This creates real `docs/script.jellyfin.plex/`, `docs/repository.jellyfinplex/`,
`docs/addons.xml`, and `docs/addons.xml.md5` from the actual repo contents. Confirm the zips were
created:

```bash
find docs -maxdepth 2 -type f
```

Expected output includes `docs/addons.xml`, `docs/addons.xml.md5`,
`docs/script.jellyfin.plex/script.jellyfin.plex-<current-version>.zip`,
`docs/script.jellyfin.plex/icon.png`,
`docs/repository.jellyfinplex/repository.jellyfinplex-1.0.0.zip`, and
`docs/repository.jellyfinplex/icon.png`.

- [ ] **Step 7: Sanity-check the generated `script.jellyfin.plex` zip contents**

```bash
python -c "import zipfile; print('\n'.join(sorted(zipfile.ZipFile('docs/script.jellyfin.plex/script.jellyfin.plex-0.2.53.zip').namelist())[:20]))"
```

(Adjust the version number in the filename to match the current `addon.xml` version.) Confirm the
listing starts with `script.jellyfin.plex/addon.xml`, `script.jellyfin.plex/default.py`,
`script.jellyfin.plex/lib/...` etc., and contains **no** `tests/`, `docs/`, `tools/`, or
`.github/` entries.

- [ ] **Step 8: Commit**

```bash
git add tools/build_repo.py tests/test_build_repo.py docs/addons.xml docs/addons.xml.md5 docs/script.jellyfin.plex docs/repository.jellyfinplex
git commit -m "Add build_repo() orchestration and generate initial docs/ repository output"
```

---

### Task 5: GitHub Actions workflow to rebuild the repo on release

**Files:**
- Create: `.github/workflows/build-repo.yml`

**Interfaces:**
- Consumes: `python tools/build_repo.py` (Task 4's CLI entry point) as the workflow's only
  build step.
- Produces: a CI job that keeps `docs/` in sync with `addon.xml` on every push to `master`.

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/build-repo.yml`:

```yaml
name: Build Kodi repository

on:
  push:
    branches: [master]
    paths:
      - "script.jellyfin.plex/addon.xml"
      - "addon.xml"
      - "repository.jellyfinplex/addon.xml"
      - "tools/build_repo.py"
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Build repository
        run: python tools/build_repo.py

      - name: Commit and push docs/ changes
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/
          if git diff --cached --quiet; then
            echo "No changes to docs/, skipping commit."
          else
            git commit -m "Rebuild Kodi repository [skip ci]"
            git push
          fi
```

Note: `addon.xml` is listed as a path filter because this repo's `script.jellyfin.plex` addon
files live at the repo root (there's no `script.jellyfin.plex/addon.xml` path — that entry is
harmless and future-proofs the filter if the addon is ever moved into its own subfolder). The
`[skip ci]` marker in the bot's commit message, combined with the path filter only matching
`addon.xml`/`build_repo.py` changes, prevents the bot's own `docs/`-only commits from
re-triggering this workflow.

- [ ] **Step 2: Validate the YAML syntax locally**

```bash
python -c "import yaml, sys; yaml.safe_load(open('.github/workflows/build-repo.yml'))" 2>/dev/null || python3 -c "
import json
import sys
try:
    import yaml
except ImportError:
    print('PyYAML not installed locally - will validate via GitHub Actions parse on push instead')
    sys.exit(0)
yaml.safe_load(open('.github/workflows/build-repo.yml'))
print('YAML OK')
"
```

Expected: either `YAML OK` or the fallback message — either way, no syntax error/traceback.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/build-repo.yml
git commit -m "Add CI workflow to rebuild the Kodi repository on release"
```

---

### Task 6: Documentation — install-via-repository instructions

**Files:**
- Modify: `README.md`
- Modify: `README.de.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing (prose only).
- Produces: user-facing install/update instructions; no code interface.

- [ ] **Step 1: Add an installation section to `README.md`**

`README.md` currently has no installation section at all (it goes straight from `## Screenshots`
to `## Status`). Insert a new `## Installation` section between them (i.e. right before the
`## Status` heading on line 35):

```markdown
## Installation

### Install via repository (recommended — enables auto-updates)

1. Download the repository addon zip:
   [`repository.jellyfinplex-1.0.0.zip`](https://drachenhort.github.io/jellyfin-kodi-plex/repository.jellyfinplex/repository.jellyfinplex-1.0.0.zip)
2. In Kodi: **Add-ons → Install from zip file**, select the downloaded file.
3. Then **Add-ons → Install from repository → Jellyfin (Plex-style) Repository →
   Program add-ons → Jellyfin (Plex-style)**, and install it from there.

From then on, Kodi checks this repository for new versions and can auto-update the addon like
any other, so you no longer need to manually reinstall a zip after every release.

### Install from a plain zip (no auto-updates)

Download the addon zip from a [GitHub Release](https://github.com/drachenhort/jellyfin-kodi-plex/releases)
and use **Add-ons → Install from zip file** in Kodi. You'll need to repeat this manually for every
future version.
```

- [ ] **Step 2: Mirror the same section into `README.de.md`**

`README.de.md` mirrors `README.md`'s structure section-for-section (per this project's standing
translation-sync convention). Insert the equivalent section at the same relative position (right
before its `## Status` heading):

```markdown
## Installation

### Installation über das Repository (empfohlen — ermöglicht automatische Updates)

1. Repository-Addon-Zip herunterladen:
   [`repository.jellyfinplex-1.0.0.zip`](https://drachenhort.github.io/jellyfin-kodi-plex/repository.jellyfinplex/repository.jellyfinplex-1.0.0.zip)
2. In Kodi: **Add-ons → Von ZIP-Datei installieren**, die heruntergeladene Datei auswählen.
3. Danach **Add-ons → Aus Repository installieren → Jellyfin (Plex-style) Repository →
   Programm-Add-ons → Jellyfin (Plex-style)** und von dort installieren.

Ab diesem Zeitpunkt prüft Kodi dieses Repository auf neue Versionen und kann das Addon wie jedes
andere automatisch aktualisieren — ein manuelles Neuinstallieren der ZIP-Datei nach jedem Release
ist damit nicht mehr nötig.

### Installation aus einer einfachen ZIP-Datei (keine automatischen Updates)

Die Addon-ZIP-Datei von einem [GitHub Release](https://github.com/drachenhort/jellyfin-kodi-plex/releases)
herunterladen und in Kodi **Add-ons → Von ZIP-Datei installieren** verwenden. Dieser Schritt muss
für jede zukünftige Version manuell wiederholt werden.
```

Verify the heading landed at the same relative position in both files:

```bash
grep -n "^##" README.md README.de.md
```

Expected: `## Installation` appears directly after `## Screenshots` and before `## Status` in
both files.

- [ ] **Step 3: Note the new automated step in `CLAUDE.md`'s release workflow section**

In `CLAUDE.md`, under the existing `## Release workflow` section, add one sentence after the
existing steps:

```markdown
Pushing a version bump to `master` also triggers `.github/workflows/build-repo.yml`, which
regenerates `docs/` (the Kodi repository served via GitHub Pages) — no extra manual step needed,
but check the Actions tab if a released version doesn't show up as a Kodi update within a few
minutes.
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest`
Expected: all tests pass (docs-only change, no test impact expected, but confirm nothing broke).

- [ ] **Step 5: Commit**

```bash
git add README.md README.de.md CLAUDE.md
git commit -m "Document installing the addon via the Kodi repository"
```

---

## After This Plan (manual, one-time, not part of the coding tasks)

- **Enable GitHub Pages:** repo Settings → Pages → source = `master` branch, `/docs` folder. This
  makes `docs/` publicly served at `https://drachenhort.github.io/jellyfin-kodi-plex/`. Confirm
  with the user before doing this (it's a repo-settings change, even though the repo is already
  public).
- **Verify end-to-end on the real Kodi test box:** install `repository.jellyfinplex` from the
  generated zip, confirm Kodi lists "Jellyfin (Plex-style)" as installable from the repository,
  then bump the addon version, push, wait for the Actions run + Pages republish, and confirm Kodi
  offers the update. This is real-Kodi verification per this project's conventions — pytest alone
  cannot confirm Kodi's update-check behavior.
