"""Minimal stand-in for Kodi's `xbmcgui` module - covers only what this
addon's lib/windows/*.py actually call. See xbmc.py's docstring for the
same "not a general emulator" caveat.
"""


class VideoInfoTag:
    def __init__(self):
        self.title = ""
        self.plot = ""
        self.year = None
        self.genres = []
        self.duration = None
        self.resume_point = None

    def setTitle(self, title):
        self.title = title

    def setPlot(self, plot):
        self.plot = plot

    def setYear(self, year):
        self.year = year

    def setGenres(self, genres):
        self.genres = genres

    def setDuration(self, seconds):
        self.duration = seconds

    def setResumePoint(self, seconds):
        self.resume_point = seconds


class ListItem:
    def __init__(self, label="", path=None, offscreen=False):
        self._label = label
        self.path = path
        self.art = {}
        self.properties = {}
        self._video_info_tag = VideoInfoTag()

    def setArt(self, art):
        self.art.update(art)

    def setProperty(self, key, value):
        self.properties[key] = value

    def getProperty(self, key):
        return self.properties.get(key, "")

    def setLabel(self, label):
        self._label = label

    def getLabel(self):
        return self._label

    def getVideoInfoTag(self):
        return self._video_info_tag


class ControlStub:
    """Generic stand-in for any getControl() result (list/panel/button/
    label/edit/image/progress/...). This addon doesn't need type-specific
    behavior in tests - just to record what was set, and let tests supply
    what getters (especially getSelectedItem()) should return."""

    def __init__(self):
        self._label = ""
        self._text = ""
        self.image = None
        self.items = []
        self.selected_item = None
        self.visible = True

    def setLabel(self, label):
        self._label = label

    def getLabel(self):
        return self._label

    def setText(self, text):
        self._text = text

    def getText(self):
        return self._text

    def setImage(self, url):
        self.image = url

    def reset(self):
        self.items = []
        self.selected_item = None

    def addItem(self, item):
        self.items.append(item)
        if self.selected_item is None:
            self.selected_item = item

    def addItems(self, items):
        self.items.extend(items)
        # Mirrors real Kodi's ControlList: each addItems() call resets the
        # highlighted position back to the top of the whole list, not just
        # the newly appended items - a selectItem() call from an earlier
        # page gets silently undone by a later page's addItems() unless the
        # caller re-selects after every page has landed.
        if items:
            self.selected_item = self.items[0]

    def getSelectedItem(self):
        return self.selected_item

    def selectItem(self, index):
        if 0 <= index < len(self.items):
            self.selected_item = self.items[index]

    def setVisible(self, visible):
        self.visible = visible


class _WindowBase:
    def __init__(self, xmlFilename=None, scriptPath=None, defaultSkin="Default", defaultRes="720p"):
        self.xmlFilename = xmlFilename
        self.scriptPath = scriptPath
        self.defaultSkin = defaultSkin
        self.defaultRes = defaultRes
        self._controls = {}
        self._focus_id = None
        self.closed = False
        self.shown = False
        self._properties = {}

    def setProperty(self, key, value):
        self._properties[key] = value

    def getProperty(self, key):
        return self._properties.get(key, "")

    def getControl(self, control_id):
        if control_id not in self._controls:
            self._controls[control_id] = ControlStub()
        return self._controls[control_id]

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id

    def doModal(self):
        pass

    def show(self):
        self.shown = True

    def close(self):
        self.closed = True

    def onInit(self):
        pass

    def onClick(self, control_id):
        pass

    def onAction(self, action):
        pass


class Window(_WindowBase):
    pass


class WindowXML(_WindowBase):
    pass


class WindowXMLDialog(_WindowBase):
    pass


class Dialog:
    def notification(self, heading, message, icon=None, time=None, sound=True):
        pass

    def yesno(self, heading, message, *args, **kwargs):
        return False

    def select(self, heading, options, **kwargs):
        return -1
