"""Custom seek/OSD dialog shown over video playback, replacing Kodi's stock
video OSD (`videoosd`).

Kodi doesn't let a script addon prevent its own default video OSD from
opening on a remote/keyboard press during playback. The workaround used by
the real Plex-for-Kodi addon (confirmed from its source) is: let Kodi's OSD
open as it normally would, detect that from a background thread polling
`Window.IsActive(videoosd)`, and immediately show this dialog — a
WindowXMLDialog opened afterwards renders and captures input above it, so
the native OSD becomes visually and functionally moot underneath. See
lib/player.py's `_osd_monitor_loop`, which drives this.

The seek bar / position / duration in the skin XML are bound directly to
Kodi's `Player.Progress` / `Player.Time` / `Player.Duration` infolabels
rather than polled from Python — Kodi keeps those current on its own
whenever this dialog is visible, no polling thread required for that part.
"""

import threading
import time

import xbmc

from lib.windows.kodigui import BACK_ACTIONS, BaseDialog

CTRL_TITLE_LABEL = 203
CTRL_PLAY_PAUSE = 100
CTRL_REWIND = 101
CTRL_FORWARD = 102
CTRL_STOP = 103
CTRL_SUBTITLES = 104
CTRL_AUDIO = 105

ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2

HIDE_DELAY_SECONDS = 5
SEEK_STEP_BACK_SECONDS = 10
SEEK_STEP_FORWARD_SECONDS = 30


class SeekDialog(BaseDialog):
    xmlFile = "script-jellyfin-seek_dialog.xml"

    def setup(self, title="", **kwargs):
        super().setup(**kwargs)
        self.title = title
        self.player = xbmc.Player()
        self._hide_at = 0
        self._hide_thread = None
        self._hide_stop = threading.Event()

    def onInit(self):
        self.getControl(CTRL_TITLE_LABEL).setLabel(self.title)
        self.show_osd()

    def show_osd(self):
        """(Re)display the dialog and (re)start its auto-hide countdown.

        Safe to call repeatedly on the same instance across an entire
        playback session — lib/player.py keeps one SeekDialog alive for the
        whole session rather than recreating it on every OSD trigger.
        """
        self.show()
        self._hide_at = time.time() + HIDE_DELAY_SECONDS
        if not (self._hide_thread and self._hide_thread.is_alive()):
            self._hide_stop.clear()
            self._hide_thread = threading.Thread(target=self._auto_hide_loop, daemon=True)
            self._hide_thread.start()

    def _auto_hide_loop(self):
        while not self._hide_stop.wait(0.5):
            if time.time() >= self._hide_at:
                self.close()
                return

    def onAction(self, action):
        # Back exits playback (matching Plex) rather than just dismissing
        # the OSD and leaving the video running behind it - the base
        # WindowMixin's BACK_ACTIONS handling only does the latter, so it's
        # overridden here rather than going through handle_action().
        if action.getId() in BACK_ACTIONS:
            self._stop_and_close()
            return
        self.handle_action(action)

    def handle_action(self, action):
        action_id = action.getId()
        if action_id == ACTION_MOVE_LEFT:
            self._seek_relative(-SEEK_STEP_BACK_SECONDS)
        elif action_id == ACTION_MOVE_RIGHT:
            self._seek_relative(SEEK_STEP_FORWARD_SECONDS)
        self.show_osd()

    def handle_click(self, control_id):
        self.show_osd()
        if control_id == CTRL_PLAY_PAUSE:
            self.player.pause()
        elif control_id == CTRL_REWIND:
            self._seek_relative(-SEEK_STEP_BACK_SECONDS)
        elif control_id == CTRL_FORWARD:
            self._seek_relative(SEEK_STEP_FORWARD_SECONDS)
        elif control_id == CTRL_STOP:
            self._stop_and_close()
        elif control_id == CTRL_SUBTITLES:
            xbmc.executebuiltin("Action(nextsubtitle)")
        elif control_id == CTRL_AUDIO:
            xbmc.executebuiltin("Action(audionextlanguage)")

    def _stop_and_close(self):
        self.player.stop()
        self.close()

    def _seek_relative(self, delta_seconds):
        if not self.player.isPlayingVideo():
            return
        try:
            new_time = max(self.player.getTime() + delta_seconds, 0)
            self.player.seekTime(new_time)
        except RuntimeError:
            pass  # not actually playing (race with playback ending)

    def close(self):
        self._hide_stop.set()
        super().close()
