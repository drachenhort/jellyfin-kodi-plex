"""Home window: library shortcuts plus Plex-style hub rows (Continue
Watching / Next Up / Recently Added Movies / Recently Added TV).

self.result on close is one of:
  {"action": "browse", "library_id": ..., "library_name": ...}
  {"action": "open", "item_id": ..., "item_type": ..., "item_name": ...}
  {"action": "search"}
  {"action": "servers"}
  None (user backed out — lib/main.py treats this as "quit the addon")
"""

import xbmcgui

from lib.jellyfin import images, library
from lib.windows.kodigui import PLACEHOLDER_ART, ControlledWindow, list_item

CTRL_LIBRARIES = 200
CTRL_CONTINUE_WATCHING = 201
CTRL_NEXT_UP = 202
CTRL_RECENTLY_ADDED_MOVIES = 203
CTRL_SEARCH = 204
CTRL_RECENTLY_ADDED_TV = 205
CTRL_SERVERS = 206

HUB_CONTROLS = (
    CTRL_CONTINUE_WATCHING, CTRL_NEXT_UP, CTRL_RECENTLY_ADDED_MOVIES, CTRL_RECENTLY_ADDED_TV,
)


def _library_list_item(client, view):
    li = xbmcgui.ListItem(label=view.get("Name", ""))
    art_url = images.primary_image_url(client, view) or PLACEHOLDER_ART
    li.setArt({"thumb": art_url, "poster": art_url})
    li.setProperty("jellyfin_id", view.get("Id", ""))
    return li


class HomeWindow(ControlledWindow):
    xmlFile = "script-jellyfin-home.xml"

    def setup(self, client=None, **kwargs):
        super().setup(**kwargs)
        self.client = client

    def onInit(self):
        try:
            views = library.get_views(self.client)
            self._populate(CTRL_LIBRARIES, views, is_library=True)
            self._populate_episode_aware(CTRL_CONTINUE_WATCHING, library.get_resume(self.client))
            self._populate_episode_aware(CTRL_NEXT_UP, library.get_next_up(self.client))
            self._populate(CTRL_RECENTLY_ADDED_MOVIES, self._latest(views, "movies"))
            self._populate(CTRL_RECENTLY_ADDED_TV, self._latest(views, "tvshows"))
        except Exception as exc:  # noqa: BLE001 - a server/network failure shouldn't crash the addon
            xbmcgui.Dialog().notification("Jellyfin", f"Couldn't load Home: {exc}")
            self.result = None
            self.close()
            return

        self.setFocusId(CTRL_LIBRARIES)

    def _latest(self, views, collection_type):
        latest = []
        for view in views:
            if view.get("CollectionType") != collection_type:
                continue
            latest.extend(library.get_latest(self.client, parent_id=view.get("Id"), limit=10))
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
