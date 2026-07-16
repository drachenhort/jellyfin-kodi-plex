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

    @classmethod
    def create(cls, addon_path, show=True, **kwargs):
        """Non-modal: returns immediately, caller keeps the live instance.

        Used for overlays like SeekDialog that must coexist with a
        background thread (playback progress reporting, OSD polling)
        instead of blocking the thread that created them.
        """
        window = cls(cls.xmlFile, addon_path, cls.theme, cls.res)
        window.setup(**kwargs)
        if show:
            window.show()
        return window

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


class BaseDialog(WindowMixin, xbmcgui.WindowXMLDialog):
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


def list_item(item, primary_art=None, backdrop_art=None):
    """Build an xbmcgui.ListItem for a Jellyfin BaseItemDto."""
    li = xbmcgui.ListItem(label=_display_label(item))
    art = {}
    if primary_art:
        art["thumb"] = primary_art
        art["poster"] = primary_art
    if backdrop_art:
        art["fanart"] = backdrop_art
    if art:
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
    return li
