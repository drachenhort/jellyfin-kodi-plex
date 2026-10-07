"""Clean Up window: watched items the user may delete on the left, the
"to be deleted" list on the right. The left list switches between Movies
(every watched movie) and TV Shows (every show that has at least one fully
watched season - see library.get_watched_seasons) via the mode button; the
to-be-deleted list is shared by both, so one Delete covers everything
queued. Selecting a movie moves it between the two lists; selecting a show
opens a picker of its fully watched seasons, and the picked seasons go on
the list (TV is only ever deleted per season, never a whole show at once).
Selecting a queued item takes it back off. Delete permanently deletes
everything on the to-be-deleted list after a confirmation that shows the
file count and size.

The to-be-deleted list is persisted per server/user in the hidden
"delete_queue" setting (see lib/delete_queue.py), so marking and deleting
can happen in separate sessions. A queued item that is no longer watched or
deletable (or was deleted elsewhere) just drops off the list on the next
load, since only the current watched listings are offered.

self.result on close: always None - this screen is self-contained.
"""

import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib import delete_queue
from lib.jellyfin import images, library
from lib.windows.delete_confirm import (
    confirm_delete, describe_count, item_name, result_message, season_choice_label,
)
from lib.windows.kodigui import LOG_PREFIX, ControlledWindow, list_item

ADDON = xbmcaddon.Addon()
DELETE_QUEUE_SETTING = "delete_queue"

CTRL_WATCHED_LIST = 500
CTRL_QUEUE_LIST = 501
CTRL_DELETE_BUTTON = 502
CTRL_WATCHED_HEADER = 503
CTRL_QUEUE_HEADER = 504
CTRL_STATUS = 505
CTRL_MODE_BUTTON = 506

MODE_MOVIES = "movies"
MODE_TV = "tv"
# mode -> (left list header, hint, empty-list status, mode button label to switch *to* the other)
MODE_TEXT = {
    MODE_MOVIES: ("Watched Movies", "Select a movie to put it on the to-be-deleted list",
                  "No watched movies you can delete", "Show TV Shows"),
    MODE_TV: ("TV Shows With Watched Seasons", "Select a show to pick which of its watched seasons to delete",
              "No fully watched seasons you can delete", "Show Movies"),
}
LOADERS = {MODE_MOVIES: "get_watched_movies", MODE_TV: "get_watched_seasons"}


def _format_minutes(run_time_ticks: int) -> str:
    total_minutes = int(run_time_ticks / 10_000_000 / 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes}min" if hours else f"{minutes}min"


def _meta_text(item: dict) -> str:
    """"1979  •  1h 57min  •  watched 2026-05-01" for a movie, "Season  •
    10 episodes  •  ..." for a season, "Watched: Season 1, Season 2" for a
    show entry (see _show_entries) - whatever parts exist."""
    if item.get("Type") == "Series":
        return "Watched: " + ", ".join(s.get("Name", "") for s in item.get("seasons", []))
    is_season = item.get("Type") == "Season"
    parts = ["Season"] if is_season else []
    if not is_season and item.get("ProductionYear"):
        parts.append(str(item["ProductionYear"]))
    if item.get("Type") == "Movie" and item.get("RunTimeTicks"):
        parts.append(_format_minutes(item["RunTimeTicks"]))
    if is_season and item.get("ChildCount"):
        count = item["ChildCount"]
        parts.append(f"{count} episode{'s' if count != 1 else ''}")
    last_played = (item.get("UserData") or {}).get("LastPlayedDate")
    if last_played:
        parts.append(f"watched {last_played[:10]}")
    return "  •  ".join(parts)


def _show_entries(seasons: list) -> list:
    """Group seasons (already ordered by show) into one left-list entry per
    show: a Series-shaped dict carrying its seasons, with the show's poster
    taken from the seasons' SeriesPrimaryImageTag."""
    shows: dict = {}
    for season in seasons:
        series_id = season.get("SeriesId") or season["Id"]
        if series_id not in shows:
            tag = season.get("SeriesPrimaryImageTag")
            shows[series_id] = {
                "Id": series_id, "Type": "Series", "Name": season.get("SeriesName", ""),
                "ImageTags": {"Primary": tag} if tag else {}, "seasons": [],
            }
        shows[series_id]["seasons"].append(season)
    return list(shows.values())


class CleanupWindow(ControlledWindow):
    xmlFile = "script-jellyfin-cleanup.xml"

    def setup(self, client=None, **kwargs) -> None:
        super().setup(**kwargs)
        self.client = client
        self.mode = MODE_MOVIES
        self.items: dict = {MODE_MOVIES: [], MODE_TV: []}
        self.queued_ids: list = []
        self.load_errors: list = []
        # Saved ids that couldn't be matched because a listing failed to
        # load - kept in the saved list so a transient error doesn't
        # silently un-queue them (see _load/_save_queue).
        self.preserved_ids: list = []
        self.deleting = False
        self.loaded = False
        self.queue_key = delete_queue.queue_key(
            getattr(client, "server_url", ""), getattr(client, "user_id", "") or ""
        )

    def onInit(self) -> None:
        self.getControl(CTRL_STATUS).setLabel("Loading watched movies and TV shows…")
        self._update_headers()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        for mode, loader in LOADERS.items():
            try:
                self.items[mode] = getattr(library, loader)(self.client)
            except Exception as exc:  # noqa: BLE001 - one failed listing shouldn't hide the other
                xbmc.log(f"{LOG_PREFIX} Cleanup: fetching watched {mode} failed: {exc}", xbmc.LOGWARNING)
                self.load_errors.append(f"Couldn't load {'TV shows' if mode == MODE_TV else 'movies'}: {exc}")
            if self.closed_event.is_set():
                return
        self.loaded = True
        known_ids = {i["Id"] for i in self._all()}
        saved = delete_queue.load(ADDON.getSetting(DELETE_QUEUE_SETTING), self.queue_key)
        self.queued_ids = [i for i in saved if i in known_ids]
        # Only prune the saved list when everything loaded - a failed TV
        # fetch must not silently drop queued shows.
        if self.load_errors:
            self.preserved_ids = [i for i in saved if i not in known_ids]
        elif self.queued_ids != saved:
            self._save_queue()
        self._refresh_lists()
        self.setFocusId(CTRL_WATCHED_LIST if self._unqueued() else CTRL_QUEUE_LIST)

    def _all(self) -> list:
        return self.items[MODE_MOVIES] + self.items[MODE_TV]

    def _unqueued(self) -> list:
        queued = set(self.queued_ids)
        return [i for i in self.items[self.mode] if i["Id"] not in queued]

    def _queued(self) -> list:
        by_id = {i["Id"]: i for i in self._all()}
        return [by_id[i] for i in self.queued_ids if i in by_id]

    def _left_items(self) -> list:
        unqueued = self._unqueued()
        return _show_entries(unqueued) if self.mode == MODE_TV else unqueued

    def _list_item(self, item: dict) -> xbmcgui.ListItem:
        li = list_item(item, images.primary_image_url(self.client, item))
        li.setLabel(item_name(item))
        li.setProperty("meta", _meta_text(item))
        return li

    def _fill(self, control_id: int, items: list, keep_position: int) -> None:
        control = self.getControl(control_id)
        control.reset()
        control.addItems([self._list_item(item) for item in items])
        if items:
            control.selectItem(min(max(keep_position, 0), len(items) - 1))

    def _refresh_lists(self, watched_pos: int = 0, queue_pos: int = 0) -> None:
        self._fill(CTRL_WATCHED_LIST, self._left_items(), watched_pos)
        self._fill(CTRL_QUEUE_LIST, self._queued(), queue_pos)
        self._update_headers()

    def _update_headers(self) -> None:
        header, hint, empty_status, mode_label = MODE_TEXT[self.mode]
        queued = self._queued()
        self.getControl(CTRL_WATCHED_HEADER).setLabel(f"{header} ({len(self._left_items())})")
        self.getControl(CTRL_QUEUE_HEADER).setLabel(f"To Be Deleted ({len(queued)})")
        self.getControl(CTRL_MODE_BUTTON).setLabel(mode_label)
        self.getControl(CTRL_DELETE_BUTTON).setLabel(
            f"Delete {describe_count(queued)}" if queued else "Nothing to delete"
        )
        if not self.loaded:
            return
        status = hint if self.items[self.mode] else empty_status
        self.getControl(CTRL_STATUS).setLabel("  •  ".join(self.load_errors + [status]))

    def handle_click(self, control_id: int) -> None:
        if self.deleting:
            return
        if control_id == CTRL_WATCHED_LIST and self.mode == MODE_TV:
            self._pick_seasons()
        elif control_id == CTRL_WATCHED_LIST:
            self._move(CTRL_WATCHED_LIST, add=True)
        elif control_id == CTRL_QUEUE_LIST:
            self._move(CTRL_QUEUE_LIST, add=False)
        elif control_id == CTRL_DELETE_BUTTON:
            self._confirm_delete()
        elif control_id == CTRL_MODE_BUTTON:
            self._toggle_mode()

    def _toggle_mode(self) -> None:
        self.mode = MODE_TV if self.mode == MODE_MOVIES else MODE_MOVIES
        self._fill(CTRL_WATCHED_LIST, self._left_items(), 0)
        self._update_headers()

    def _pick_seasons(self) -> None:
        control = self.getControl(CTRL_WATCHED_LIST)
        selected = control.getSelectedItem()
        if not selected:
            return
        position = control.getSelectedPosition()
        show = next((s for s in self._left_items() if s["Id"] == selected.getProperty("jellyfin_id")), None)
        if show is None:
            return
        seasons = show["seasons"]
        picked = xbmcgui.Dialog().multiselect(
            f"Delete watched seasons of '{show['Name']}'", [season_choice_label(s) for s in seasons]
        )
        if not picked:
            return
        self.queued_ids.extend(seasons[n]["Id"] for n in picked if seasons[n]["Id"] not in self.queued_ids)
        self._save_queue()
        self._refresh_lists(watched_pos=position, queue_pos=len(self.queued_ids) - 1)
        if not self._unqueued():
            self.setFocusId(CTRL_QUEUE_LIST)

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
        ids = self.queued_ids + [i for i in self.preserved_ids if i not in self.queued_ids]
        ADDON.setSetting(DELETE_QUEUE_SETTING, delete_queue.save(raw, self.queue_key, ids))

    def _confirm_delete(self) -> None:
        items = self._queued()
        if not items:
            xbmcgui.Dialog().notification("Jellyfin", "The to-be-deleted list is empty")
            return
        # Blocks further clicks until the summary/confirmation is answered -
        # the size lookup runs off the GUI thread and can take a moment
        # (a whole show means walking all its episodes).
        self.deleting = True
        self.getControl(CTRL_STATUS).setLabel(f"Calculating size of {describe_count(items)}…")
        threading.Thread(target=self._confirm_and_delete, args=(items,), daemon=True).start()

    def _confirm_and_delete(self, items: list) -> None:
        if confirm_delete(self.client, items) and not self.closed_event.is_set():
            self._delete(items)
            return
        self.deleting = False
        if not self.closed_event.is_set():
            self._update_headers()

    def _delete(self, items: list) -> None:
        failed = []
        for index, item in enumerate(items, start=1):
            if not self.closed_event.is_set():
                self.getControl(CTRL_STATUS).setLabel(f"Deleting {index}/{len(items)}: {item_name(item)}")
            try:
                library.delete_item(self.client, item["Id"])
            except Exception as exc:  # noqa: BLE001 - keep going, report failures at the end
                xbmc.log(f"{LOG_PREFIX} Cleanup: deleting {item['Id']!r} failed: {exc}", xbmc.LOGWARNING)
                failed.append(item)
                continue
            for mode in self.items:
                self.items[mode] = [i for i in self.items[mode] if i["Id"] != item["Id"]]
            self.queued_ids = [i for i in self.queued_ids if i != item["Id"]]
        self._save_queue()
        self.deleting = False
        xbmcgui.Dialog().notification("Jellyfin", result_message([i for i in items if i not in failed], failed))
        if not self.closed_event.is_set():
            self._refresh_lists()
            self.setFocusId(CTRL_QUEUE_LIST if self.queued_ids else CTRL_WATCHED_LIST)
