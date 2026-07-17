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

import threading

import xbmcgui

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
BACK_ACTIONS = (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK)

# Bundled skin texture shown wherever a Jellyfin item/library has no art of
# its own (some servers leave this blank rather than generating/scraping a
# placeholder). Composed with generous margin around the icon so it survives
# both the 16:9 (Libraries row) and 2:3 (posters) crop-to-fill boxes used
# across the skin without clipping.
PLACEHOLDER_ART = "art-placeholder.png"


class WindowMixin(object):
    xmlFile = None
    theme = "Main"
    res = "1080i"

    def setup(self, **kwargs):
        """Called once immediately after construction, before doModal()/show()."""
        self.result = None
        self.closed_event = threading.Event()
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def open(cls, addon_path, **kwargs):
        """Modal: blocks until the window sets `self.result` and closes."""
        window = cls(cls.xmlFile, addon_path, cls.theme, cls.res)
        window.setup(**kwargs)
        window.doModal()
        result = window.result
        del window
        return result

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
    art = {"thumb": primary_art or PLACEHOLDER_ART, "poster": primary_art or PLACEHOLDER_ART}
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
    li.setProperty("series_name", item.get("SeriesName") or "")
    li.setProperty("episode_code", _episode_code(item))
    li.setProperty("progress_text", _progress_text(item))
    li.setProperty("ratings_text", _ratings_text(item))
    return li
