"""Movie picker page, opened from the Clean Up screen's "Select Movies…"
button: every deletable movie (watched first, then unwatched ones, marked as
such) in a two-column grid with a check mark per row. Selecting a row ticks
or unticks it; "All Watched" ticks every watched movie, "Clear" unticks
everything.

self.result on close: the list of ticked movie ids, in the order the movies
were given ("Done"), or None ("Cancel" / Back - no change).
"""

import xbmcgui

from lib.jellyfin import images, library
from lib.windows.delete_confirm import item_name, meta_text
from lib.windows.kodigui import ControlledWindow, list_item

CTRL_MOVIE_LIST = 600
CTRL_STATUS = 601
CTRL_DONE_BUTTON = 602
CTRL_CANCEL_BUTTON = 603
CTRL_ALL_WATCHED_BUTTON = 604
CTRL_CLEAR_BUTTON = 605

HINT = "Select a movie to tick or untick it"


class MoviePickerWindow(ControlledWindow):
    xmlFile = "script-jellyfin-moviepicker.xml"

    def setup(self, client=None, movies=None, selected_ids=None, **kwargs) -> None:
        super().setup(**kwargs)
        self.client = client
        self.movies: list = list(movies or [])
        self.selected: set = set(selected_ids or [])
        self.list_items: list = []

    def onInit(self) -> None:
        self.list_items = [self._list_item(movie) for movie in self.movies]
        control = self.getControl(CTRL_MOVIE_LIST)
        control.reset()
        control.addItems(self.list_items)
        self._update_status()
        self.setFocusId(CTRL_MOVIE_LIST if self.movies else CTRL_CANCEL_BUTTON)

    def _list_item(self, movie: dict) -> xbmcgui.ListItem:
        li = list_item(movie, images.primary_image_url(self.client, movie))
        li.setLabel(item_name(movie))
        li.setProperty("meta", meta_text(movie))
        li.setProperty("unwatched", "" if library.is_played(movie) else "true")
        li.setProperty("checked", "true" if movie["Id"] in self.selected else "")
        return li

    def handle_click(self, control_id: int) -> None:
        if control_id == CTRL_MOVIE_LIST:
            self._toggle_selected()
        elif control_id == CTRL_DONE_BUTTON:
            self.result = [m["Id"] for m in self.movies if m["Id"] in self.selected]
            self.close()
        elif control_id == CTRL_CANCEL_BUTTON:
            self.result = None
            self.close()
        elif control_id == CTRL_ALL_WATCHED_BUTTON:
            self.selected |= {m["Id"] for m in self.movies if library.is_played(m)}
            self._refresh_checks()
        elif control_id == CTRL_CLEAR_BUTTON:
            self.selected.clear()
            self._refresh_checks()

    def _toggle_selected(self) -> None:
        position = self.getControl(CTRL_MOVIE_LIST).getSelectedPosition()
        if not 0 <= position < len(self.movies):
            return
        movie_id = self.movies[position]["Id"]
        if movie_id in self.selected:
            self.selected.discard(movie_id)
        else:
            self.selected.add(movie_id)
        self._refresh_checks()

    def _refresh_checks(self) -> None:
        # ListItems added to a container stay live in real Kodi, so setting
        # a property on the same object updates the row's check mark.
        for movie, li in zip(self.movies, self.list_items):
            li.setProperty("checked", "true" if movie["Id"] in self.selected else "")
        self._update_status()

    def _update_status(self) -> None:
        count = len(self.selected & {m["Id"] for m in self.movies})
        self.getControl(CTRL_STATUS).setLabel(f"{count} of {len(self.movies)} selected  •  {HINT}")
