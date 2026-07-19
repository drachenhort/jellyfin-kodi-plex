"""Home window: library shortcuts plus Plex-style hub rows (Continue
Watching / Next Up / Recently Added Movies / Recently Added TV / Recently
Added Music).

self.result on close is one of:
  {"action": "browse", "library_id": ..., "library_name": ...}
  {"action": "open", "item_id": ..., "item_type": ..., "item_name": ...}
  {"action": "search"}
  {"action": "servers"}
  None (user backed out — lib/main.py treats this as "quit the addon")

The Playlists show/hide toggle next to Search doesn't close the window or
go through self.result at all - it flips an addon setting and repopulates
the Libraries row in place, the same "mutate immediately" pattern
lib/windows/detail.py uses for its watched/unwatched toggle.
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from lib.jellyfin import images, library
from lib.windows.kodigui import LOG_PREFIX, ControlledWindow, list_item, placeholder_art, progress_percent

ADDON = xbmcaddon.Addon()
HIDE_PLAYLISTS_SETTING = "hide_playlists"
SHOW_CONTINUE_WATCHING_SETTING = "show_continue_watching"
SHOW_NEXT_UP_SETTING = "show_next_up"
SHOW_RECENTLY_ADDED_MOVIES_SETTING = "show_recently_added_movies"
SHOW_RECENTLY_ADDED_TV_SETTING = "show_recently_added_tv"
SHOW_RECENTLY_ADDED_MUSIC_SETTING = "show_recently_added_music"

CTRL_LIBRARIES = 200
CTRL_CONTINUE_WATCHING = 201
CTRL_NEXT_UP = 202
CTRL_RECENTLY_ADDED_MOVIES = 203
CTRL_SEARCH = 204
CTRL_RECENTLY_ADDED_TV = 205
CTRL_SERVERS = 206
CTRL_RECENTLY_ADDED_MUSIC = 207
CTRL_PLAYLISTS_TOGGLE = 208
CTRL_SETTINGS = 209
CTRL_LOADING = 220

HUB_CONTROLS = (
    CTRL_CONTINUE_WATCHING, CTRL_NEXT_UP, CTRL_RECENTLY_ADDED_MOVIES, CTRL_RECENTLY_ADDED_TV,
    CTRL_RECENTLY_ADDED_MUSIC,
)

# Libraries plus every hub row - one "step" each for the loading overlay's
# "N of TOTAL_LOAD_STEPS loaded" count, whether that step ultimately
# succeeds or (per _load_hub_row's own failure handling) fails and leaves
# its row empty; either way that step is done being attempted.
TOTAL_LOAD_STEPS = 1 + len(HUB_CONTROLS)


# Playlists is an auto-created Jellyfin library that isn't a real media
# collection to browse here (there's no browse.py support for it either) -
# hidden from the shortcut row by default rather than showing an empty/
# broken tile, but the toggle button next to Search lets it back in for
# anyone who does keep playlists there. The rest are shown in a fixed order
# (Movies, TV, Music) regardless of whatever order the server returns views
# in, with any other/unknown library type (including Playlists, when shown)
# kept after those, in the server's original relative order (Python's sort
# is stable) since there's nothing more specific to say about them.
LIBRARY_TYPE_ORDER = {"movies": 0, "tvshows": 1, "music": 2}


def _visible_library_views(views, hide_playlists=True):
    def is_hidden(view):
        return hide_playlists and view.get("CollectionType") == "playlists"

    visible = [v for v in views if not is_hidden(v)]
    return sorted(visible, key=lambda v: LIBRARY_TYPE_ORDER.get(v.get("CollectionType"), len(LIBRARY_TYPE_ORDER)))


def _library_list_item(client, view):
    li = xbmcgui.ListItem(label=view.get("Name", ""))
    art_url = images.primary_image_url(client, view) or placeholder_art(view)
    li.setArt({"thumb": art_url, "poster": art_url})
    li.setProperty("jellyfin_id", view.get("Id", ""))
    return li


class HomeWindow(ControlledWindow):
    xmlFile = "script-jellyfin-home.xml"

    def setup(self, client=None, select_control_id=None, select_item_id=None, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.views = None
        self.hide_playlists = ADDON.getSetting(HIDE_PLAYLISTS_SETTING) != "false"
        # Per-row visibility toggles, addon settings > Home - each row is
        # simply never fetched/populated when off, so the group's own
        # Container(x).NumItems>0 visibility condition in the skin XML
        # keeps it collapsed without any XML changes needed here.
        self.show_continue_watching = ADDON.getSetting(SHOW_CONTINUE_WATCHING_SETTING) != "false"
        self.show_next_up = ADDON.getSetting(SHOW_NEXT_UP_SETTING) != "false"
        self.show_recently_added_movies = ADDON.getSetting(SHOW_RECENTLY_ADDED_MOVIES_SETTING) != "false"
        self.show_recently_added_tv = ADDON.getSetting(SHOW_RECENTLY_ADDED_TV_SETTING) != "false"
        self.show_recently_added_music = ADDON.getSetting(SHOW_RECENTLY_ADDED_MUSIC_SETTING) != "false"
        self.loaded_steps = 0
        # Which item (if any) to re-select once its row is loaded, e.g.
        # because Home is being shown again after the user backed out of
        # whatever they opened from here - lets Back land back on the same
        # tile instead of resetting focus to the Libraries row.
        self.select_control_id = select_control_id
        self.select_item_id = select_item_id
        self._selected_target = False
        # onInit() overwrites this right before _load() actually starts;
        # set here too so tests that call _load() directly (bypassing
        # onInit(), per this file's existing convention) don't hit an
        # AttributeError.
        self._load_started = time.time()

    def onInit(self):
        # The actual fetch runs on a background thread (see _load()) so a
        # slow/large library (e.g. a big Music collection - the request that
        # first exposed this) doesn't freeze the whole GUI thread for the
        # duration; each population step below checks closed_event first in
        # case the user has already backed out while it was in flight.
        self.setFocusId(CTRL_LIBRARIES)
        self._update_playlists_toggle_label()
        self._load_started = time.time()
        self._update_loading_label()
        threading.Thread(target=self._load, daemon=True).start()
        threading.Thread(target=self._tick_progress, daemon=True).start()

    def _update_loading_label(self):
        # Shows both: a simulated percentage that keeps visibly climbing
        # even during a long stretch with no step completing (the real case
        # this was built for: a hub-row fetch that can take minutes against
        # a slow real library), and the actual "N of TOTAL_LOAD_STEPS"
        # count, which stays honest during that same stretch - a fetch
        # that's still stuck on step 2 says so, no matter how confidently
        # the percentage is climbing.
        percent = progress_percent(self._load_started)
        self.getControl(CTRL_LOADING).setLabel(
            f"Loading library… {percent}% ({self.loaded_steps} of {TOTAL_LOAD_STEPS})"
        )

    def _tick_progress(self):
        # A separate ticker rather than updating the label only after each
        # step completes in _load()/_load_hub_row() - a single slow step can
        # otherwise mean no visible update for a long stretch. This ticks
        # independently of step completion.
        while True:
            xbmc.sleep(300)
            if self.closed_event.is_set() or self.loading_done.is_set():
                return
            self._update_loading_label()

    def _load(self):
        # Only the Libraries row is essential - without it there's no Home
        # screen at all, so a failure there still closes the window. Each
        # hub row below is independent: a slow/failing real library (seen in
        # practice: a large Music collection's "recently added" query) must
        # not take the other, already-succeeded rows down with it.
        try:
            views = self._timed("get_views", library.get_views, self.client)
        except Exception as exc:  # noqa: BLE001 - a server/network failure shouldn't crash the addon
            if self.closed_event.is_set():
                return
            xbmcgui.Dialog().notification("Jellyfin", f"Couldn't load Home: {exc}")
            self.result = None
            self.close()
            return
        if self.closed_event.is_set():
            return
        visible_views = _visible_library_views(views, self.hide_playlists)
        self._populate(CTRL_LIBRARIES, visible_views, is_library=True)
        self._maybe_restore_selection(CTRL_LIBRARIES, visible_views)
        # self.views must only become non-None after the populate above has
        # returned - _toggle_playlists_visibility() (GUI thread) uses it as
        # its "safe to repopulate CTRL_LIBRARIES" guard, and this control
        # must never be mutated from two threads at once.
        self.views = views
        self.loaded_steps += 1
        self._update_loading_label()

        self._load_hub_row(
            CTRL_CONTINUE_WATCHING, "get_resume", library.get_resume, self.client,
            populate=self._populate_episode_aware, enabled=self.show_continue_watching,
        )
        self._load_hub_row(
            CTRL_NEXT_UP, "get_next_up", library.get_next_up, self.client,
            populate=self._populate_episode_aware, enabled=self.show_next_up,
        )
        self._load_hub_row(
            CTRL_RECENTLY_ADDED_MOVIES, "latest movies", self._latest, views, "movies",
            enabled=self.show_recently_added_movies,
        )
        self._load_hub_row(
            CTRL_RECENTLY_ADDED_TV, "latest tvshows", self._latest_tv_episodes, views,
            populate=self._populate_tv_posters, enabled=self.show_recently_added_tv,
        )
        self._load_hub_row(
            CTRL_RECENTLY_ADDED_MUSIC, "latest music", self._latest, views, "music",
            enabled=self.show_recently_added_music,
        )
        self.loading_done.set()
        if not self.closed_event.is_set():
            self.getControl(CTRL_LOADING).setVisible(False)

    def _load_hub_row(self, control_id, label, fetch, *args, populate=None, enabled=True, **kwargs):
        if self.closed_event.is_set():
            return
        try:
            if not enabled:
                return
            try:
                items = self._timed(label, fetch, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - one slow/broken row shouldn't blank the rest of Home
                xbmc.log(f"{LOG_PREFIX} Home: {label} failed, leaving that row empty: {exc}", xbmc.LOGWARNING)
                return
            if self.closed_event.is_set():
                return
            (populate or self._populate)(control_id, items)
            self._maybe_restore_selection(control_id, items)
        finally:
            # Counts as a completed step (for the loading overlay's "N of
            # TOTAL_LOAD_STEPS" count) whether the fetch succeeded, failed,
            # or the window closed mid-fetch - either way there's nothing
            # left to wait on for this row.
            self.loaded_steps += 1
            if not self.closed_event.is_set():
                self._update_loading_label()

    def _maybe_restore_selection(self, control_id, items):
        if control_id != self.select_control_id or self._selected_target:
            return
        for index, item in enumerate(items):
            if item.get("Id") == self.select_item_id:
                self.getControl(control_id).selectItem(index)
                self.setFocusId(control_id)
                self._selected_target = True
                return

    def _timed(self, label, fn, *args, **kwargs):
        """Logs how long each Home fetch step took (or how long it ran
        before failing) - a slow real library (e.g. a big Music collection)
        can make any one of these steps the one that's actually slow, and
        without this a timeout only shows as an unexplained gap in the log."""
        started = time.time()
        try:
            return fn(*args, **kwargs)
        finally:
            xbmc.log(f"{LOG_PREFIX} Home: {label} took {time.time() - started:.1f}s", xbmc.LOGINFO)

    def _latest(self, views, collection_type):
        latest = []
        for view in views:
            if view.get("CollectionType") != collection_type:
                continue
            latest.extend(library.get_latest(self.client, parent_id=view.get("Id"), limit=10))
        return latest

    def _latest_tv_episodes(self, views):
        """Recently added TV: individual episodes, newest-added first, not
        grouped/deduplicated by series."""
        latest = []
        for view in views:
            if view.get("CollectionType") != "tvshows":
                continue
            latest.extend(library.get_latest_episodes(self.client, parent_id=view.get("Id"), limit=10))
        return latest

    def _populate(self, control_id, items, is_library=False):
        control = self.getControl(control_id)
        control.reset()
        list_items = []
        for item in items:
            if is_library:
                list_items.append(_library_list_item(self.client, item))
            else:
                primary = images.primary_image_url(self.client, item)
                backdrop = images.backdrop_image_url(self.client, item)
                list_items.append(list_item(item, primary, backdrop))
        control.addItems(list_items)

    def _populate_tv_posters(self, control_id, items):
        """Recently Added TV: each tile shows its show's poster rather than
        the episode's own landscape screengrab - images.primary_image_url()
        would use that screengrab when the episode has one (which most do),
        so this always goes straight to the series poster instead, the same
        art series_poster_url() uses for Next Up/Continue Watching."""
        control = self.getControl(control_id)
        control.reset()
        list_items = []
        for item in items:
            primary = images.series_poster_url(self.client, item)
            backdrop = images.backdrop_image_url(self.client, item)
            list_items.append(list_item(item, primary, backdrop))
        control.addItems(list_items)

    def _populate_episode_aware(self, control_id, items):
        """Shared by Next Up and Continue Watching. Episode items show their
        show's poster (current season's own poster if it has one, else the
        series poster) instead of their own landscape screengrab, so the row
        reads as "here's what's next/in progress for each show" rather than
        a strip of random stills. Continue Watching also mixes in movies,
        which keep their own poster art since they have no season/series."""
        season_ids = {item["SeasonId"] for item in items if item.get("SeasonId")}
        seasons = library.get_items_by_ids(self.client, list(season_ids))
        season_by_id = {season["Id"]: season for season in seasons}

        control = self.getControl(control_id)
        control.reset()
        list_items = []
        for item in items:
            season_id = item.get("SeasonId")
            if season_id:
                primary = images.series_poster_url(self.client, item, season=season_by_id.get(season_id))
            else:
                primary = images.primary_image_url(self.client, item)
            backdrop = images.backdrop_image_url(self.client, item)
            list_items.append(list_item(item, primary, backdrop))
        control.addItems(list_items)

    def handle_click(self, control_id):
        if control_id == CTRL_LIBRARIES:
            self._open_library()
        elif control_id in HUB_CONTROLS:
            self._open_item(control_id)
        elif control_id == CTRL_SEARCH:
            self.result = {"action": "search"}
            self.close()
        elif control_id == CTRL_SERVERS:
            self.result = {"action": "servers"}
            self.close()
        elif control_id == CTRL_PLAYLISTS_TOGGLE:
            self._toggle_playlists_visibility()
        elif control_id == CTRL_SETTINGS:
            self._open_addon_settings()

    def _update_playlists_toggle_label(self):
        self.getControl(CTRL_PLAYLISTS_TOGGLE).setLabel("Show Playlists" if self.hide_playlists else "Hide Playlists")

    def _toggle_playlists_visibility(self):
        if self.views is None:
            return
        self.hide_playlists = not self.hide_playlists
        ADDON.setSetting(HIDE_PLAYLISTS_SETTING, "true" if self.hide_playlists else "false")
        self._update_playlists_toggle_label()
        self._populate(CTRL_LIBRARIES, _visible_library_views(self.views, self.hide_playlists), is_library=True)

    def _open_addon_settings(self):
        # openSettings() blocks (shows Kodi's native addon settings dialog)
        # until the user closes it, so this only resumes once whatever they
        # changed - hub row toggles, hide_playlists, sort order, etc. - is
        # already saved; refresh Home in place afterwards rather than
        # requiring a manual Back/re-open to see the effect.
        ADDON.openSettings()
        if self.closed_event.is_set():
            return
        self._refresh_after_settings_change()

    def _refresh_after_settings_change(self):
        self.hide_playlists = ADDON.getSetting(HIDE_PLAYLISTS_SETTING) != "false"
        self.show_continue_watching = ADDON.getSetting(SHOW_CONTINUE_WATCHING_SETTING) != "false"
        self.show_next_up = ADDON.getSetting(SHOW_NEXT_UP_SETTING) != "false"
        self.show_recently_added_movies = ADDON.getSetting(SHOW_RECENTLY_ADDED_MOVIES_SETTING) != "false"
        self.show_recently_added_tv = ADDON.getSetting(SHOW_RECENTLY_ADDED_TV_SETTING) != "false"
        self.show_recently_added_music = ADDON.getSetting(SHOW_RECENTLY_ADDED_MUSIC_SETTING) != "false"
        self._update_playlists_toggle_label()
        # A settings-driven refresh re-fetches every row from scratch (the
        # simplest way to correctly pick up a newly-enabled row, which was
        # never fetched the first time around) - same background-thread
        # pattern onInit() uses so this doesn't freeze the GUI thread.
        self.loading_done.clear()
        self.loaded_steps = 0
        self._load_started = time.time()
        self._update_loading_label()
        self.getControl(CTRL_LOADING).setVisible(True)
        threading.Thread(target=self._load, daemon=True).start()
        threading.Thread(target=self._tick_progress, daemon=True).start()

    def _open_library(self):
        selected = self.getControl(CTRL_LIBRARIES).getSelectedItem()
        if not selected:
            return
        self.result = {
            "action": "browse",
            "library_id": selected.getProperty("jellyfin_id"),
            "library_name": selected.getLabel(),
            "control_id": CTRL_LIBRARIES,
            "item_id": selected.getProperty("jellyfin_id"),
        }
        self.close()

    def _open_item(self, control_id):
        selected = self.getControl(control_id).getSelectedItem()
        if not selected:
            return
        self.result = {
            "action": "open",
            "item_id": selected.getProperty("jellyfin_id"),
            "item_type": selected.getProperty("jellyfin_type"),
            "item_name": selected.getLabel(),
            "item_overview": selected.getProperty("overview"),
            "control_id": control_id,
        }
        self.close()
