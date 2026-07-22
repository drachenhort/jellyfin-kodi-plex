""""Up Next" prompt shown after a TV episode finishes playing: offers the
next episode in the same season with a 30-second auto-play countdown,
Plex-style. lib/main.py opens this only when player.play_item() reports the
episode played to completion (not on a manual stop) and a next episode
exists (lib/jellyfin/library.get_next_episode_in_season()).

self.result on close is one of:
  {"action": "play"}  — either "Play Now" was clicked or the countdown hit 0
  None                — "Cancel"/Back: resume the normal detail-page flow
"""

import threading

import xbmcgui

from lib.jellyfin import images
from lib.windows.kodigui import ControlledWindow, placeholder_art

COUNTDOWN_SECONDS = 30


def _episode_code(item):
    """"4x12"-style season/episode code, or "" if either number is missing -
    same format as kodigui._episode_code(), duplicated locally rather than
    reaching into that module's private helper."""
    season = item.get("ParentIndexNumber")
    episode = item.get("IndexNumber")
    if season is None or episode is None:
        return ""
    return f"{season}x{episode:02d}"

CTRL_THUMB = 500
CTRL_TITLE = 501
CTRL_EPISODE_CODE = 502
CTRL_COUNTDOWN_LABEL = 503
CTRL_PLAY_NOW = 504
CTRL_CANCEL = 505


class NextEpisodeWindow(ControlledWindow):
    xmlFile = "script-jellyfin-nextepisode.xml"

    def setup(self, client=None, next_item=None, countdown_seconds=COUNTDOWN_SECONDS, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.next_item = next_item or {}
        self.countdown_seconds = countdown_seconds
        self._countdown_started = threading.Event()

    def onInit(self):
        self.getControl(CTRL_TITLE).setLabel(self.next_item.get("Name", ""))
        self.getControl(CTRL_EPISODE_CODE).setLabel(_episode_code(self.next_item))
        thumb = images.primary_image_url(self.client, self.next_item) if self.client else None
        self.getControl(CTRL_THUMB).setImage(thumb or placeholder_art(self.next_item))
        self.setFocusId(CTRL_PLAY_NOW)
        threading.Thread(target=self._run_countdown, daemon=True).start()

    def _run_countdown(self):
        # Only one countdown thread ever runs per window instance, but
        # onInit() can in principle fire more than once (WindowXML
        # convention) - guard so a second countdown thread can't also start.
        if self._countdown_started.is_set():
            return
        self._countdown_started.set()
        remaining = self.countdown_seconds
        while remaining > 0:
            self.getControl(CTRL_COUNTDOWN_LABEL).setLabel(
                f"Playing next episode in {remaining}..."
            )
            if self.closed_event.wait(1):
                return
            remaining -= 1
        self.result = {"action": "play"}
        self.close()

    def handle_click(self, control_id):
        if control_id == CTRL_PLAY_NOW:
            self.result = {"action": "play"}
            self.close()
        elif control_id == CTRL_CANCEL:
            self.result = None
            self.close()
