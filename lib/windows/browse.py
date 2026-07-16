"""Generic container browse window: a poster-wall grid of one item's direct
children. Used at every level of the TV and Music hierarchies (a library's
top-level items, a series' seasons, a season's episodes, a folder-organized
music library's artists, an artist's albums, an album's tracks) as well as
flat libraries (Movies) with no intermediate levels.

M1 loads a single page of up to MAX_ITEMS items up front (sorted by name)
rather than implementing incremental scroll-paging — a reasonable place to
cut scope for the first vertical slice; true infinite scroll is M2 work.

self.result on close: {"action": "open", "item_id": ..., "item_type": ...,
"item_name": ...} or None (back).
"""

from lib.jellyfin import images, library
from lib.windows.kodigui import ControlledWindow, list_item

CTRL_TITLE = 300
CTRL_GRID = 301

MAX_ITEMS = 200


class BrowseWindow(ControlledWindow):
    xmlFile = "script-jellyfin-browse.xml"

    def setup(self, client=None, parent_id=None, title="", **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.parent_id = parent_id
        self.title = title

    def onInit(self):
        self.getControl(CTRL_TITLE).setLabel(self.title)
        response = library.get_items(
            self.client, parent_id=self.parent_id, start_index=0, limit=MAX_ITEMS,
            recursive=False,
        )
        items = response.get("Items", [])

        control = self.getControl(CTRL_GRID)
        control.reset()
        list_items = []
        for item in items:
            primary = images.primary_image_url(self.client, item)
            backdrop = images.backdrop_image_url(self.client, item)
            list_items.append(list_item(item, primary, backdrop))
        control.addItems(list_items)
        self.setFocusId(CTRL_GRID)

    def handle_click(self, control_id):
        if control_id != CTRL_GRID:
            return
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
