# Configure Server via Kodi's Native Add-on Settings

## Goal

Let a user configure/manage their Jellyfin server(s) through Kodi's native "Configure" dialog
(Add-ons → Jellyfin (Plex-style) → Configure), not only via the addon's own in-app Home → Servers
screen.

## Current State

`resources/settings.xml` has one `server` category, but every setting in it
(`servers`, `active_server_id`, `device_id`, `hide_playlists`) is marked `hidden` — internal
storage only. Kodi's Configure dialog is currently empty from a user's perspective. Meanwhile
`lib/windows/servers.py` (`ServerListWindow`) + `lib/windows/login.py` (`LoginWindow`) already
provide a full add/switch/remove/Quick-Connect/password/LAN-discovery flow, reachable today only
via a "Servers" button on the Home screen (`lib/main.py`'s `_manage_servers`).

## Design

### 1. Two new visible settings (`resources/settings.xml`)

Both added to the existing `server` category/group, both `<level>0</level>` (Kodi's default
"Basic" settings level — the existing hidden settings use `<level>2</level>`, but that's
irrelevant while hidden; these new ones must be visible without the user raising Kodi's settings
level):

- `active_server_info` — `type="string"`, read-only (`<control type="edit" format="string"/>` +
  `<constraints><options>readonly</options></constraints>`, matching the existing sibling-of-
  `<control>` placement used by the `hidden` constraint on other settings in this file). Shows
  `"<name> (<server_url>)"` for the current active server, or an empty string if none.
- `manage_servers` — `type="action"`, `<control type="button" format="action">` with
  `<data>RunScript(script.jellyfin.plex,configure)</data>`. Clicking it launches the addon in a
  special mode (see below) instead of the normal Home flow.

New label/help strings in `resources/language/resource.language.en_gb/strings.po`:
`30010` "Active server", `30011` "Manage servers…", `30012` help text for the action button.

### 2. `default.py` dispatches on a `configure` argv

For `xbmc.python.script` addons, `RunScript(addonid, param1, ...)` passes the extra params as
`sys.argv[1:]`. `default.py` becomes:

```python
import sys
from lib import main

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "configure":
        main.run_configure()
    else:
        main.run()
```

Any other/missing argv falls through to the normal `main.run()` — safe default.

### 3. `lib/main.py` changes

- **`_set_active_server_id(server_id)`** becomes the single choke point for keeping
  `active_server_info` correct: after writing `active_server_id`, it looks up the matching entry
  in `_load_servers()` and writes `active_server_info` as `"{name} ({server_url})"`, or `""` if
  the id isn't found. Every existing call site (`_login`, `_manage_servers`'s "select" branch,
  `_migrate_legacy_settings`) gets this for free — no new call sites needed.
- **`_backfill_active_server_info()`** (new): one-time self-heal for installs upgrading from
  before this feature existed — if `active_server_info` is already set, no-op; otherwise, if
  there's an `active_server_id`, re-run `_set_active_server_id` on it to populate the label.
- **`run_configure()`** (new): `_migrate_legacy_settings()` → `_backfill_active_server_info()` →
  `_manage_servers()`, then returns (script exits back to Kodi/Configure). No Home loop involved.
- **`_manage_servers(client)` → `_manage_servers()`**: the `client` parameter is unused in the
  current implementation (dead parameter); dropped now because `run_configure()` has no client to
  give it and passing a dummy value would be worse than removing the parameter. The one existing
  call site in `_home_loop` (`_manage_servers(client)` → `_manage_servers()`) is updated to match.

### Data Flow

User opens Configure → sees the active server at a glance via the read-only label → clicks
"Manage servers…" → Kodi runs the script with `configure` → `_manage_servers()` opens the same
`ServerListWindow`/`LoginWindow` UI as Home's "Servers" button (add/switch/remove, Quick Connect,
password, LAN discovery) → user backs out → script exits → Configure dialog reappears with the
label reflecting whatever changed, next time it's opened.

This also means Configure works as a legitimate **first-time setup path**: with zero servers
saved, `_manage_servers()` still opens `ServerListWindow` with an empty list and a working "Add
server" button (confirmed in `lib/windows/servers.py`: the add button is a separate control from
the list, and `onInit` tolerates an empty `servers` list).

## Testing

New `tests/test_main.py`, covering only the new pure logic (this file's orchestration —
`run()`, `_home_loop`, `_login`, `_manage_servers`, `run_configure` — has no existing unit tests
and stays manually-verified, consistent with today's convention):

- `_set_active_server_id`: writes `active_server_info` as `"{name} ({server_url})"` when the id
  matches a saved server; writes `""` when it doesn't.
- `_backfill_active_server_info`: no-op when `active_server_info` is already set; populates it
  from the existing `active_server_id` when empty; no-op (stays empty) when there's no active
  server id either.

## Out of Scope (YAGNI)

- No direct editable server-URL/credential text fields in the native settings dialog (rejected
  design alternative — can't support Quick Connect's async polling, duplicates existing UX).
- No changes to `ServerListWindow`/`LoginWindow` themselves — reused as-is.
- No German (or other) translation of the new `strings.po` entries — this repo has only
  `resource.language.en_gb` today; unrelated to the README.de.md translation convention, which is
  documentation, not Kodi's in-app strings.
