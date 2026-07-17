"""Search window: a query field, a Search button, and a poster-wall results
grid shared with lib/windows/browse.py.

Explicit-submit rather than search-as-you-type: Kodi's WindowXML edit control
has no cheap text-changed callback, so the query is only sent to Jellyfin
when the Search button is pressed (typing itself opens Kodi's native
on-screen keyboard, the same as the username/password fields in
lib/windows/login.py).

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

MAX_RESULTS = 50


class SearchWindow(ControlledWindow):
    xmlFile = "script-jellyfin-search.xml"

    def setup(self, client=None, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self._search_thread = None

    def onInit(self):
        self.setFocusId(CTRL_QUERY)

    def handle_click(self, control_id):
        if control_id == CTRL_SEARCH_BUTTON:
            self._start_search()
        elif control_id == CTRL_RESULTS_GRID:
            self._open_selected()

    def _start_search(self):
        # Runs the actual query on a background thread (_search()) so a slow
        # server doesn't freeze the GUI thread - same fix as Home/Browse/
        # Detail's onInit(). Guard against a second click starting an
        # overlapping search while one is still in flight.
        if self._search_thread and self._search_thread.is_alive():
            return
        term = self.getControl(CTRL_QUERY).getText().strip()
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
            "item_name": selected.getLabel(),
        }
        self.close()
