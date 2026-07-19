"""Search window: a query field, a Search button, and a poster-wall results
grid shared with lib/windows/browse.py.

Search-as-you-type via polling, not a text-changed callback: Kodi's WindowXML
edit control doesn't expose one, so _poll_query() checks getText() on a timer
instead and submits once the text has held steady for one poll interval. This
also covers the on-screen-keyboard case (which commits the whole typed string
in one shot when closed, same as the username/password fields in
lib/windows/login.py) as well as a physical keyboard typing character by
character - either way the query only actually gets sent once typing pauses,
so it doesn't fire a request per keystroke. The Search button remains for an
explicit, immediate submit.

self.result on close: {"action": "open", "item_id": ..., "item_type": ...,
"item_name": ...} or None (back).
"""

import threading
import time

import xbmc

from lib.jellyfin import images, library
from lib.windows.kodigui import LOG_PREFIX, ControlledWindow, list_item

CTRL_QUERY = 500
CTRL_SEARCH_BUTTON = 501
CTRL_STATUS_LABEL = 503
CTRL_BACK_BUTTON = 504
CTRL_FILTER_MOVIES = 505
CTRL_FILTER_TV = 506
CTRL_FILTER_MUSIC = 507
CTRL_RESULTS_MOVIES = 508
CTRL_RESULTS_TV = 509
CTRL_RESULTS_MUSIC = 510

MAX_RESULTS = 50
QUERY_POLL_INTERVAL_MS = 300

# Each filter toggle's control id -> the Jellyfin item types it contributes
# to the search's IncludeItemTypes. TV covers both Series and Episode (a
# matching episode is still "a TV show" from the user's point of view, even
# though the item itself isn't a Series) - same idea for Music covering all
# three of Jellyfin's music item types in one toggle.
FILTER_ITEM_TYPES = {
    CTRL_FILTER_MOVIES: ("Movie",),
    CTRL_FILTER_TV: ("Series", "Episode"),
    CTRL_FILTER_MUSIC: ("MusicArtist", "MusicAlbum", "Audio"),
}
FILTER_LABELS = {
    CTRL_FILTER_MOVIES: "Movies",
    CTRL_FILTER_TV: "TV Shows",
    CTRL_FILTER_MUSIC: "Music",
}

# Which results row (see script-jellyfin-search.xml's grouplist) each result
# item type lands in - results are grouped under one heading per category
# (Movies/TV Shows/Music) instead of one flat mixed grid, since a broad term
# (e.g. a show with tie-in soundtrack albums and a same-named movie) could
# otherwise return a wall of results with no way to tell them apart at a
# glance.
RESULT_ROW_FOR_TYPE = {
    "Movie": CTRL_RESULTS_MOVIES,
    "Series": CTRL_RESULTS_TV,
    "Episode": CTRL_RESULTS_TV,
    "MusicArtist": CTRL_RESULTS_MUSIC,
    "MusicAlbum": CTRL_RESULTS_MUSIC,
    "Audio": CTRL_RESULTS_MUSIC,
}
RESULT_ROWS = (CTRL_RESULTS_MOVIES, CTRL_RESULTS_TV, CTRL_RESULTS_MUSIC)


class SearchWindow(ControlledWindow):
    xmlFile = "script-jellyfin-search.xml"

    def setup(self, client=None, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self._search_thread = None
        self._last_polled_text = None
        self._last_submitted_text = None
        # All three filters start enabled - unchecking one narrows the next
        # search's IncludeItemTypes rather than just hiding results that
        # already came back, so an excluded category doesn't even cost a
        # server-side lookup.
        self._active_filters = set(FILTER_ITEM_TYPES)

    def onInit(self):
        self.setFocusId(CTRL_QUERY)
        for control_id in FILTER_ITEM_TYPES:
            self._update_filter_label(control_id)
        threading.Thread(target=self._poll_query, daemon=True).start()

    def _update_filter_label(self, control_id):
        checked = "x" if control_id in self._active_filters else " "
        self.getControl(control_id).setLabel(f"[{checked}] {FILTER_LABELS[control_id]}")

    def _active_item_types(self):
        types = [t for control_id in self._active_filters for t in FILTER_ITEM_TYPES[control_id]]
        return ",".join(types)

    def _poll_query(self):
        # threading.Event.wait() rather than the xbmc.sleep()-then-check
        # pattern used elsewhere in this addon (e.g. browse.py's loading
        # ticker) - it blocks efficiently between polls in real Kodi *and*
        # returns immediately the moment close() sets closed_event, instead
        # of finishing out whatever's left of the current interval. That
        # matters more here than for a one-shot loading ticker: this loop
        # runs for the window's entire lifetime, and xbmc.sleep() is a
        # no-op in the test stub, which would otherwise make it spin at
        # 100% CPU for however long a test takes to close the window.
        while not self.closed_event.wait(QUERY_POLL_INTERVAL_MS / 1000):
            self._poll_query_once()

    def _poll_query_once(self):
        # See module docstring - fires _start_search() once the polled text
        # matches what was polled last time (i.e. held steady for one whole
        # interval) and differs from whatever was last actually submitted,
        # so an in-flight search that's still running when text changes
        # again just gets retried on a later tick once it finishes (
        # _start_search() is a no-op while one is already running). Split
        # out from _poll_query() so tests can drive the decision logic
        # directly instead of racing a real timer.
        text = self.getControl(CTRL_QUERY).getText().strip()
        if text == self._last_polled_text and text != self._last_submitted_text:
            self._start_search()
        self._last_polled_text = text

    def handle_click(self, control_id):
        if control_id == CTRL_SEARCH_BUTTON:
            self._start_search()
        elif control_id in RESULT_ROWS:
            self._open_selected(control_id)
        elif control_id == CTRL_BACK_BUTTON:
            self.result = None
            self.close()
        elif control_id in FILTER_ITEM_TYPES:
            self._toggle_filter(control_id)

    def _toggle_filter(self, control_id):
        if control_id in self._active_filters:
            self._active_filters.remove(control_id)
        else:
            self._active_filters.add(control_id)
        self._update_filter_label(control_id)
        # Force a re-submit even though the query text itself hasn't
        # changed - _start_search() only skips a search that's already in
        # flight, not one whose term matches the last one sent, so this is
        # enough to make a filter toggle actually re-query.
        self._last_submitted_text = None
        self._start_search()

    def _start_search(self):
        # Runs the actual query on a background thread (_search()) so a slow
        # server doesn't freeze the GUI thread - same fix as Home/Browse/
        # Detail's onInit(). Guard against a second call starting an
        # overlapping search while one is still in flight.
        if self._search_thread and self._search_thread.is_alive():
            return
        term = self.getControl(CTRL_QUERY).getText().strip()
        self._last_submitted_text = term
        for row_id in RESULT_ROWS:
            self.getControl(row_id).reset()
        if not term:
            self.getControl(CTRL_STATUS_LABEL).setLabel("")
            return
        item_types = self._active_item_types()
        if not item_types:
            # All three filters unchecked - nothing to search for, and an
            # empty IncludeItemTypes would mean "every type" to Jellyfin's
            # API rather than "none", so this has to be handled here instead
            # of just falling through to _search().
            self.getControl(CTRL_STATUS_LABEL).setLabel("No categories selected")
            return
        self.getControl(CTRL_STATUS_LABEL).setLabel("Searching…")
        self._search_thread = threading.Thread(
            target=self._search, args=(term, item_types), daemon=True
        )
        self._search_thread.start()

    def _search(self, term, item_types):
        started = time.time()
        try:
            response = library.search_items(
                self.client, term, limit=MAX_RESULTS, include_item_types=item_types
            )
        except Exception as exc:  # noqa: BLE001 - a server/network failure shouldn't crash the addon
            xbmc.log(
                f"{LOG_PREFIX} Search: {term!r} failed after {time.time() - started:.1f}s: {exc}",
                xbmc.LOGWARNING,
            )
            if self.closed_event.is_set():
                return
            self.getControl(CTRL_STATUS_LABEL).setLabel(f"Search failed: {exc}")
            return
        items = response.get("Items", [])
        xbmc.log(
            f"{LOG_PREFIX} Search: {term!r} returned {len(items)} results in "
            f"{time.time() - started:.1f}s",
            xbmc.LOGINFO,
        )
        if self.closed_event.is_set():
            return

        list_items_by_row = {row_id: [] for row_id in RESULT_ROWS}
        for item in items:
            row_id = RESULT_ROW_FOR_TYPE.get(item.get("Type"))
            if row_id is None:
                continue
            primary = images.primary_image_url(self.client, item)
            backdrop = images.backdrop_image_url(self.client, item)
            list_items_by_row[row_id].append(list_item(item, primary, backdrop))
        first_nonempty_row = None
        for row_id in RESULT_ROWS:
            row_items = list_items_by_row[row_id]
            if row_items:
                self.getControl(row_id).addItems(row_items)
                if first_nonempty_row is None:
                    first_nonempty_row = row_id

        self.getControl(CTRL_STATUS_LABEL).setLabel("" if items else "No results")
        if first_nonempty_row is not None:
            self.setFocusId(first_nonempty_row)

    def _open_selected(self, control_id):
        selected = self.getControl(control_id).getSelectedItem()
        if not selected:
            return
        self.result = {
            "action": "open",
            "item_id": selected.getProperty("jellyfin_id"),
            "item_type": selected.getProperty("jellyfin_type"),
            "item_overview": selected.getProperty("overview"),
            "item_name": selected.getLabel(),
        }
        self.close()
