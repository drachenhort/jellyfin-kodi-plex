"""Playback: resolves a stream via PlaybackInfo, plays it with xbmc.Player,
and reports position back to Jellyfin so watched-state/resume stays in sync
with other Jellyfin clients. Uses Kodi's own native video OSD/controls
during playback (pause, seek, stop, audio/subtitle selection) rather than a
custom overlay - an earlier custom seek dialog was removed after repeated
real-device testing showed it could leave the whole OSD unresponsive to
input (see git history for lib/windows/seekdialog.py if reviving the idea).
"""

import threading

import xbmc
import xbmcgui

from lib.jellyfin import playback
from lib.windows.kodigui import LOG_PREFIX

PROGRESS_REPORT_INTERVAL_SECONDS = 10
STARTUP_TIMEOUT_SECONDS = 30


class JellyfinPlayer(xbmc.Player):
    """One instance per playback; discard it once play_item() returns."""

    def __init__(self, client):
        super().__init__()
        self.client = client
        self._item_id = None
        self._play_session_id = None
        self._stop_event = threading.Event()
        self._progress_thread = None
        self._reported_stop = False
        self._end_reason = "ended"

    def play_item(self, item_id, item_type=None, resume_ticks=0):
        """Returns "ended" (played to completion), "stopped" (user backed
        out or explicitly stopped early), or "error" (playback never started,
        or Kodi reported a playback error) - lib.player.play_queue() uses
        this to decide whether to auto-advance to the next item."""
        media_info = playback.get_playback_info(self.client, item_id)
        media_sources = media_info.get("MediaSources") or []
        if not media_sources:
            raise RuntimeError(f"No playable media source for item {item_id}")
        media_source = media_sources[0]
        url, play_session_id = playback.stream_url(self.client, item_id, media_source, item_type=item_type)

        self._item_id = item_id
        self._play_session_id = play_session_id
        self._reported_stop = False
        self._end_reason = "ended"

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

        # Block the calling window loop until playback actually ends, since
        # lib/main.py's window stack expects play_item() to be synchronous.
        # self.play() is async - Kodi may still be opening/buffering the
        # stream for a while before isPlayingVideo()/isPlaying() go True, so
        # "started" has to be observed before "not playing" can mean
        # "finished" rather than "hasn't started yet". Without this, a slow
        # stream open raced this loop into exiting on its very first check
        # (both still False) and returning immediately while the video kept
        # playing in the background, orphaned from the rest of the addon.
        monitor = xbmc.Monitor()
        started = False
        seconds_waiting_to_start = 0
        while True:
            if monitor.waitForAbort(1):
                # Kodi is telling the script to exit (shutdown, being
                # force-killed to launch something else, etc.) - without
                # this, Kodi's player keeps playing after our script (and
                # its progress-reporting thread) is already gone.
                self._end_reason = "stopped"
                if self.isPlaying():
                    self.stop()
                break
            if self.isPlayingVideo() or self.isPlayingAudio():
                started = True
            elif started or self._stop_event.is_set():
                break
            else:
                # Still hasn't started (may just be slow to open/buffer) -
                # but don't wait forever for a stream that will never come,
                # in case Kodi doesn't fire onPlayBackError for this failure.
                seconds_waiting_to_start += 1
                if seconds_waiting_to_start >= STARTUP_TIMEOUT_SECONDS:
                    xbmc.log(
                        f"{LOG_PREFIX} giving up: playback of {item_id} never "
                        f"started within {STARTUP_TIMEOUT_SECONDS}s",
                        xbmc.LOGWARNING,
                    )
                    self._end_reason = "error"
                    if self.isPlaying():
                        self.stop()
                    break
            if started and xbmc.getCondVisibility("Window.IsActive(home)"):
                # The user backed all the way out to Kodi's own native home
                # screen (e.g. a remote's dedicated Home button) while this
                # addon's playback was still going. Our own screens are all
                # separate script windows, never Kodi's built-in "home", so
                # this only fires on that specific escape route. Gated on
                # `started` (not just isPlaying()) so it can't fire during
                # the ambiguous opening/buffering phase - logged explicitly
                # since a previous attempt at this check was reverted after
                # a confusing real-device result that, on reflection, was
                # likely actually caused by the startup race fixed above,
                # not by this condition misfiring.
                xbmc.log(
                    f"{LOG_PREFIX} stopping playback of {item_id}: Kodi's home "
                    "screen became active while still playing",
                    xbmc.LOGINFO,
                )
                self._end_reason = "stopped"
                self.stop()
                break
        self._finish()
        return self._end_reason

    def onPlayBackStopped(self):
        self._end_reason = "stopped"
        self._stop_event.set()

    def onPlayBackEnded(self):
        self._end_reason = "ended"
        self._stop_event.set()

    def onPlayBackError(self):
        self._end_reason = "error"
        self._stop_event.set()

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


def play_item(client, item_id, item_type=None, resume_ticks=0):
    player = JellyfinPlayer(client)
    player.play_item(item_id, item_type=item_type, resume_ticks=resume_ticks)


def play_queue(client, item_ids, item_type=None):
    """Play a sequence of items back-to-back (e.g. an album's tracks, in
    play-all or shuffled order). Auto-advances only when a track plays to
    completion - if the user stops or backs out early, or a track errors,
    the rest of the queue is abandoned rather than barrelling on."""
    for item_id in item_ids:
        player = JellyfinPlayer(client)
        status = player.play_item(item_id, item_type=item_type)
        if status != "ended":
            break
