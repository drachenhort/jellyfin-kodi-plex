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
CTRL_RESULTS_GRID = 502
CTRL_STATUS_LABEL = 503
CTRL_BACK_BUTTON = 504

MAX_RESULTS = 50
QUERY_POLL_INTERVAL_MS = 300


class SearchWindow(ControlledWindow):
    xmlFile = "script-jellyfin-search.xml"

    def setup(self, client=None, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self._search_thread = None
        self._last_polled_text = None
        self._last_submitted_text = None

    def onInit(self):
        self.setFocusId(CTRL_QUERY)
        threading.Thread(target=self._poll_query, daemon=True).start()

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
        elif control_id == CTRL_RESULTS_GRID:
            self._open_selected()
        elif control_id == CTRL_BACK_BUTTON:
            self.result = None
            self.close()

    def _start_search(self):
        # Runs the actual query on a background thread (_search()) so a slow
        # server doesn't freeze the GUI thread - same fix as Home/Browse/
        # Detail's onInit(). Guard against a second call starting an
        # overlapping search while one is still in flight.
        if self._search_thread and self._search_thread.is_alive():
            return
        term = self.getControl(CTRL_QUERY).getText().strip()
        self._last_submitted_text = term
        self.getControl(CTRL_RESULTS_GRID).reset()
        if not term:
            self.getControl(CTRL_STATUS_LABEL).setLabel("")
            return
        self.getControl(CTRL_STATUS_LABEL).setLabel("Searching…")
        self._search_thread = threading.Thread(target=self._search, args=(term,), daemon=True)
        self._search_thread.start()

    def _search(self, term):
        started = time.time()
        try:
            response = library.search_items(self.client, term, limit=MAX_RESULTS)
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

        control = self.getControl(CTRL_RESULTS_GRID)
        list_items = []
        for item in items:
            primary = images.primary_image_url(self.client, item)
            backdrop = images.backdrop_image_url(self.client, item)
            list_items.append(list_item(item, primary, backdrop))
        control.addItems(list_items)

        self.getControl(CTRL_STATUS_LABEL).setLabel("" if items else "No results")
        if items:
            self.setFocusId(CTRL_RESULTS_GRID)

    def _open_selected(self):
        selected = self.getControl(CTRL_RESULTS_GRID).getSelectedItem()
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
