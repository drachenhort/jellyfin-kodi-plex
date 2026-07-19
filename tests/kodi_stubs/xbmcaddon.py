"""Minimal stand-in for Kodi's `xbmcaddon` module - covers only what this
addon's lib/main.py actually calls.
"""


class Addon:
    def __init__(self, id=None):
        self.id = id
        self._settings = {}
        self._info = {
            "path": "/fake/addon/path",
            "id": "script.jellyfin.plex",
            "version": "0.0.0",
        }

    def getSetting(self, id):
        return self._settings.get(id, "")

    def setSetting(self, id, value):
        self._settings[id] = value

    def getAddonInfo(self, key):
        return self._info.get(key, "")

    def openSettings(self):
        # Real Kodi blocks here until the user closes the native settings
        # dialog; nothing to simulate in tests beyond the call succeeding.
        pass
