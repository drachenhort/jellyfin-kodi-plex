"""Item detail / preplay window: fanart background, poster, metadata, cast,
a Play (or Resume) button, and a "More Like This" row of similar items.

self.result on close: {"action": "play", "item_id": ..., "resume_ticks": N},
{"action": "open", "item_id": ..., "item_type": ..., "item_name": ...} (a
similar item was clicked), or None (back).
"""

import threading
import time

import xbmc
import xbmcgui

from lib.jellyfin import images, library
from lib.windows.kodigui import LOG_PREFIX, ControlledWindow, list_item

CTRL_BACKDROP = 400
CTRL_POSTER = 401
CTRL_TITLE = 402
CTRL_META = 403
CTRL_OVERVIEW = 404
CTRL_CAST = 405
CTRL_PLAY_BUTTON = 406
CTRL_WATCHED_BUTTON = 407
CTRL_SIMILAR = 408

RESUME_THRESHOLD_TICKS = 10 * 10_000_000  # ignore resume points under 10s


def _meta_line(item):
    parts = []
    if item.get("Type") == "Audio":
        artists = item.get("Artists") or ([item["AlbumArtist"]] if item.get("AlbumArtist") else [])
        if artists:
            parts.append(", ".join(artists))
        if item.get("Album"):
            parts.append(item["Album"])
    if item.get("ProductionYear"):
        parts.append(str(item["ProductionYear"]))
    if item.get("RunTimeTicks"):
        minutes = int(item["RunTimeTicks"] / 10_000_000 / 60)
        parts.append(f"{minutes} min")
    if item.get("CommunityRating"):
        parts.append(f"{item['CommunityRating']:.1f}★")
    if item.get("Genres"):
        parts.append(", ".join(item["Genres"]))
    if (item.get("UserData") or {}).get("Played"):
        parts.append("Watched")
    return "  •  ".join(parts)


def _cast_line(item):
    people = [p["Name"] for p in (item.get("People") or []) if p.get("Type") == "Actor"]
    return ", ".join(people[:6])


class DetailWindow(ControlledWindow):
    xmlFile = "script-jellyfin-detail.xml"

    def setup(self, client=None, item_id=None, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.item_id = item_id
        self.item = None

    def onInit(self):
        # The skin's defaultcontrol already focuses the Play button before
        # this even runs, so handle_click() below must cope with a click
        # landing while self.item is still None - the fetch itself runs on
        # a background thread (_load()) so it can't block the GUI thread.
        self.getControl(CTRL_TITLE).setLabel("Loading…")
        threading.Thread(target=self._load, daemon=True).start()
        # Runs on its own thread, independent of _load() above - similar
        # items are a nice-to-have, secondary to the item's own metadata/
        # Play button, so a slow or failing Similar request must never hold
        # up (or take down) the rest of the page.
        threading.Thread(target=self._load_similar, daemon=True).start()

    def _load(self):
        started = time.time()
        try:
            item = library.get_item(self.client, self.item_id)
        except Exception as exc:  # noqa: BLE001 - a server/network failure shouldn't crash the addon
            xbmc.log(
                f"{LOG_PREFIX} Detail: fetching {self.item_id!r} failed after "
                f"{time.time() - started:.1f}s: {exc}",
                xbmc.LOGWARNING,
            )
            if self.closed_event.is_set():
                return
            xbmcgui.Dialog().notification("Jellyfin", f"Couldn't load item: {exc}")
            self.result = None
            self.close()
            return
        xbmc.log(
            f"{LOG_PREFIX} Detail: fetched {self.item_id!r} in {time.time() - started:.1f}s",
            xbmc.LOGINFO,
        )
        if self.closed_event.is_set():
            return
        self.item = item

        backdrop = images.backdrop_image_url(self.client, self.item)
        if backdrop:
            self.getControl(CTRL_BACKDROP).setImage(backdrop)
        poster = images.primary_image_url(self.client, self.item)
        if poster:
            self.getControl(CTRL_POSTER).setImage(poster)

        self.getControl(CTRL_TITLE).setLabel(self.item.get("Name", ""))
        self.getControl(CTRL_META).setLabel(_meta_line(self.item))
        self.getControl(CTRL_OVERVIEW).setText(self.item.get("Overview", ""))
        self.getControl(CTRL_CAST).setLabel(_cast_line(self.item))

        resume_ticks = (self.item.get("UserData") or {}).get("PlaybackPositionTicks", 0)
        if resume_ticks and resume_ticks > RESUME_THRESHOLD_TICKS:
            self.getControl(CTRL_PLAY_BUTTON).setLabel("Resume")
        else:
            self.getControl(CTRL_PLAY_BUTTON).setLabel("Play")

        self._set_watched_button_label()

    def _set_watched_button_label(self):
        played = bool((self.item.get("UserData") or {}).get("Played"))
        self.getControl(CTRL_WATCHED_BUTTON).setLabel("Mark as Unwatched" if played else "Mark as Watched")

    def _load_similar(self):
        try:
            items = library.get_similar(self.client, self.item_id)
        except Exception as exc:  # noqa: BLE001 - a failed/slow Similar lookup shouldn't affect the rest of the page
            xbmc.log(
                f"{LOG_PREFIX} Detail: fetching similar items for {self.item_id!r} failed: {exc}",
                xbmc.LOGWARNING,
            )
            return
        if self.closed_event.is_set():
            return
        control = self.getControl(CTRL_SIMILAR)
        control.addItems([
            list_item(item, images.primary_image_url(self.client, item),
                      images.backdrop_image_url(self.client, item))
            for item in items
        ])

    def handle_click(self, control_id):
        # Independent of self.item's own load state - similar items load on
        # a separate thread (see _load_similar) and could finish first.
        if control_id == CTRL_SIMILAR:
            self._open_similar()
            return
        if self.item is None:
            return
        if control_id == CTRL_PLAY_BUTTON:
            self._play()
        elif control_id == CTRL_WATCHED_BUTTON:
            threading.Thread(target=self._toggle_watched, daemon=True).start()

    def _open_similar(self):
        selected = self.getControl(CTRL_SIMILAR).getSelectedItem()
        if not selected:
            return
        self.result = {
            "action": "open",
            "item_id": selected.getProperty("jellyfin_id"),
            "item_type": selected.getProperty("jellyfin_type"),
            "item_name": selected.getLabel(),
            "item_overview": selected.getProperty("overview"),
        }
        self.close()

    def _play(self):
        resume_ticks = (self.item.get("UserData") or {}).get("PlaybackPositionTicks", 0)
        if resume_ticks <= RESUME_THRESHOLD_TICKS:
            resume_ticks = 0
        self.result = {
            "action": "play",
            "item_id": self.item_id,
            "item_type": self.item.get("Type"),
            "resume_ticks": resume_ticks,
        }
        self.close()

    def _toggle_watched(self):
        played = bool((self.item.get("UserData") or {}).get("Played"))
        try:
            if played:
                library.mark_unplayed(self.client, self.item_id)
            else:
                library.mark_played(self.client, self.item_id)
        except Exception as exc:  # noqa: BLE001 - a server/network failure shouldn't crash the addon
            xbmc.log(
                f"{LOG_PREFIX} Detail: marking {self.item_id!r} "
                f"{'unwatched' if played else 'watched'} failed: {exc}",
                xbmc.LOGWARNING,
            )
            if self.closed_event.is_set():
                return
            xbmcgui.Dialog().notification("Jellyfin", f"Couldn't update watched state: {exc}")
            return
        if self.closed_event.is_set():
            return
        self.item["UserData"] = self.item.get("UserData") or {}
        self.item["UserData"]["Played"] = not played
        self._set_watched_button_label()
        self.getControl(CTRL_META).setLabel(_meta_line(self.item))
