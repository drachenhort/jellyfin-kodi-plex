"""Minimal stand-in for Kodi's `xbmc` module - covers only what this
addon's lib/player.py, lib/main.py, and lib/windows/*.py actually call.

Not a general Kodi emulator: tests monkeypatch individual methods/functions
(or replace Monitor/Player entirely) to get the specific timing/state each
scenario needs, the same way tests/test_jellyfin_client.py monkeypatches
`requests` rather than running a real HTTP server.
"""

LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3


def log(msg, level=LOGINFO):
    pass


def sleep(milliseconds):
    pass


def getCondVisibility(condition):
    return False


def executebuiltin(function, wait=False):
    pass


class Monitor:
    """Real Kodi's waitForAbort() blocks up to `timeout` seconds; this
    returns immediately (tests don't want to really sleep), always
    reporting "no abort" unless a test replaces this class or instance."""

    def waitForAbort(self, timeout=None):
        return False

    def abortRequested(self):
        return False


class Player:
    """Base class for lib.player.JellyfinPlayer. All state here is a
    static default - tests monkeypatch these methods on the instance
    under test to simulate real playback timing."""

    def __init__(self):
        pass

    def play(self, item=None, listitem=None, windowed=False):
        pass

    def stop(self):
        pass

    def pause(self):
        pass

    def isPlaying(self):
        return False

    def isPlayingVideo(self):
        return False

    def getTime(self):
        return 0.0

    def seekTime(self, seconds):
        pass

    def onPlayBackStarted(self):
        pass

    def onAVStarted(self):
        pass

    def onPlayBackEnded(self):
        pass

    def onPlayBackStopped(self):
        pass

    def onPlayBackError(self):
        pass

    def onPlayBackPaused(self):
        pass

    def onPlayBackResumed(self):
        pass
