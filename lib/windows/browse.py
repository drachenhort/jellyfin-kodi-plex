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

import xbmcgui

from lib.jellyfin import images, library
from lib.windows.kodigui import ControlledWindow, list_item

CTRL_TITLE = 300
CTRL_GRID = 301
CTRL_PLAY_ALL = 302
CTRL_SHUFFLE = 303

MAX_ITEMS = 200

# Only an album's own screen offers Play All/Shuffle - browsing an Artist
# still just drills down into that artist's Albums.
QUEUEABLE_PARENT_TYPES = {"MusicAlbum"}


class BrowseWindow(ControlledWindow):
    xmlFile = "script-jellyfin-browse.xml"

    def setup(self, client=None, parent_id=None, title="", parent_item_type=None, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.parent_id = parent_id
        self.title = title
        self.parent_item_type = parent_item_type
        self.items = []

    def onInit(self):
        self.getControl(CTRL_TITLE).setLabel(self.title)
        try:
            response = library.get_items(
                self.client, parent_id=self.parent_id, start_index=0, limit=MAX_ITEMS,
                recursive=False,
            )
        except Exception as exc:  # noqa: BLE001 - a server/network failure shouldn't crash the addon
            xbmcgui.Dialog().notification("Jellyfin", f"Couldn't load {self.title}: {exc}")
            self.result = None
            self.close()
            return
        self.items = response.get("Items", [])

        control = self.getControl(CTRL_GRID)
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

        self.setFocusId(CTRL_GRID)

    def _track_ids(self):
        return [item["Id"] for item in self.items if item.get("Type") == "Audio"]

    def handle_click(self, control_id):
        if control_id == CTRL_GRID:
            self._open_selected()
        elif control_id == CTRL_PLAY_ALL:
            self._play_queue(shuffle=False)
        elif control_id == CTRL_SHUFFLE:
            self._play_queue(shuffle=True)

    def _open_selected(self):
        selected = self.getControl(CTRL_GRID).getSelectedItem()
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
