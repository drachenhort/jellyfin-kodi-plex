"""Generic container browse window: a poster-wall grid of one item's direct
children. Used at every level of the TV and Music hierarchies (a library's
top-level items, a series' seasons, a season's episodes, a folder-organized
music library's artists, an artist's albums, an album's tracks) as well as
flat libraries (Movies) with no intermediate levels.

Loads via library.iter_items_paged() (StartIndex/Limit paging, sorted by
name) rather than one single capped fetch, appending each page to the grid
as it arrives - this is what lets a library too large for one request (the
motivating case: a ~100k-track Music library that made a single big-limit
fetch time out server-side) still browse successfully instead of failing
outright. See lib/jellyfin/library.py's iter_items_paged docstring.

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
        control = self.getControl(CTRL_EPISODE_LIST if self.is_episode_list else CTRL_GRID)
        control.reset()
        self.items = []
        error = None
        try:
            for page in library.iter_items_paged(
                self.client, parent_id=self.parent_id, recursive=False,
                fields=library.LISTING_ITEM_FIELDS,
            ):
                if self.closed_event.is_set():
                    return
                self.items.extend(page)
                control.addItems([
                    list_item(item, images.primary_image_url(self.client, item),
                              images.backdrop_image_url(self.client, item))
                    for item in page
                ])
                # Update the count after every page so a slow/large fetch
                # (still going after the first page or two) visibly keeps
                # counting up instead of leaving the user staring at a
                # static "Loading…" with no sign anything is happening.
                self.getControl(CTRL_LOADING).setLabel(
                    f"Loading {self.title}… ({len(self.items)} items)"
                )
        except Exception as exc:  # noqa: BLE001 - a server/network failure shouldn't crash the addon
            error = exc

        if self.closed_event.is_set():
            return
        elapsed = time.time() - started

        if error and not self.items:
            # Nothing loaded at all (e.g. the very first page failed) - same
            # dead end as before pagination: notify and back out.
            xbmc.log(
                f"{LOG_PREFIX} Browse: fetching children of {self.parent_id!r} ({self.title!r}) "
                f"failed after {elapsed:.1f}s: {error}",
                xbmc.LOGWARNING,
            )
            self.getControl(CTRL_LOADING).setVisible(False)
            xbmcgui.Dialog().notification("Jellyfin", f"Couldn't load {self.title}: {error}")
            self.result = None
            self.close()
            return

        self.getControl(CTRL_LOADING).setVisible(False)
        if error:
            # A later page failed after earlier ones already loaded fine -
            # keep what's shown rather than throwing it all away.
            xbmc.log(
                f"{LOG_PREFIX} Browse: fetching children of {self.parent_id!r} ({self.title!r}) "
                f"stopped early after {elapsed:.1f}s with {len(self.items)} items: {error}",
                xbmc.LOGWARNING,
            )
            xbmcgui.Dialog().notification("Jellyfin", f"Stopped loading {self.title}: {error}")
        else:
            xbmc.log(
                f"{LOG_PREFIX} Browse: fetched {len(self.items)} children of {self.parent_id!r} "
                f"({self.title!r}) in {elapsed:.1f}s",
                xbmc.LOGINFO,
            )

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
