"""Generic container browse window: a poster-wall grid of one item's direct
children. Used at every level of the TV and Music hierarchies (a library's
top-level items, a series' seasons, a season's episodes, a folder-organized
music library's artists, an artist's albums, an album's tracks) as well as
flat libraries (Movies) with no intermediate levels.

M1 loads a single page of up to MAX_ITEMS items up front (sorted by name)
rather than implementing incremental scroll-paging — a reasonable place to
cut scope for the first vertical slice; true infinite scroll is M2 work.

self.result on close: {"action": "open", "item_id": ..., "item_type": ...,
"item_name": ...} or {"action": "play_queue", "item_ids": [...], "item_type":
"Audio"} (Play All/Shuffle, album view only) or None (back).
"""

import random
import threading
import time

import xbmc
import xbmcgui

from lib.jellyfin import images, library
from lib.windows.kodigui import LOG_PREFIX, ControlledWindow, list_item

CTRL_TITLE = 300
CTRL_GRID = 301
CTRL_PLAY_ALL = 302
CTRL_SHUFFLE = 303
CTRL_EPISODE_LIST = 304
CTRL_LOADING = 305

MAX_ITEMS = 200

# Only an album's own screen offers Play All/Shuffle - browsing an Artist
# still just drills down into that artist's Albums.
QUEUEABLE_PARENT_TYPES = {"MusicAlbum"}

# A season's episodes get the "ls -l"-style detail list (CTRL_EPISODE_LIST)
# instead of the poster grid - one row per episode is a lot more scannable
# than a wall of near-identical landscape thumbnails.
LISTED_PARENT_TYPES = {"Season"}


class BrowseWindow(ControlledWindow):
    xmlFile = "script-jellyfin-browse.xml"

    def setup(self, client=None, parent_id=None, title="", parent_item_type=None, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.parent_id = parent_id
        self.title = title
        self.parent_item_type = parent_item_type
        self.is_episode_list = parent_item_type in LISTED_PARENT_TYPES
        self.items = []

    def onInit(self):
        # Title shows immediately (cheap, no network); the actual listing
        # fetch runs on a background thread (_load()) so a slow response
        # doesn't freeze the whole GUI thread - each step below checks
        # closed_event first in case the user already backed out.
        self.getControl(CTRL_TITLE).setLabel(self.title)
        self.getControl(CTRL_PLAY_ALL).setVisible(False)
        self.getControl(CTRL_SHUFFLE).setVisible(False)
        self.getControl(CTRL_LOADING).setLabel(f"Loading {self.title}…")
        active_control = CTRL_EPISODE_LIST if self.is_episode_list else CTRL_GRID
        self.getControl(CTRL_GRID).setVisible(not self.is_episode_list)
        self.getControl(CTRL_EPISODE_LIST).setVisible(self.is_episode_list)
        self.setFocusId(active_control)
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        started = time.time()
        try:
            response = library.get_items(
                self.client, parent_id=self.parent_id, start_index=0, limit=MAX_ITEMS,
                recursive=False,
            )
        except Exception as exc:  # noqa: BLE001 - a server/network failure shouldn't crash the addon
            xbmc.log(
                f"{LOG_PREFIX} Browse: fetching children of {self.parent_id!r} ({self.title!r}) "
                f"failed after {time.time() - started:.1f}s: {exc}",
                xbmc.LOGWARNING,
            )
            if self.closed_event.is_set():
                return
            xbmcgui.Dialog().notification("Jellyfin", f"Couldn't load {self.title}: {exc}")
            self.result = None
            self.close()
            return
        self.items = response.get("Items", [])
        xbmc.log(
            f"{LOG_PREFIX} Browse: fetched {len(self.items)} children of {self.parent_id!r} "
            f"({self.title!r}) in {time.time() - started:.1f}s",
            xbmc.LOGINFO,
        )
        if self.closed_event.is_set():
            return
        self.getControl(CTRL_LOADING).setVisible(False)

        control = self.getControl(CTRL_EPISODE_LIST if self.is_episode_list else CTRL_GRID)
        control.reset()
        list_items = []
        for item in self.items:
            primary = images.primary_image_url(self.client, item)
            backdrop = images.backdrop_image_url(self.client, item)
            list_items.append(list_item(item, primary, backdrop))
        control.addItems(list_items)

        show_queue_controls = self.parent_item_type in QUEUEABLE_PARENT_TYPES and self._track_ids()
        self.getControl(CTRL_PLAY_ALL).setVisible(bool(show_queue_controls))
        self.getControl(CTRL_SHUFFLE).setVisible(bool(show_queue_controls))

    def _track_ids(self):
        return [item["Id"] for item in self.items if item.get("Type") == "Audio"]

    def handle_click(self, control_id):
        if control_id in (CTRL_GRID, CTRL_EPISODE_LIST):
            self._open_selected(control_id)
        elif control_id == CTRL_PLAY_ALL:
            self._play_queue(shuffle=False)
        elif control_id == CTRL_SHUFFLE:
            self._play_queue(shuffle=True)

    def _open_selected(self, control_id):
        selected = self.getControl(control_id).getSelectedItem()
        if not selected:
            return
        self.result = {
            "action": "open",
            "item_id": selected.getProperty("jellyfin_id"),
            "item_type": selected.getProperty("jellyfin_type"),
            "item_name": selected.getLabel(),
        }
        self.close()

    def _play_queue(self, shuffle):
        track_ids = self._track_ids()
        if not track_ids:
            return
        if shuffle:
            track_ids = random.sample(track_ids, len(track_ids))
        self.result = {"action": "play_queue", "item_ids": track_ids, "item_type": "Audio"}
        self.close()
