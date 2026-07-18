# Configure Server via Kodi's Native Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user manage their Jellyfin server(s) from Kodi's native "Configure" dialog on the
addon, by adding a read-only active-server label and a "Manage servers…" action button that
launches the addon's existing server-management UI directly (bypassing Home).

**Architecture:** Two new visible settings in `resources/settings.xml`; the action button runs
`RunScript(script.jellyfin.plex,configure)`, which `default.py` detects via `sys.argv` and routes
to a new `lib/main.py:run_configure()` that reuses the existing `ServerListWindow`/`LoginWindow`
flow. `_set_active_server_id()` becomes the single place that keeps the new read-only label
current, so every existing caller (login, switch, migration) updates it for free.

**Tech Stack:** Existing project conventions only — pure-Python logic in `lib/main.py` tested via
`tests/kodi_stubs`, no new dependencies.

## Global Constraints

- `resources/settings.xml`'s new settings must be `<level>0</level>` — Kodi's default "Basic"
  settings level — or they won't show up without the user raising Kodi's settings level.
- The `<constraints>` element is a sibling of `<control>` under `<setting>`, not nested inside
  `<control>` — match the existing file's structure exactly (see the `hidden` settings already
  there).
- `RunScript(script.jellyfin.plex,configure)` must match the addon's actual id
  (`script.jellyfin.plex`, per `addon.xml`) — a typo here silently breaks the button with no error
  surfaced to the user.
- `lib/main.py`'s orchestration functions (`run`, `run_configure`, `_home_loop`, `_login`,
  `_manage_servers`) have no existing unit tests and are not gaining any in this plan — only the
  new pure-logic pieces (`_set_active_server_id`'s dual-write, `_backfill_active_server_info`) get
  tests, consistent with this file's existing testing boundary (`lib/windows/*` and
  `lib/jellyfin/*` are unit-tested; `lib/main.py`'s wiring is manually verified in real Kodi per
  `CLAUDE.md`).
- Run `pytest` before every commit that touches Python code.

---

### Task 1: `lib/main.py` — active-server label + configure entry point

**Files:**
- Modify: `lib/main.py`
- Test: `tests/test_main.py` (new file)

**Interfaces:**
- Consumes: `servers.find`, `servers.serialize`/`deserialize` (existing, `lib/servers.py`).
- Produces:
  - `_set_active_server_id(server_id)` — now also writes an `active_server_info` setting as
    `"{name} ({server_url})"` for the matching server, or `""` if not found. Same signature as
    today; every existing caller is unaffected by this change other than the new side effect.
  - `_backfill_active_server_info()` — new, no args, no return value.
  - `_manage_servers()` — same behavior as today's `_manage_servers(client)`, `client` parameter
    removed (it was unused in the current implementation).
  - `run_configure()` — new, no args. Consumed by Task 3's `default.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main.py`:

```python
"""Tests for lib/main.py's active-server-label bookkeeping.

Only the new pure-logic pieces get unit tests here (matching this module's
existing convention: run()/_home_loop/_login/_manage_servers are orchestration
glue verified manually in real Kodi, not unit-tested). ADDON is a
module-level singleton in lib.main, so each test gets its own fresh stub via
monkeypatch to avoid leaking setSetting() calls between tests (same pattern
as tests/test_home.py).
"""

import xbmcaddon

import lib.main as main_mod
from lib import servers


def _make_addon(monkeypatch, server_list=None, active_server_id=""):
    addon = xbmcaddon.Addon()
    if server_list is not None:
        addon.setSetting("servers", servers.serialize(server_list))
    if active_server_id:
        addon.setSetting("active_server_id", active_server_id)
    monkeypatch.setattr(main_mod, "ADDON", addon)
    return addon


TOWER = {
    "id": "abc",
    "name": "Tower",
    "server_url": "http://192.168.1.5:8096",
    "access_token": "tok",
    "user_id": "uid",
}


def test_set_active_server_id_writes_info_for_known_server(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[TOWER])

    main_mod._set_active_server_id("abc")

    assert addon.getSetting("active_server_id") == "abc"
    assert addon.getSetting("active_server_info") == "Tower (http://192.168.1.5:8096)"


def test_set_active_server_id_writes_empty_info_for_unknown_server(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[])

    main_mod._set_active_server_id("does-not-exist")

    assert addon.getSetting("active_server_id") == "does-not-exist"
    assert addon.getSetting("active_server_info") == ""


def test_backfill_active_server_info_noop_when_already_set(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[TOWER], active_server_id="abc")
    addon.setSetting("active_server_info", "Custom (unchanged)")

    main_mod._backfill_active_server_info()

    assert addon.getSetting("active_server_info") == "Custom (unchanged)"


def test_backfill_active_server_info_populates_from_active_id(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[TOWER], active_server_id="abc")

    main_mod._backfill_active_server_info()

    assert addon.getSetting("active_server_info") == "Tower (http://192.168.1.5:8096)"


def test_backfill_active_server_info_noop_when_no_active_server(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[])

    main_mod._backfill_active_server_info()

    assert addon.getSetting("active_server_info") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v`
Expected: FAIL — `_backfill_active_server_info` doesn't exist yet (`AttributeError`), and the two
`_set_active_server_id` tests fail on the missing `active_server_info` assertion (empty string
mismatch, since that setting is never written today).

- [ ] **Step 3: Implement the changes in `lib/main.py`**

Replace the existing `_set_active_server_id` (currently `lib/main.py:54-55`):

```python
def _set_active_server_id(server_id):
    ADDON.setSetting("active_server_id", server_id)
    server = servers.find(_load_servers(), server_id)
    info = "{} ({})".format(server["name"], server["server_url"]) if server else ""
    ADDON.setSetting("active_server_info", info)


def _backfill_active_server_info():
    """One-time self-heal for installs updated from before active_server_info
    existed: if a server is already active but its info label was never
    written, populate it now."""
    if ADDON.getSetting("active_server_info"):
        return
    active_id = _get_active_server_id()
    if active_id:
        _set_active_server_id(active_id)
```

Change `_manage_servers(client)` (currently `lib/main.py:133-160`) to drop the unused parameter —
only the `def` line and docstring change, the body is identical:

```python
def _manage_servers():
    """Loops the server-management screen, letting the user add/remove/
    switch saved servers. Returns a new client to switch to, or None if
    there's nothing to resume. Used both by Home's "Servers" action and by
    the standalone Configure entry point (run_configure)."""
    while True:
        server_list = _load_servers()
        active_id = _get_active_server_id()
        result = ServerListWindow.open(
            ADDON_PATH, servers=server_list, active_id=active_id
        )
        if not result:
            return None
        if result["action"] == "add":
            new_client = _login()
            if new_client is None:
                continue
            return new_client
        elif result["action"] == "remove":
            _save_servers(servers.remove(server_list, result["server_id"]))
            continue
        elif result["action"] == "select":
            if result["server_id"] == active_id:
                return None
            server = servers.find(server_list, result["server_id"])
            if not server:
                continue
            _set_active_server_id(server["id"])
            return _client_from_server(server)
```

Update its one call site in `_home_loop` (currently `lib/main.py:233-236`):

```python
        elif result["action"] == "servers":
            new_client = _manage_servers()
            if new_client is not None:
                return new_client
```

Add `run_configure()` after `run()` at the end of the file:

```python
def run_configure():
    """Entry point for Kodi's native "Manage servers…" settings action
    (RunScript(script.jellyfin.plex,configure)). Skips Home entirely."""
    _migrate_legacy_settings()
    _backfill_active_server_info()
    _manage_servers()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest`
Expected: all tests pass (no regressions from the `_manage_servers` signature change — its only
caller, `_home_loop`, was updated in the same step).

- [ ] **Step 6: Commit**

```bash
git add lib/main.py tests/test_main.py
git commit -m "Keep an active-server label current and add a configure entry point"
```

---

### Task 2: `resources/settings.xml` — visible settings for the Configure dialog

**Files:**
- Modify: `resources/settings.xml`
- Modify: `resources/language/resource.language.en_gb/strings.po`
- Test: `tests/test_settings_xml.py` (new file)

**Interfaces:**
- Consumes: nothing from Task 1 (this task only adds XML/strings; the `RunScript` target and the
  `active_server_info` setting id are the contract with Task 1's Python code).
- Produces: the `active_server_info` and `manage_servers` settings, consumed at runtime by Kodi's
  Configure dialog and by Task 1's `_set_active_server_id`/`_backfill_active_server_info` (which
  write/read the `active_server_info` setting id — already implemented in Task 1, this task just
  makes it visible).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_xml.py`:

```python
"""Validates the new visible Configure-dialog settings are wired correctly.
XML structure only - this doesn't (and can't, without real Kodi) verify the
settings dialog actually renders as expected; see CLAUDE.md's Verification
section for the real-Kodi check this still needs.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_XML = REPO_ROOT / "resources" / "settings.xml"


def _get_setting(root, setting_id):
    return root.find(".//setting[@id='{}']".format(setting_id))


def test_active_server_info_is_visible_and_readonly():
    root = ET.parse(SETTINGS_XML).getroot()
    setting = _get_setting(root, "active_server_info")
    assert setting is not None
    assert setting.find("level").text == "0"

    constraints = setting.find("constraints")
    assert constraints is not None
    options = constraints.find("options")
    assert options is not None
    assert options.text == "readonly"


def test_manage_servers_action_runs_configure_script():
    root = ET.parse(SETTINGS_XML).getroot()
    setting = _get_setting(root, "manage_servers")
    assert setting is not None
    assert setting.attrib["type"] == "action"
    assert setting.find("level").text == "0"

    data = setting.find("control/data")
    assert data is not None
    assert data.text == "RunScript(script.jellyfin.plex,configure)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings_xml.py -v`
Expected: FAIL — both settings don't exist yet (`AttributeError: 'NoneType' object has no
attribute 'find'` or similar on the `None` result of `_get_setting`).

- [ ] **Step 3: Add the settings**

In `resources/settings.xml`, inside the existing `<group id="1">` (after the `hide_playlists`
setting, before `</group>`), add:

```xml
        <setting id="active_server_info" type="string" label="30010" help="">
          <level>0</level>
          <default></default>
          <control type="edit" format="string"/>
          <constraints>
            <options>readonly</options>
          </constraints>
        </setting>
        <setting id="manage_servers" type="action" label="30011" help="30012">
          <level>0</level>
          <control type="button" format="action">
            <data>RunScript(script.jellyfin.plex,configure)</data>
          </control>
        </setting>
```

In `resources/language/resource.language.en_gb/strings.po`, after the existing `#30006` entry,
add:

```
msgctxt "#30010"
msgid "Active server"
msgstr ""

msgctxt "#30011"
msgid "Manage servers…"
msgstr ""

msgctxt "#30012"
msgid "Add, switch, or remove saved Jellyfin servers, or log in for the first time."
msgstr ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings_xml.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add resources/settings.xml resources/language/resource.language.en_gb/strings.po tests/test_settings_xml.py
git commit -m "Add visible active-server label and manage-servers action setting"
```

---

### Task 3: `default.py` — dispatch to the configure entry point

**Files:**
- Modify: `default.py`

**Interfaces:**
- Consumes: `main.run_configure()` (Task 1) and the `manage_servers` setting's
  `RunScript(script.jellyfin.plex,configure)` (Task 2).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Update `default.py`**

Replace the full contents of `default.py`:

```python
import sys

from lib import main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "configure":
        main.run_configure()
    else:
        main.run()
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest`
Expected: all tests pass (this file has no unit tests today — it's a 5-line entry point guarded
by `if __name__ == "__main__":`, consistent with it never having had tests before this change).

- [ ] **Step 3: Commit**

```bash
git add default.py
git commit -m "Dispatch to the configure entry point via RunScript argv"
```

---

## After This Plan (manual verification, not part of the coding tasks)

Per `CLAUDE.md`'s Verification section, confirm on the real Kodi test box:
- Add-ons → Jellyfin (Plex-style) → Configure shows "Active server" (populated, not blank) and a
  "Manage servers…" button.
- Clicking "Manage servers…" opens the existing add/switch/remove/Quick-Connect/discovery screen
  directly (not Home), and backing out returns cleanly to the Configure dialog.
- On an install with zero saved servers, Configure → "Manage servers…" still works as a first-time
  setup path (empty list, working "Add server" button).
- After adding/switching a server via Configure, reopening Configure shows the updated "Active
  server" label.
