"""Clean Up window: every watched movie the user may delete on the left,
the "to be deleted" list on the right. Selecting a movie moves it between
the two lists; the Delete button permanently deletes everything on the
to-be-deleted list (after a confirmation).

The to-be-deleted list is persisted per server/user in the hidden
"delete_queue" setting (see lib/delete_queue.py), so marking movies and
deleting them can happen in separate sessions. A queued movie that is no
longer watched or deletable (or was deleted elsewhere) just drops off the
list on the next load, since only the current watched-movie listing is
offered.

self.result on close: always None - this screen is self-contained.
"""

import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib import delete_queue
from lib.jellyfin import images, library
from lib.windows.delete_confirm import confirm_delete
from lib.windows.kodigui import LOG_PREFIX, ControlledWindow, list_item

ADDON = xbmcaddon.Addon()
DELETE_QUEUE_SETTING = "delete_queue"

CTRL_WATCHED_LIST = 500
CTRL_QUEUE_LIST = 501
CTRL_DELETE_BUTTON = 502
CTRL_WATCHED_HEADER = 503
CTRL_QUEUE_HEADER = 504
CTRL_STATUS = 505


def _meta_text(item: dict) -> str:
    """"1979  •  1h 57min  •  watched 2026-05-01" - whatever parts exist."""
    parts = []
    if item.get("ProductionYear"):
        parts.append(str(item["ProductionYear"]))
    if item.get("RunTimeTicks"):
        total_minutes = int(item["RunTimeTicks"] / 10_000_000 / 60)
        hours, minutes = divmod(total_minutes, 60)
        parts.append(f"{hours}h {minutes}min" if hours else f"{minutes}min")
    last_played = (item.get("UserData") or {}).get("LastPlayedDate")
    if last_played:
        parts.append(f"watched {last_played[:10]}")
    return "  •  ".join(parts)


class CleanupWindow(ControlledWindow):
    xmlFile = "script-jellyfin-cleanup.xml"

    def setup(self, client=None, **kwargs) -> None:
        super().setup(**kwargs)
        self.client = client
        self.movies: list = []
        self.queued_ids: list = []
        self.deleting = False
        self.loaded = False
        self.queue_key = delete_queue.queue_key(
            getattr(client, "server_url", ""), getattr(client, "user_id", "") or ""
        )

    def onInit(self) -> None:
        self.getControl(CTRL_STATUS).setLabel("Loading watched movies…")
        self._update_headers()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            movies = library.get_watched_movies(self.client)
        except Exception as exc:  # noqa: BLE001 - a server/network failure shouldn't crash the addon
            xbmc.log(f"{LOG_PREFIX} Cleanup: fetching watched movies failed: {exc}", xbmc.LOGWARNING)
            if not self.closed_event.is_set():
                self.getControl(CTRL_STATUS).setLabel(f"Couldn't load watched movies: {exc}")
            return
        if self.closed_event.is_set():
            return
        self.movies = movies
        self.loaded = True
        known_ids = {m["Id"] for m in movies}
        saved = delete_queue.load(ADDON.getSetting(DELETE_QUEUE_SETTING), self.queue_key)
        self.queued_ids = [i for i in saved if i in known_ids]
        if self.queued_ids != saved:
            self._save_queue()
        self._refresh_lists()
        self.setFocusId(CTRL_WATCHED_LIST if self._unqueued() else CTRL_QUEUE_LIST)

    def _unqueued(self) -> list:
        queued = set(self.queued_ids)
        return [m for m in self.movies if m["Id"] not in queued]

    def _queued(self) -> list:
        by_id = {m["Id"]: m for m in self.movies}
        return [by_id[i] for i in self.queued_ids if i in by_id]

    def _list_item(self, item: dict) -> xbmcgui.ListItem:
        li = list_item(item, images.primary_image_url(self.client, item))
        li.setProperty("meta", _meta_text(item))
        return li

    def _fill(self, control_id: int, items: list, keep_position: int) -> None:
        control = self.getControl(control_id)
        control.reset()
        control.addItems([self._list_item(item) for item in items])
        if items:
            control.selectItem(min(max(keep_position, 0), len(items) - 1))

    def _refresh_lists(self, watched_pos: int = 0, queue_pos: int = 0) -> None:
        self._fill(CTRL_WATCHED_LIST, self._unqueued(), watched_pos)
        self._fill(CTRL_QUEUE_LIST, self._queued(), queue_pos)
        self._update_headers()

    def _update_headers(self) -> None:
        unqueued, queued = len(self._unqueued()), len(self.queued_ids)
        self.getControl(CTRL_WATCHED_HEADER).setLabel(f"Watched Movies ({unqueued})")
        self.getControl(CTRL_QUEUE_HEADER).setLabel(f"To Be Deleted ({queued})")
        self.getControl(CTRL_DELETE_BUTTON).setLabel(
            f"Delete {queued} Movie{'s' if queued != 1 else ''}" if queued else "Nothing to delete"
        )
        if not self.loaded:
            return
        status = ("Select a movie to move it between the two lists" if self.movies
                  else "No watched movies you can delete")
        self.getControl(CTRL_STATUS).setLabel(status)

    def handle_click(self, control_id: int) -> None:
        if self.deleting:
            return
        if control_id == CTRL_WATCHED_LIST:
            self._move(CTRL_WATCHED_LIST, add=True)
        elif control_id == CTRL_QUEUE_LIST:
            self._move(CTRL_QUEUE_LIST, add=False)
        elif control_id == CTRL_DELETE_BUTTON:
            self._confirm_delete()

    def _move(self, control_id: int, add: bool) -> None:
        control = self.getControl(control_id)
        selected = control.getSelectedItem()
        if not selected:
            return
        item_id = selected.getProperty("jellyfin_id")
        position = control.getSelectedPosition()
        if add and item_id not in self.queued_ids:
            self.queued_ids.append(item_id)
        elif not add and item_id in self.queued_ids:
            self.queued_ids.remove(item_id)
        self._save_queue()
        if add:
            self._refresh_lists(watched_pos=position, queue_pos=len(self.queued_ids) - 1)
        else:
            self._refresh_lists(queue_pos=position)
        # Moving the last item out of a list leaves it empty, and Kodi can't
        # keep focus on an empty list - hop to the other one instead.
        if (add and not self._unqueued()) or (not add and not self.queued_ids):
            self.setFocusId(CTRL_QUEUE_LIST if add else CTRL_WATCHED_LIST)

    def _save_queue(self) -> None:
        raw = ADDON.getSetting(DELETE_QUEUE_SETTING)
        ADDON.setSetting(DELETE_QUEUE_SETTING, delete_queue.save(raw, self.queue_key, self.queued_ids))

    def _confirm_delete(self) -> None:
        movies = self._queued()
        if not movies:
            xbmcgui.Dialog().notification("Jellyfin", "The to-be-deleted list is empty")
            return
        # Blocks further clicks until the summary/confirmation is answered -
        # the size lookup runs off the GUI thread and can take a moment.
        self.deleting = True
        self.getControl(CTRL_STATUS).setLabel(f"Calculating size of {len(movies)} movies…")
        threading.Thread(target=self._confirm_and_delete, args=(movies,), daemon=True).start()

    def _confirm_and_delete(self, movies: list) -> None:
        if confirm_delete(self.client, movies) and not self.closed_event.is_set():
            self._delete(movies)
            return
        self.deleting = False
        if not self.closed_event.is_set():
            self._update_headers()

    def _delete(self, movies: list) -> None:
        failed = []
        for index, movie in enumerate(movies, start=1):
            if not self.closed_event.is_set():
                self.getControl(CTRL_STATUS).setLabel(f"Deleting {index}/{len(movies)}: {movie.get('Name', '')}")
            try:
                library.delete_item(self.client, movie["Id"])
            except Exception as exc:  # noqa: BLE001 - keep going, report failures at the end
                xbmc.log(f"{LOG_PREFIX} Cleanup: deleting {movie['Id']!r} failed: {exc}", xbmc.LOGWARNING)
                failed.append(movie)
                continue
            self.movies = [m for m in self.movies if m["Id"] != movie["Id"]]
            self.queued_ids = [i for i in self.queued_ids if i != movie["Id"]]
        self._save_queue()
        self.deleting = False
        deleted = len(movies) - len(failed)
        message = f"Deleted {deleted} movie{'s' if deleted != 1 else ''}"
        if failed:
            message += f", {len(failed)} failed: {', '.join(m.get('Name', '') for m in failed)}"
        xbmcgui.Dialog().notification("Jellyfin", message)
        if not self.closed_event.is_set():
            self._refresh_lists()
            self.setFocusId(CTRL_QUEUE_LIST if self.queued_ids else CTRL_WATCHED_LIST)
