"""Shared WindowXML/WindowXMLDialog base classes.

Modelled on plex-for-kodi's lib/kodigui.py: each screen is a subclass that
just sets `xmlFile` and overrides onInit()/onClick()/onAction(). Kodi does
not automatically close a script addon's custom windows on Back/Escape the
way it does its own skin windows, so BACK_ACTIONS handling here is what
makes "Back" work at all.

`open()` blocks (via doModal(), which the base xbmcgui.Window class
supports, not just the Dialog subclasses) until the window sets
`self.result` and calls `self.close()`, then hands that result back to the
caller — this is how lib/main.py's window stack passes data (e.g. a chosen
library or item id) from one screen to the next.
"""

import math
import threading
import time

import xbmc
import xbmcgui

# Shared xbmc.log() prefix so log lines from any window or the player are
# easy to grep for as one group (e.g. `grep "script.jellyfin.plex" kodi.log`).
LOG_PREFIX = "[script.jellyfin.plex]"

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
BACK_ACTIONS = (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK)

# Bundled skin textures shown wherever a Jellyfin item/library has no art of
# its own (some servers leave this blank rather than generating/scraping a
# placeholder, and a music track/album/artist essentially never has its own
# image beyond the album's). Both are composed with generous margin around
# the icon so they survive both the 16:9 (Libraries row) and 2:3 (posters)
# crop-to-fill boxes used across the skin without clipping.
PLACEHOLDER_ART = "art-placeholder.png"
PLACEHOLDER_ART_MUSIC = "art-placeholder-music.png"

MUSIC_ITEM_TYPES = {"Audio", "MusicAlbum", "MusicArtist"}


def placeholder_art(item):
    """Which placeholder texture fits `item` - a BaseItemDto (checked via
    Type) or a library View (checked via CollectionType)."""
    if item.get("Type") in MUSIC_ITEM_TYPES or item.get("CollectionType") == "music":
        return PLACEHOLDER_ART_MUSIC
    return PLACEHOLDER_ART


# The loading overlay's percentage is simulated, not a real fraction of a
# known total - Home/Browse fetches don't know their total in advance
# (EnableTotalRecordCount=false). It's deliberately capped below 100 so it
# never looks "done" while the fetch is still actually running; the window
# sets the real 100%-equivalent (hides the overlay) once the fetch finishes.
PROGRESS_CEILING = 95
PROGRESS_TAU_SECONDS = 8.0


def progress_percent(started, ceiling=PROGRESS_CEILING, tau=PROGRESS_TAU_SECONDS):
    """Simulated loading percentage: climbs from 0 toward `ceiling` (an
    exponential approach, never reaching it) as time passes since `started`,
    so a slow fetch still visibly keeps advancing instead of parking on one
    number for however long it takes."""
    elapsed = max(0.0, time.time() - started)
    return min(ceiling, int(ceiling * (1 - math.exp(-elapsed / tau))))


class WindowMixin(object):
    xmlFile = None
    theme = "Main"
    res = "1080i"

    def setup(self, **kwargs):
        """Called once immediately after construction, before doModal()/show()."""
        self.result = None
        self.closed_event = threading.Event()
        self.loading_done = threading.Event()
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def open(cls, addon_path, **kwargs):
        """Modal: blocks until the window sets `self.result` and closes.

        Can raise RuntimeError("maximum number of windows reached") if Kodi
        has begun tearing down for shutdown - callers already check
        xbmc.Monitor().abortRequested() first, but that only narrows this
        race, it can't close it (Kodi can flip its teardown state in the
        gap between that check and this constructor call). Deliberately
        NOT caught here: an earlier attempt at swallowing it and returning
        None caused lib.main's window loop to immediately retry, hitting
        the same error every time in a tight loop (Kodi keeps refusing new
        windows for the rest of shutdown) - observed on a real device
        logging 100,000+ exceptions/sec and never actually exiting, worse
        than the crash-and-exit this was meant to fix. Letting it propagate
        once is what actually terminates the script promptly; lib.main.run()
        catches it exactly once at the top level instead.
        """
        window = cls(cls.xmlFile, addon_path, cls.theme, cls.res)
        window.setup(**kwargs)
        # Kodi doesn't force-close a script addon's own WindowXML/Dialog on
        # shutdown the way it does its native skin windows (see this
        # module's docstring) - doModal() only returns once Python code
        # calls close(), which otherwise only happens from Back-action
        # handling. Without this watcher, doModal() blocks forever once
        # Kodi sets its abort flag, and the whole script gets force-killed
        # after Kodi's 5-second shutdown grace period instead of exiting
        # cleanly (observed on a real device).
        abort_watcher = threading.Thread(target=window._watch_abort, daemon=True)
        abort_watcher.start()
        window.doModal()
        result = window.result
        del window
        return result

    def _watch_abort(self):
        monitor = xbmc.Monitor()
        while not self.closed_event.is_set():
            if monitor.waitForAbort(1):
                self.result = None
                self.close()
                return

    def onAction(self, action):
        if action.getId() in BACK_ACTIONS:
            self.result = None
            self.close()
            return
        self.handle_action(action)

    def close(self):
        self.closed_event.set()
        super().close()

    def handle_action(self, action):
        """Override for custom key/remote handling beyond Back."""
        pass

    def onClick(self, control_id):
        self.handle_click(control_id)

    def handle_click(self, control_id):
        """Override to react to button/list clicks."""
        pass


class ControlledWindow(WindowMixin, xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXML.__init__(self, *args, **kwargs)


class ControlledDialog(WindowMixin, xbmcgui.WindowXMLDialog):
    """Same WindowMixin conveniences as ControlledWindow, but backed by
    WindowXMLDialog instead of WindowXML - real Kodi treats a Dialog as a
    layer above whatever window is currently active (including the native
    Fullscreen Video window during playback) and routes remote input to it
    accordingly. A plain WindowXML shown non-modally during video playback
    does *not* get that treatment - Fullscreen Video keeps input priority
    over it, so its buttons are simply unreachable by remote. Used by
    lib.windows.next_episode_overlay.NextEpisodeOverlay, the one screen
    that needs to be shown (and clickable) over active video playback."""

    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)


def _display_label(item):
    """Grid caption for `item`: plain Name, except ordered children of a
    container (episodes within a season, tracks within an album) get their
    index number prefixed since Name alone doesn't convey ordering."""
    name = item.get("Name", "")
    item_type = item.get("Type")
    index = item.get("IndexNumber")
    if item_type == "Episode" and item.get("ParentIndexNumber") is not None and index is not None:
        return f"{item['ParentIndexNumber']}x{index:02d}. {name}"
    if item_type == "Audio" and index is not None:
        return f"{index}. {name}"
    return name


def _episode_code(item):
    """"4x12"-style season/episode code for an Episode item, or "" for
    anything else (or an episode missing season/episode numbers) - used
    where the number needs to display separately from the plain title
    rather than combined the way _display_label() combines them."""
    if item.get("Type") != "Episode":
        return ""
    season = item.get("ParentIndexNumber")
    episode = item.get("IndexNumber")
    if season is None or episode is None:
        return ""
    return f"{season}x{episode:02d}"


def _progress_text(item):
    """"72% watched · 34 min left"-style caption for a partially-played
    item, or "" if it hasn't been started (or has no runtime to measure
    against)."""
    position_ticks = (item.get("UserData") or {}).get("PlaybackPositionTicks") or 0
    runtime_ticks = item.get("RunTimeTicks") or 0
    if position_ticks <= 0 or runtime_ticks <= 0:
        return ""
    percent = round(position_ticks / runtime_ticks * 100)
    minutes_left = max(1, round((runtime_ticks - position_ticks) / 10_000_000 / 60))
    return f"{percent}% watched · {minutes_left} min left"


def _unwatched_count_text(item):
    """Remaining-unwatched-episode count for a Series/Season/BoxSet, capped at
    "99+" since the badge is only sized for a couple of digits, or "" if
    fully watched (or the item type doesn't carry UnplayedItemCount at all,
    e.g. a plain Movie or Episode)."""
    count = (item.get("UserData") or {}).get("UnplayedItemCount") or 0
    if count <= 0:
        return ""
    return "99+" if count > 99 else str(count)


def _ratings_text(item):
    """"TMDb 6.7 · RT 80%"-style caption from Jellyfin's two rating fields:
    CommunityRating (whichever metadata plugin populated it, commonly TMDb)
    and CriticRating (Rotten Tomatoes' critic/tomatometer score, 0-100).
    Jellyfin doesn't expose a separate IMDb score. Omits either half that's
    missing, and returns "" if neither is set."""
    parts = []
    community = item.get("CommunityRating")
    if community:
        parts.append(f"TMDb {community:.1f}")
    critic = item.get("CriticRating")
    if critic is not None:
        parts.append(f"RT {int(critic)}%")
    return " · ".join(parts)


def list_item(item, primary_art=None, backdrop_art=None):
    """Build an xbmcgui.ListItem for a Jellyfin BaseItemDto."""
    li = xbmcgui.ListItem(label=_display_label(item))
    placeholder = placeholder_art(item)
    art = {"thumb": primary_art or placeholder, "poster": primary_art or placeholder}
    if backdrop_art:
        art["fanart"] = backdrop_art
    li.setArt(art)
    info_tag = li.getVideoInfoTag()
    info_tag.setTitle(item.get("Name", ""))
    if item.get("Overview"):
        info_tag.setPlot(item["Overview"])
    if item.get("ProductionYear"):
        info_tag.setYear(item["ProductionYear"])
    if item.get("Genres"):
        info_tag.setGenres(item["Genres"])
    if item.get("RunTimeTicks"):
        info_tag.setDuration(int(item["RunTimeTicks"] / 10_000_000))
    user_data = item.get("UserData") or {}
    if user_data.get("PlaybackPositionTicks"):
        info_tag.setResumePoint(user_data["PlaybackPositionTicks"] / 10_000_000)
    li.setProperty("jellyfin_id", item.get("Id", ""))
    li.setProperty("jellyfin_type", item.get("Type", ""))
    li.setProperty("overview", item.get("Overview") or "")
    li.setProperty("series_name", item.get("SeriesName") or "")
    li.setProperty("episode_code", _episode_code(item))
    li.setProperty("progress_text", _progress_text(item))
    li.setProperty("ratings_text", _ratings_text(item))
    li.setProperty("watched", "true" if user_data.get("Played") else "")
    li.setProperty("unwatched_count", _unwatched_count_text(item))
    return li
