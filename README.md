# jellyfin-kodi-plex

A Kodi program addon (`script.jellyfin.plex`) that connects to a Jellyfin media server and
presents a custom, hub-based interface modelled on the Plex Web/App experience — rather than
Kodi's default skin listings.

Architecture is modelled on the open-source [Plex for Kodi](https://github.com/plexinc/plex-for-kodi)
addon: a Kodi *script* addon (not `plugin.video.*`) that opens its own `WindowXML`/`WindowXMLDialog`
windows to fully control the UI, independent of the active Kodi skin.

## Status

Milestone 1 (in progress): login (LAN autodiscovery, Quick Connect + password fallback) → home screen with
Continue Watching / Next Up / Recently Added hub rows → library poster-wall browsing, including
drill-down through TV (Series → Season → Episode) and Music (Artist → Album → Track) hierarchies,
and a Search screen → item detail page → playback with progress reported back to the server, and
a custom Plex-style seek/OSD dialog in place of Kodi's stock video controls. Multi-server support
is follow-up work.

The TV/Music drill-down works by fetching each item's direct children non-recursively
(`lib/windows/browse.py` is reused at every level: a library's top-level items, a series'
seasons, a season's episodes, an artist's albums, an album's tracks) and branching on the
clicked item's type (`lib/main.py`'s `CONTAINER_TYPES`) to decide whether to browse deeper or
open the detail/play screen. Music artist grouping relies on the library being organized as one
folder per artist — Jellyfin's virtual cross-folder artist aggregation (`/Artists`) isn't used.

The login screen autodetects Jellyfin servers on the LAN (`lib/jellyfin/discovery.py`) using the
UDP broadcast protocol inherited from Emby/MediaBrowser — found servers are offered as a pick-list
that fills in the server URL field, with manual entry still available as a fallback.

The custom OSD works by exploiting the fact that Kodi has no API to suppress its own default video
OSD from opening on a remote/keyboard press: `lib/player.py` polls `Window.IsActive(videoosd)` in a
background thread and shows `lib/windows/seekdialog.py`'s dialog on top of it the moment that
happens — the same trick the real Plex-for-Kodi addon uses.

## Development

```bash
pip install -r requirements-dev.txt   # pytest
pytest
```

`lib/jellyfin/*` is a pure-Python Jellyfin API client with no `xbmc*` imports, so it's testable
directly with pytest. `lib/windows/*` and `lib/player.py` are the only modules that touch
`xbmcgui`/`xbmc`, and require a real Kodi environment (or the stubs in `tests/conftest.py`) to run.

To try it in Kodi: copy or symlink this directory into
`~/.kodi/addons/script.jellyfin.plex/` and launch it from the Programs menu.
