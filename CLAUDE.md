# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`script.jellyfin.plex` — a Kodi *program* addon (not `plugin.video.*`) that connects to a Jellyfin
media server and renders its own Plex-style `WindowXML`/`WindowXMLDialog` UI, independent of the
active Kodi skin. Architecture is modelled on the open-source
[Plex for Kodi](https://github.com/plexinc/plex-for-kodi) addon.

Milestone 1 (complete): login (LAN autodiscovery, Quick Connect + password fallback) → home
screen with hub rows (Continue Watching / Next Up / Recently Added) → library poster-wall browsing
with drill-down through TV (Series → Season → Episode) and Music (Artist → Album → Track) → Search
→ item detail → playback via Kodi's native OSD, with progress reported back to the server → a
Servers screen for saving/switching between multiple Jellyfin server logins.

Milestone 2 (in progress): expanding `resources/settings.xml` from purely-internal hidden state
(saved servers, device id) into real user-facing configuration — per-hub-row Home show/hide
toggles, hide-watched toggles for Recently Added rows, default library sort order, server request
timeout, max streaming bitrate, and a Settings button on the Home screen. `service.py` is unrelated
to M2 and remains a no-op placeholder reserved for a possible future milestone (e.g. background
auto-discovery or session keep-alive).

## Commands

```bash
pip install -r requirements-dev.txt   # installs pytest, requests
pytest                                 # run the full suite
pytest tests/test_browse.py            # run one test file
pytest tests/test_browse.py::test_name # run a single test
```

There is no lint/build step configured. To try the addon in Kodi itself: copy or symlink this
directory into `~/.kodi/addons/script.jellyfin.plex/` and launch it from the Programs menu.

## Release workflow

After implementing a change: run `pytest` and confirm it passes, commit, push, bump the version in
`addon.xml`, and note the change in the changelog/news if one exists. Verify each git step (status,
push result) rather than assuming success. Don't consider a feature done until it's been verified
against a real Jellyfin server and/or real Kodi install (see Verification below) — passing tests
alone only proves the pure-Python layer, not the actual UI behavior in Kodi. Pushing a version bump to `master` also triggers `.github/workflows/build-repo.yml`, which
regenerates `docs/` (the Kodi repository served via GitHub Pages) — no extra manual step needed,
but check the Actions tab if a released version doesn't show up as a Kodi update within a few
minutes.

## Verification

This addon's real UI behavior can only be confirmed by running it in actual Kodi, not by pytest
alone (`tests/kodi_stubs/` stand in for `xbmcgui`/`xbmc` but don't render anything). When manual
verification is needed:

- Never launch or drive Kodi on the user's own dev machine display — that's their live desktop, not
  a headless/test environment. Ask before touching it.
- Prefer the dedicated real Kodi/LibreELEC test box and the real Jellyfin test server for end-to-end
  checks (ask the user for current connection details if unknown — don't guess a device or IP).
- When pushing an updated addon build to a real Kodi box for reinstall, use a version-suffixed zip
  filename (or delete the old one first) rather than overwriting the same filename in place — Kodi's
  zip VFS can fail to install over a stale cached path.
- A verification pass should confirm the screen actually rendered as expected (e.g. via a real
  screenshot or JSON-RPC state check), not just that the script didn't crash on launch.

## Architecture

**Layering and testability.** `lib/jellyfin/*` is a pure-Python Jellyfin API client with no
`xbmc*` imports, so it's tested directly with pytest. `lib/windows/*` and `lib/player.py` are the
only modules that touch `xbmcgui`/`xbmc`; `tests/kodi_stubs/` provides minimal stand-ins for those
modules, registered into `sys.modules` by `tests/conftest.py` *before* any test file imports a
`lib.windows.*` module — so this layer also runs under plain pytest with no real Kodi environment.
Keep new Jellyfin API logic in `lib/jellyfin/` free of `xbmc*` imports to preserve this.

**Navigation model (`lib/main.py`).** Each window's `open()` blocks via `doModal()` until it
closes, so the screen "stack" is just nested loops/function calls: showing a screen again after a
deeper screen closes with no result is Back (loop again); moving to a deeper screen is a nested
call. Only backing out of the root Home loop ends the script. Container item types that get
browsed deeper rather than played are listed in `lib/main.py`'s `CONTAINER_TYPES` (`Series`,
`Season`, `MusicArtist`, `MusicAlbum`, `BoxSet`, `Folder`).

**Drill-down reuses one window.** `lib/windows/browse.py` handles every non-recursive
child-listing level — a library's top-level items, a series' seasons, a season's episodes, an
artist's albums, an album's tracks — branching only on the clicked item's type. Music artist
grouping assumes the library is organized one folder per artist; Jellyfin's virtual cross-folder
`/Artists` aggregation is not used.

**Multi-server support (`lib/servers.py` + `lib/main.py`).** Saved logins are a list of `{name,
server_url, access_token, user_id}` dicts, serialized into a single hidden addon setting (not one
setting per field). `lib/main.py` owns reading/writing that setting and matches a re-login to an
already-saved `server_url` to update the entry in place rather than duplicating it. An existing
single-server install is migrated into this list automatically on first run after update
(`_migrate_legacy_settings` in `lib/main.py`), so it doesn't get logged out. The currently active
server can't be removed from the Servers screen (`lib/windows/servers.py`) — switch away first.

**Discovery.** `lib/jellyfin/discovery.py` finds Jellyfin servers on the LAN via the UDP broadcast
protocol inherited from Emby/MediaBrowser; results are offered as a pick-list on the login screen,
with manual URL entry as a fallback.

**Client version.** `lib/jellyfin/client.py`'s `CLIENT_VERSION` constant is only a fallback — real
callers (`lib/main.py`) pass the addon's actual version from `addon.xml` via
`ADDON.getAddonInfo("version")`, so it can't drift from what Jellyfin displays for the session.

**Background threading.** Library/recently-added queries in `lib/windows/*.py` run on a background
thread rather than Kodi's GUI thread, since a large real library (e.g. thousands of music tracks)
can be slow to enumerate — this is why `JellyfinClient`'s request timeout is generous (60s): it no
longer risks freezing the UI.

**`service.py`** is currently a no-op placeholder, unrelated to M2's Settings work — a future
milestone may use it for auto-discovery or session keep-alive. M1 playback-progress reporting runs
inline in `lib/player.py` while the script addon is in the foreground.

