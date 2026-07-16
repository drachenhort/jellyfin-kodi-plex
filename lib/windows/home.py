"""Home window: library shortcuts plus Plex-style hub rows (Continue
Watching / Next Up / Recently Added).

self.result on close is one of:
  {"action": "browse", "library_id": ..., "library_name": ...}
  {"action": "open", "item_id": ..., "item_type": ..., "item_name": ...}
  {"action": "search"}
  None (user backed out — lib/main.py treats this as "quit the addon")
"""

import xbmcgui

from lib.jellyfin import images, library
from lib.windows.kodigui import ControlledWindow, list_item

CTRL_LIBRARIES = 200
CTRL_CONTINUE_WATCHING = 201
CTRL_NEXT_UP = 202
CTRL_RECENTLY_ADDED = 203
CTRL_SEARCH = 204

HUB_CONTROLS = (CTRL_CONTINUE_WATCHING, CTRL_NEXT_UP, CTRL_RECENTLY_ADDED)


def _library_list_item(client, view):
    li = xbmcgui.ListItem(label=view.get("Name", ""))
    art_url = images.primary_image_url(client, view)
    if art_url:
        li.setArt({"thumb": art_url, "poster": art_url})
    li.setProperty("jellyfin_id", view.get("Id", ""))
    return li


class HomeWindow(ControlledWindow):
    xmlFile = "script-jellyfin-home.xml"

    def setup(self, client=None, **kwargs):
        super().setup(**kwargs)
        self.client = client

    def onInit(self):
        self._populate(CTRL_LIBRARIES, library.get_views(self.client), is_library=True)
        self._populate(CTRL_CONTINUE_WATCHING, library.get_resume(self.client))
        self._populate(CTRL_NEXT_UP, library.get_next_up(self.client))

        latest = []
        for view in library.get_views(self.client):
            latest.extend(library.get_latest(self.client, parent_id=view.get("Id"), limit=10))
        self._populate(CTRL_RECENTLY_ADDED, latest)

        self.setFocusId(CTRL_LIBRARIES)

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

    def handle_click(self, control_id):
        if control_id == CTRL_LIBRARIES:
            self._open_library()
        elif control_id in HUB_CONTROLS:
            self._open_item(control_id)
        elif control_id == CTRL_SEARCH:
            self.result = {"action": "search"}
            self.close()

    def _open_library(self):
        selected = self.getControl(CTRL_LIBRARIES).getSelectedItem()
        if not selected:
            return
        self.result = {
            "action": "browse",
            "library_id": selected.getProperty("jellyfin_id"),
            "library_name": selected.getLabel(),
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
        }
        self.close()
