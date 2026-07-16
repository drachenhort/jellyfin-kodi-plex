"""Library browse window: a poster-wall grid for one library.

M1 loads a single page of up to MAX_ITEMS items up front (sorted by name)
rather than implementing incremental scroll-paging — a reasonable place to
cut scope for the first vertical slice; true infinite scroll is M2 work.

self.result on close: {"action": "detail", "item_id": ...} or None (back).
"""

from lib.jellyfin import images, library
from lib.windows.kodigui import ControlledWindow, list_item

CTRL_TITLE = 300
CTRL_GRID = 301

MAX_ITEMS = 200


class BrowseWindow(ControlledWindow):
    xmlFile = "script-jellyfin-browse.xml"

    def setup(self, client=None, library_id=None, library_name="", **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.library_id = library_id
        self.library_name = library_name

    def onInit(self):
        self.getControl(CTRL_TITLE).setLabel(self.library_name)
        response = library.get_items(
            self.client, parent_id=self.library_id, start_index=0, limit=MAX_ITEMS
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
        self.result = {"action": "detail", "item_id": selected.getProperty("jellyfin_id")}
        self.close()
