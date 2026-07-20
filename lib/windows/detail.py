"""Item detail / preplay window: fanart background, poster, metadata, cast,
a Play (or Resume) button, audio/subtitle track pickers, and a "More Like
This" row of similar items.

self.result on close: {"action": "play", "item_id": ..., "resume_ticks": N,
"audio_stream_index": N or None, "subtitle_stream_index": N or None},
{"action": "open", "item_id": ..., "item_type": ..., "item_name": ...} (a
similar item was clicked), or None (back).
"""

import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from lib.jellyfin import images, library
from lib.windows.kodigui import LOG_PREFIX, ControlledWindow, list_item

ADDON = xbmcaddon.Addon()
PREFERRED_AUDIO_LANGUAGE_SETTING = "preferred_audio_language"
PREFERRED_SUBTITLE_LANGUAGE_SETTING = "preferred_subtitle_language"

CTRL_BACKDROP = 400
CTRL_POSTER = 401
CTRL_TITLE = 402
CTRL_META = 403
CTRL_OVERVIEW = 404
CTRL_CAST = 405
CTRL_PLAY_BUTTON = 406
CTRL_WATCHED_BUTTON = 407
CTRL_SIMILAR = 408
CTRL_AUDIO_BUTTON = 409
CTRL_SUBTITLE_BUTTON = 410

RESUME_THRESHOLD_TICKS = 10 * 10_000_000  # ignore resume points under 10s

NO_SUBTITLES_LABEL = "None"
NO_LANGUAGE_PREFERENCE = "none"


def _format_runtime(run_time_ticks):
    """72_000_000_000 (ticks) -> "2h 0min"; under an hour -> "45min"."""
    total_minutes = int(run_time_ticks / 10_000_000 / 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes}min" if hours else f"{minutes}min"


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
    if item.get("OfficialRating"):
        parts.append(item["OfficialRating"])
    if item.get("RunTimeTicks"):
        parts.append(_format_runtime(item["RunTimeTicks"]))
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


def _stream_label(stream):
    """A human-readable track description - Jellyfin's own DisplayTitle
    (e.g. "English 5.1 - AC3 - Default") is already exactly this, built
    from the stream's language/codec/channel layout; only synthesize a
    fallback for the rare stream that lacks one."""
    if stream.get("DisplayTitle"):
        return stream["DisplayTitle"]
    parts = [p for p in (stream.get("Language"), stream.get("Codec")) if p]
    return ", ".join(parts) or f"Track {stream.get('Index', '?')}"


class DetailWindow(ControlledWindow):
    xmlFile = "script-jellyfin-detail.xml"

    def setup(self, client=None, item_id=None, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.item_id = item_id
        self.item = None
        self.audio_streams = []
        self.subtitle_streams = []
        # Indices into the two lists above (not Jellyfin's own MediaStreams
        # Index field, which counts across all stream types together) -
        # None for subtitles means "no subtitles", a valid, common choice.
        self.selected_audio_index = None
        self.selected_subtitle_index = None

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
        self._load_streams()

    def _set_watched_button_label(self):
        played = bool((self.item.get("UserData") or {}).get("Played"))
        self.getControl(CTRL_WATCHED_BUTTON).setLabel("Mark as Unwatched" if played else "Mark as Watched")

    def _load_streams(self):
        """Audio/subtitle tracks for the item's primary media source -
        MediaSources is requested via DEFAULT_ITEM_FIELDS, so this needs no
        extra network call. Both buttons are hidden entirely (via
        setVisible() below - deliberately no <visible> tag of its own in
        the skin XML, see that file's comment on this exact gotcha) rather
        than shown empty/pointless when the item genuinely only has one
        track of that type."""
        media_sources = self.item.get("MediaSources") or []
        streams = media_sources[0].get("MediaStreams") or [] if media_sources else []
        self.audio_streams = [s for s in streams if s.get("Type") == "Audio"]
        self.subtitle_streams = [s for s in streams if s.get("Type") == "Subtitle"]

        if self.audio_streams:
            preferred = (ADDON.getSetting(PREFERRED_AUDIO_LANGUAGE_SETTING) or "").strip().lower()
            match_index = self._find_stream_by_language(self.audio_streams, preferred)
            if match_index is not None:
                self.selected_audio_index = match_index
            else:
                # Preferred language (English by default) not on this item -
                # fall back to whichever track the source itself flags as
                # default, the same as before this setting existed.
                self.selected_audio_index = next(
                    (i for i, s in enumerate(self.audio_streams) if s.get("IsDefault")), 0
                )
        self._set_audio_button_label()
        self.getControl(CTRL_AUDIO_BUTTON).setVisible(len(self.audio_streams) > 1)

        # Subtitles default to off ("None") even if the source has some
        # marked default - Jellyfin's "default" subtitle flag is about the
        # server's own auto-select-subtitle setting, not a signal that most
        # viewers want them on. A forced track (honorifics/foreign-language
        # dialogue only) is still preselected regardless of this setting,
        # since it's meant to always be on, not a language preference.
        preferred_subtitle = (ADDON.getSetting(PREFERRED_SUBTITLE_LANGUAGE_SETTING) or "").strip().lower()
        subtitle_match = (
            self._find_stream_by_language(self.subtitle_streams, preferred_subtitle)
            if preferred_subtitle and preferred_subtitle != NO_LANGUAGE_PREFERENCE
            else None
        )
        if subtitle_match is not None:
            self.selected_subtitle_index = subtitle_match
        else:
            self.selected_subtitle_index = next(
                (i for i, s in enumerate(self.subtitle_streams) if s.get("IsForced")), None
            )
        self._set_subtitle_button_label()
        self.getControl(CTRL_SUBTITLE_BUTTON).setVisible(bool(self.subtitle_streams))

    @staticmethod
    def _find_stream_by_language(streams, language_code):
        if not language_code or language_code == NO_LANGUAGE_PREFERENCE:
            return None
        return next(
            (i for i, s in enumerate(streams) if (s.get("Language") or "").lower() == language_code), None
        )
        self.getControl(CTRL_SUBTITLE_BUTTON).setVisible(bool(self.subtitle_streams))

    def _set_audio_button_label(self):
        if self.selected_audio_index is None:
            label = "N/A"
        else:
            label = _stream_label(self.audio_streams[self.selected_audio_index])
        self.getControl(CTRL_AUDIO_BUTTON).setLabel(f"Audio: {label}")

    def _set_subtitle_button_label(self):
        if self.selected_subtitle_index is None:
            label = NO_SUBTITLES_LABEL
        else:
            label = _stream_label(self.subtitle_streams[self.selected_subtitle_index])
        self.getControl(CTRL_SUBTITLE_BUTTON).setLabel(f"Subtitles: {label}")

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
        elif control_id == CTRL_AUDIO_BUTTON:
            self._pick_audio()
        elif control_id == CTRL_SUBTITLE_BUTTON:
            self._pick_subtitle()

    def _pick_audio(self):
        if not self.audio_streams:
            return
        labels = [_stream_label(s) for s in self.audio_streams]
        choice = xbmcgui.Dialog().select("Audio Track", labels)
        if choice == -1:
            return
        self.selected_audio_index = choice
        self._set_audio_button_label()

    def _pick_subtitle(self):
        labels = [NO_SUBTITLES_LABEL] + [_stream_label(s) for s in self.subtitle_streams]
        choice = xbmcgui.Dialog().select("Subtitles", labels)
        if choice == -1:
            return
        self.selected_subtitle_index = None if choice == 0 else choice - 1
        self._set_subtitle_button_label()

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
            "audio_stream_index": self.selected_audio_index,
            "subtitle_stream_index": self.selected_subtitle_index,
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
