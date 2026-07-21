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
import xbmcaddon
import xbmcgui

from lib.jellyfin import playback, library
from lib.windows.kodigui import LOG_PREFIX

ADDON = xbmcaddon.Addon()
PROGRESS_REPORT_INTERVAL_SECONDS = 10
STARTUP_TIMEOUT_SECONDS = 30


def _max_streaming_bitrate():
    """The addon's "Max streaming bitrate" setting, in bits/sec - falls
    back to None (DEFAULT_DEVICE_PROFILE's own default) if unset or not a
    valid int."""
    try:
        return int(ADDON.getSetting("max_streaming_bitrate_mbps")) * 1_000_000
    except (TypeError, ValueError):
        return None


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
        self._audio_stream_index = None
        self._subtitle_stream_index = None
        self._last_position_ticks = 0

    def play_item(self, item_id, item_type=None, resume_ticks=0,
                  audio_stream_index=None, subtitle_stream_index=None):
        """Returns "ended" (played to completion), "stopped" (user backed
        out or explicitly stopped early), or "error" (playback never started,
        or Kodi reported a playback error) - lib.player.play_queue() uses
        this to decide whether to auto-advance to the next item."""
        try:
            item = library.get_item(self.client, item_id)
        except Exception:  # noqa: BLE001 - metadata is nice-to-have, not critical
            item = None

        media_info = playback.get_playback_info(
            self.client, item_id, max_streaming_bitrate=_max_streaming_bitrate()
        )
        if not media_info:
            raise RuntimeError(f"Failed to get playback info for item {item_id}")
        media_sources = media_info.get("MediaSources") or []
        if not media_sources:
            raise RuntimeError(f"No playable media source for item {item_id}")
        media_source = media_sources[0]
        url, play_session_id = playback.stream_url(self.client, item_id, media_source, item_type=item_type)

        self._item_id = item_id
        self._play_session_id = play_session_id
        self._reported_stop = False
        self._last_position_ticks = resume_ticks or 0
        self._end_reason = "ended"
        self._audio_stream_index = audio_stream_index
        self._subtitle_stream_index = subtitle_stream_index

        list_item = xbmcgui.ListItem(label=item.get("Name", "") if item else "", path=url)
        if item:
            info_tag = list_item.getVideoInfoTag()
            info_tag.setTitle(item.get("Name", ""))
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
        selection_applied = False
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
                if not selection_applied:
                    # Only meaningful once Kodi has actually opened the
                    # stream and detected its tracks - calling these any
                    # earlier is a silent no-op. This addon plays the
                    # server's direct stream/play URL (the whole original
                    # file, unmodified), so Kodi's own demuxer sees exactly
                    # the same embedded audio/subtitle tracks Jellyfin
                    # reported, in the same order - the Detail screen's
                    # picker indices (position within just that track
                    # type) line up with Kodi's own per-type stream index.
                    self._apply_stream_selection()
                    selection_applied = True
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

    def _apply_stream_selection(self):
        try:
            if self._audio_stream_index is not None:
                self.setAudioStream(self._audio_stream_index)
            if self._subtitle_stream_index is not None:
                self.setSubtitleStream(self._subtitle_stream_index)
                self.showSubtitles(True)
            else:
                # Explicit off, in case the source's own default subtitle
                # track would otherwise auto-enable itself - the Detail
                # screen's picker defaults to "None" unless a forced track
                # exists, and that choice should stick.
                self.showSubtitles(False)
        except Exception as exc:  # noqa: BLE001 - a failed track switch shouldn't stop playback
            xbmc.log(
                f"{LOG_PREFIX} Player: applying audio/subtitle selection for "
                f"{self._item_id!r} failed: {exc}",
                xbmc.LOGWARNING,
            )

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
                self._last_position_ticks = position_ticks
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
            # Only trust a live getTime() while Kodi still considers itself
            # playing - onPlayBackStopped/onPlayBackEnded fire before the
            # player is torn down, but by the time this runs isPlaying() is
            # often already False and getTime() raises, which used to fall
            # back to 0 and wipe the resume position server-side. The last
            # position seen by the progress-report loop is a much better
            # fallback than "from the beginning".
            if self.isPlaying():
                self._last_position_ticks = int(self.getTime() * 10_000_000)
        except Exception:  # noqa: BLE001 - player may already be torn down
            pass
        position_ticks = self._last_position_ticks
        playback.report_playback_stopped(
            self.client, self._item_id, self._play_session_id, position_ticks
        )
        # Reporting playback stopped is what makes Jellyfin update watched
        # state (played flag, resume position) server-side - any cached
        # browse listing's UserData is now potentially stale.
        library.clear_browse_cache()


def play_item(client, item_id, item_type=None, resume_ticks=0,
              audio_stream_index=None, subtitle_stream_index=None):
    player = JellyfinPlayer(client)
    player.play_item(
        item_id, item_type=item_type, resume_ticks=resume_ticks,
        audio_stream_index=audio_stream_index, subtitle_stream_index=subtitle_stream_index,
    )


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
