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
from lib.windows.kodigui import LOG_PREFIX, ControlledWindow, list_item, progress_percent

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
        self._track_id_cache = []
        # onInit() overwrites this right before _load() actually starts;
        # set here too so tests that call _load() directly (bypassing
        # onInit(), per this file's existing convention) don't hit an
        # AttributeError.
        self._load_started = time.time()

    def onInit(self):
        # Title shows immediately (cheap, no network); the actual listing
        # fetch runs on a background thread (_load()) so a slow response
        # doesn't freeze the whole GUI thread - each step below checks
        # closed_event first in case the user already backed out.
        self.getControl(CTRL_TITLE).setLabel(self.title)
        self.getControl(CTRL_PLAY_ALL).setVisible(False)
        self.getControl(CTRL_SHUFFLE).setVisible(False)
        active_control = CTRL_EPISODE_LIST if self.is_episode_list else CTRL_GRID
        self.getControl(CTRL_GRID).setVisible(not self.is_episode_list)
        self.getControl(CTRL_EPISODE_LIST).setVisible(self.is_episode_list)
        self.setFocusId(active_control)
        self._load_started = time.time()
        self._update_loading_label()
        threading.Thread(target=self._load, daemon=True).start()
        threading.Thread(target=self._tick_progress, daemon=True).start()

    def _update_loading_label(self):
        # Shows both: a simulated percentage that keeps visibly climbing
        # even during a long stretch with no page arrivals (the real case
        # this was built for: a page that can now take up to the full 300s
        # timeout to answer), and the actual item count so far, which stays
        # honest during that same stretch - a fetch that has received
        # nothing still says "(0 items)" no matter how confidently the
        # percentage is climbing.
        percent = progress_percent(self._load_started)
        self.getControl(CTRL_LOADING).setLabel(
            f"Loading {self.title}… {percent}% ({len(self.items)} items)"
        )

    def _tick_progress(self):
        # A separate ticker rather than updating the label only from
        # _load()'s per-page loop - iter_items_paged() only yields once per
        # page, which for a slow real fetch could mean no visible update for
        # minutes at a time. This ticks independently of page arrivals.
        while True:
            xbmc.sleep(300)
            if self.closed_event.is_set() or self.loading_done.is_set():
                return
            self._update_loading_label()

    def _load(self):
        started = self._load_started
        active_control = CTRL_EPISODE_LIST if self.is_episode_list else CTRL_GRID
        control = self.getControl(active_control)
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
                was_empty = not self.items
                self.items.extend(page)
                control.addItems([
                    list_item(item, images.primary_image_url(self.client, item),
                              images.backdrop_image_url(self.client, item))
                    for item in page
                ])
                if was_empty:
                    # onInit() sets focus to this control before any items
                    # exist, so Kodi refuses it ("has been asked to focus,
                    # but it can't") and the control is left unfocusable -
                    # arrow keys/select land nowhere. Re-request focus now
                    # that it actually has items.
                    self.setFocusId(active_control)
                self._update_loading_label()
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
            self.loading_done.set()
            self.getControl(CTRL_LOADING).setVisible(False)
            xbmcgui.Dialog().notification("Jellyfin", f"Couldn't load {self.title}: {error}")
            self.result = None
            self.close()
            return

        self.loading_done.set()
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

        self._track_id_cache = [item["Id"] for item in self.items if item.get("Type") == "Audio"]
        show_queue_controls = self.parent_item_type in QUEUEABLE_PARENT_TYPES and self._track_id_cache
        self.getControl(CTRL_PLAY_ALL).setVisible(bool(show_queue_controls))
        self.getControl(CTRL_SHUFFLE).setVisible(bool(show_queue_controls))

    def _track_ids(self):
        return self._track_id_cache

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
