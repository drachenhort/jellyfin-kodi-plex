"""Playback: resolves a stream via PlaybackInfo, plays it with xbmc.Player,
shows a custom seek/OSD dialog in place of Kodi's stock one, and reports
position back to Jellyfin so watched-state/resume stays in sync with other
Jellyfin clients.
"""

import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib.jellyfin import playback
from lib.windows.seekdialog import SeekDialog

PROGRESS_REPORT_INTERVAL_SECONDS = 10
OSD_POLL_INTERVAL_SECONDS = 0.1


class JellyfinPlayer(xbmc.Player):
    """One instance per playback; discard it once play_item() returns."""

    def __init__(self, client):
        super().__init__()
        self.client = client
        self._item_id = None
        self._play_session_id = None
        self._title = ""
        self._stop_event = threading.Event()
        self._progress_thread = None
        self._osd_thread = None
        self._seek_dialog = None
        self._reported_stop = False

    def play_item(self, item_id, resume_ticks=0, title=""):
        media_info = playback.get_playback_info(self.client, item_id)
        media_source = media_info["MediaSources"][0]
        url, play_session_id = playback.stream_url(self.client, item_id, media_source)

        self._item_id = item_id
        self._play_session_id = play_session_id
        self._title = title
        self._reported_stop = False

        list_item = xbmcgui.ListItem(path=url)
        resume_seconds = resume_ticks / 10_000_000 if resume_ticks else 0
        if resume_seconds:
            list_item.setProperty("StartOffset", str(resume_seconds))

        playback.report_playback_start(
            self.client, item_id, play_session_id, position_ticks=resume_ticks
        )
        self.play(url, list_item)

        self._stop_event.clear()
        self._progress_thread = threading.Thread(target=self._report_progress_loop, daemon=True)
        self._progress_thread.start()
        self._osd_thread = threading.Thread(target=self._osd_monitor_loop, daemon=True)
        self._osd_thread.start()

        # Block the calling window loop until playback actually ends, since
        # lib/main.py's window stack expects play_item() to be synchronous.
        monitor = xbmc.Monitor()
        while self.isPlayingVideo() or (not self._stop_event.is_set() and self.isPlaying()):
            if monitor.waitForAbort(1):
                break
        self._finish()
        if self._seek_dialog is not None:
            self._seek_dialog.close()
            self._seek_dialog = None

    def onPlayBackStopped(self):
        self._stop_event.set()

    def onPlayBackEnded(self):
        self._stop_event.set()

    def onPlayBackError(self):
        self._stop_event.set()

    def _osd_monitor_loop(self):
        """Detect Kodi's own video OSD opening and show ours instead.

        Kodi has no API to suppress its stock OSD from appearing on a
        remote/keyboard press during playback; the workaround (same one the
        real Plex-for-Kodi addon uses) is to let it open, notice via
        `Window.IsActive(videoosd)`, and immediately show our own dialog on
        top of it.
        """
        had_osd = False
        while not self._stop_event.wait(OSD_POLL_INTERVAL_SECONDS):
            if not self.isPlayingVideo():
                had_osd = False
                continue
            active = xbmc.getCondVisibility("Window.IsActive(videoosd)")
            if active and not had_osd:
                had_osd = True
                self._show_seek_dialog()
            elif not active:
                had_osd = False

    def _show_seek_dialog(self):
        if self._seek_dialog is None:
            addon_path = xbmcaddon.Addon().getAddonInfo("path")
            self._seek_dialog = SeekDialog.create(addon_path, show=False, title=self._title)
        self._seek_dialog.show_osd()

    def _report_progress_loop(self):
        while not self._stop_event.wait(PROGRESS_REPORT_INTERVAL_SECONDS):
            try:
                if not self.isPlaying():
                    continue
                position_ticks = int(self.getTime() * 10_000_000)
                playback.report_playback_progress(
                    self.client, self._item_id, self._play_session_id, position_ticks
                )
            except Exception:  # noqa: BLE001 - a single failed report shouldn't kill playback
                pass

    def _finish(self):
        if self._reported_stop:
            return
        self._reported_stop = True
        try:
            position_ticks = int(self.getTime() * 10_000_000)
        except Exception:  # noqa: BLE001 - player may already be torn down
            position_ticks = 0
        playback.report_playback_stopped(
            self.client, self._item_id, self._play_session_id, position_ticks
        )


def play_item(client, item_id, resume_ticks=0, title=""):
    player = JellyfinPlayer(client)
    player.play_item(item_id, resume_ticks=resume_ticks, title=title)
