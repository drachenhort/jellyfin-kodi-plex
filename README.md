# jellyfin-kodi-plex

*[Deutsche Version](README.de.md)*

A Kodi program addon (`script.jellyfin.plex`) that connects to a Jellyfin media server and
presents a custom, hub-based interface modelled on the Plex Web/App experience — rather than
Kodi's default skin listings.

Architecture is modelled on the open-source [Plex for Kodi](https://github.com/plexinc/plex-for-kodi)
addon: a Kodi *script* addon (not `plugin.video.*`) that opens its own `WindowXML`/`WindowXMLDialog`
windows to fully control the UI, independent of the active Kodi skin.

## Screenshots

![Home screen with library row, Recently Added Movies, and Recently Added TV](screenshots/home-screen.png)

The Home screen's hub rows: a watched checkmark badge on already-seen movies, and an
unwatched-episode-count badge (capped at "99+") on TV shows with episodes left to watch.

![TV library grid with a synopsis pane for the focused show](screenshots/tv-library-synopsis.png)

Browsing the TV library: the synopsis pane below the grid tracks whichever poster has focus.

![Seasons of a series with a season's synopsis shown](screenshots/tv-seasons-synopsis-1.png)
![A different season of the same series, synopsis updated accordingly](screenshots/tv-seasons-synopsis-2.png)

The same synopsis pane one level deeper, browsing a series' seasons — it updates instantly as
focus moves between seasons.

![A season's episodes listed ls -l style with code, title, rating, duration, and watched state](screenshots/tv-episode-list.png)

A season's episodes get an `ls -l`-style detail list instead of a poster grid: episode code,
title, rating, duration, and watched state in aligned columns, plus the same synopsis pane below.

![Search screen with a query box, Movies/TV Shows/Music filter toggles, and a Home button](screenshots/search-empty.png)

Search: results-as-you-type, three category filter toggles, and an explicit Home button since
Back can get eaten by Kodi's on-screen keyboard closing itself instead of reaching the window.

![Search results for "Supernatural" grouped into a TV Shows row and a Music row](screenshots/search-supernatural-grouped.png)

Results are grouped one row per category instead of a single flat grid — searching "Supernatural"
here returns the show and its episodes under TV Shows, and several unrelated albums/artists
sharing the word under Music, each clearly separated instead of one undifferentiated wall of
posters.

## Installation

### Install via repository (recommended — enables auto-updates)

1. Download the repository addon zip:
   [`repository.jellyfinplex-1.0.0.zip`](https://drachenhort.github.io/jellyfin-kodi-plex/repository.jellyfinplex/repository.jellyfinplex-1.0.0.zip)
2. In Kodi: **Add-ons → Install from zip file**, select the downloaded file.
3. Then **Add-ons → Install from repository → Jellyfin (Plex-style) Repository →
   Video add-ons → Jellyfin (Plex-style)**, and install it from there.

From then on, Kodi checks this repository for new versions and can auto-update the addon like
any other, so you no longer need to manually reinstall a zip after every release.

### Install from a plain zip (no auto-updates)

Download the addon zip from a [GitHub Release](https://github.com/drachenhort/jellyfin-kodi-plex/releases)
and use **Add-ons → Install from zip file** in Kodi. You'll need to repeat this manually for every
future version.

## Status

Milestone 1 (complete): login (LAN autodiscovery, Quick Connect + password fallback) → home screen with
Continue Watching / Next Up / Recently Added Movies / Recently Added TV / Recently Added Music hub
rows → library poster-wall browsing, including drill-down through TV (Series → Season → Episode)
and Music (Artist → Album → Track) hierarchies, and a Search screen → item detail page → playback
(video and audio, using Kodi's own native OSD/controls) with progress reported back to the server,
and a Servers screen for saving logins to multiple Jellyfin servers and switching between them. An
album's own screen adds Play All/Shuffle buttons to queue its tracks back-to-back, advancing to the
next track only when the current one finishes naturally rather than being stopped early. When a TV
episode finishes playing to completion, an "Up Next" prompt offers the following episode in the
same season with a 30-second auto-play countdown (`lib/windows/next_episode.py`), chaining through
the rest of the season for as long as each one keeps playing to completion. In an episode's closing
~2.5 minutes, a small non-modal "Play Next Episode" overlay (`lib/windows/next_episode_overlay.py`)
also appears in the bottom-right corner, letting the outro/credits be skipped straight into the
next episode without waiting for natural end.

Milestone 2 (in progress): expanding the addon's Settings into real user-facing configuration —
per-hub-row Home show/hide toggles, hide-watched toggles for Recently Added rows, a configurable
Recently Added item limit, default library sort order, server request timeout, max streaming
bitrate, the "Play Next Episode" overlay's lead time (Playback settings), and a Settings button on
the Home screen next to Servers/Search.

The TV/Music drill-down works by fetching each item's direct children non-recursively
(`lib/windows/browse.py` is reused at every level: a library's top-level items, a series'
seasons, a season's episodes, an artist's albums, an album's tracks) and branching on the
clicked item's type (`lib/main.py`'s `CONTAINER_TYPES`) to decide whether to browse deeper or
open the detail/play screen. Music artist grouping relies on the library being organized as one
folder per artist — Jellyfin's virtual cross-folder artist aggregation (`/Artists`) isn't used.
The browse screen also shows a synopsis pane for whichever item currently has focus (most useful
browsing a series' seasons), and marks already-watched movies/episodes with a checkmark badge and
partially-watched shows with an unwatched-episode-count badge.

The login screen autodetects Jellyfin servers on the LAN (`lib/jellyfin/discovery.py`) using the
UDP broadcast protocol inherited from Emby/MediaBrowser — found servers are offered as a pick-list
that fills in the server URL field, with manual entry still available as a fallback.

Multi-server support (`lib/servers.py`) stores saved logins as a list of `{name, server_url,
access_token, user_id}` dicts, serialized into a single hidden addon setting rather than one
setting per field — `lib/main.py` owns reading/writing that setting and matches re-logins to an
already-saved server URL to update its entry in place instead of duplicating it. The Servers
button on Home (`lib/windows/servers.py`) opens a picker to switch the active server, add another
via the same login flow, or remove a saved one (the currently active server can't be removed —
switch away from it first). An existing single-server install is migrated into this list
automatically the first time it runs after updating, so it doesn't get logged out.

If the active server can't be reached on startup (down, unreachable, returning a 5xx error),
`lib/main.py` automatically tries the other saved servers in order and switches to the first one
that responds, with a notification explaining which server failed and why, and which one it
switched to. If none of the saved servers are reachable, a notification reports that instead and
the normal login screen opens.

## Development

```bash
pip install -r requirements-dev.txt   # pytest
pytest
```

`lib/jellyfin/*` is a pure-Python Jellyfin API client with no `xbmc*` imports, so it's testable
directly with pytest. `lib/windows/*` and `lib/player.py` are the only modules that touch
`xbmcgui`/`xbmc`; `tests/kodi_stubs/` provides minimal stand-ins for those modules (registered into
`sys.modules` by `tests/conftest.py`), so this layer runs under plain pytest too — no real Kodi
environment needed to exercise it.

To try it in Kodi: copy or symlink this directory into
`~/.kodi/addons/script.jellyfin.plex/` and launch it from the Programs menu.
