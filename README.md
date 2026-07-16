# jellyfin-kodi-plex

A Kodi program addon (`script.jellyfin.plex`) that connects to a Jellyfin media server and
presents a custom, hub-based interface modelled on the Plex Web/App experience — rather than
Kodi's default skin listings.

Architecture is modelled on the open-source [Plex for Kodi](https://github.com/plexinc/plex-for-kodi)
addon: a Kodi *script* addon (not `plugin.video.*`) that opens its own `WindowXML`/`WindowXMLDialog`
windows to fully control the UI, independent of the active Kodi skin.

## Status

Milestone 1 (in progress): login (Quick Connect + password fallback) → home screen with
Continue Watching / Next Up / Recently Added hub rows → library poster-wall browsing → item
detail page → playback with progress reported back to the server, and a custom Plex-style seek/OSD
dialog in place of Kodi's stock video controls. TV/music navigation, search, and multi-server
support are follow-up work.

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
