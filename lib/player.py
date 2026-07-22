"""Playback: resolves a stream via PlaybackInfo, plays it with xbmc.Player,
and reports position back to Jellyfin so watched-state/resume stays in sync
with other Jellyfin clients. Uses Kodi's own native video OSD/controls
during playback (pause, seek, stop, audio/subtitle selection) rather than a
custom seek/scrub UI - an earlier custom seek dialog was removed after
repeated real-device testing showed it could leave the whole OSD
unresponsive to input (see git history for lib/windows/seekdialog.py if
reviving the idea). The one deliberate exception is
lib.windows.next_episode_overlay.NextEpisodeOverlay: a small, non-modal,
corner-positioned "play next episode" prompt shown in an Episode's closing
minutes - much simpler than the reverted seek dialog (two buttons, no
scrubbing) and verified on a real device not to reproduce that failure.
"""

import threading

import xbmc
import xbmcaddon
import xbmcgui

from lib.jellyfin import playback, library
from lib.windows.kodigui import LOG_PREFIX
from lib.windows.next_episode_overlay import NextEpisodeOverlay

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo("path")
PROGRESS_REPORT_INTERVAL_SECONDS = 10
STARTUP_TIMEOUT_SECONDS = 30
# How much runtime must remain before the "play next episode" overlay
# offers skipping ahead - roughly the closing minutes (end credits/outro)
# of a typical TV episode, per the feature request this implements.
NEXT_EPISODE_OVERLAY_REMAINING_SECONDS = 150


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
        self._item_type = None
        self._overlay = None
        self._overlay_attempted = False
        self._overlay_next_episode_id = None
        self._pending_next_episode = None
        self.skip_target_item_id = None

    def play_item(self, item_id, item_type=None, resume_ticks=0,
                  audio_stream_index=None, subtitle_stream_index=None):
        """Returns "ended" (played to completion - including via the "play
        next episode" overlay's Play Now/countdown, since from the caller's
        perspective this item is done either way), "stopped" (user backed
        out or explicitly stopped early), or "error" (playback never
        started, or Kodi reported a playback error) - lib.player.play_queue()
        and the module-level play_item() below use this to decide whether
        to auto-advance to the next item."""
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
        self._item_type = item_type
        self._play_session_id = play_session_id
        self._reported_stop = False
        self._last_position_ticks = resume_ticks or 0
        self._end_reason = "ended"
        self._audio_stream_index = audio_stream_index
        self._subtitle_stream_index = subtitle_stream_index
        self._overlay = None
        self._overlay_attempted = False
        self._overlay_next_episode_id = None
        self._pending_next_episode = None
        self.skip_target_item_id = None

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
            if started and self._item_type == "Episode":
                if self._overlay is None and not self._overlay_attempted:
                    self._maybe_offer_next_episode(item_id)
                elif self._overlay is None and self._pending_next_episode is not None:
                    # The background lookup thread found a next episode -
                    # show the overlay here, on this loop's own thread,
                    # rather than from the lookup thread itself: a
                    # WindowXMLDialog created off the main script thread
                    # rendered fine on a real device but never received a
                    # single click (confirmed via JSON-RPC-driven input
                    # testing) - showing it from here fixed that.
                    self._overlay_next_episode_id = self._pending_next_episode.get("Id")
                    self._overlay = NextEpisodeOverlay.show_overlay(
                        ADDON_PATH, client=self.client, next_item=self._pending_next_episode,
                    )
                    self._pending_next_episode = None
                elif self._overlay is not None and self._overlay.closed_event.is_set():
                    overlay_result = self._overlay.result
                    self._overlay = None
                    if overlay_result and overlay_result.get("action") == "play":
                        self.skip_target_item_id = self._overlay_next_episode_id
                        self._end_reason = "ended"
                        if self.isPlaying():
                            self.stop()
                        break
        if self._overlay is not None:
            # Playback ended (naturally, by error, or via the Home-active
            # escape route above) before the user reacted to the overlay -
            # tear it down rather than leaving it on screen with nothing
            # left playing underneath it.
            self._overlay.close()
            self._overlay = None
        self._finish()
        return self._end_reason

    def _maybe_offer_next_episode(self, item_id):
        """Kicks off the background lookup for the "play next episode"
        overlay once playback has entered its closing
        NEXT_EPISODE_OVERLAY_REMAINING_SECONDS - never re-attempted after
        the first try (self._overlay_attempted), whether or not a next
        episode actually turned up, so a missing next episode or a lookup
        failure doesn't retry every second for the rest of playback. The
        overlay itself is shown later, back on this same wait loop's own
        thread once the lookup finishes - see play_item()'s handling of
        self._pending_next_episode."""
        try:
            total_time = self.getTotalTime()
        except Exception:  # noqa: BLE001 - player may not be fully ready yet
            return
        if total_time <= 0:
            return
        remaining = total_time - self.getTime()
        if not (0 < remaining <= NEXT_EPISODE_OVERLAY_REMAINING_SECONDS):
            return
        self._overlay_attempted = True
        threading.Thread(
            target=self._look_up_next_episode, args=(item_id,), daemon=True,
        ).start()

    def _look_up_next_episode(self, item_id):
        # Runs on its own thread (network lookup) so the 1s wait loop above
        # keeps ticking (progress reporting, abort/Home-active checks)
        # rather than stalling on a slow server for however long the
        # request timeout allows. Only stashes the result for the wait
        # loop to actually show - see the "pending_next_episode" handling
        # in play_item() for why the overlay itself isn't shown here.
        try:
            next_episode = library.get_next_episode_in_season(self.client, item_id)
        except Exception:  # noqa: BLE001 - no overlay is better than a crash this close to the end
            next_episode = None
        if not next_episode or self._stop_event.is_set():
            return
        self._pending_next_episode = next_episode

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
    """Returns (status, last_item_id): status is the same "ended"/"stopped"/
    "error" JellyfinPlayer.play_item() returns, for whichever item was
    actually last played. last_item_id can differ from the requested
    item_id: choosing "Play Next Episode" on the in-playback overlay skips
    the rest of the current episode and chains straight into the next one
    (recursively, in case that one's overlay gets used too) without
    returning control to the caller - lib/main.py uses last_item_id, not
    the original item_id, to decide which episode its own post-playback
    "Up Next" prompt should offer."""
    player = JellyfinPlayer(client)
    status = player.play_item(
        item_id, item_type=item_type, resume_ticks=resume_ticks,
        audio_stream_index=audio_stream_index, subtitle_stream_index=subtitle_stream_index,
    )
    if status == "ended" and player.skip_target_item_id:
        return play_item(client, player.skip_target_item_id, item_type="Episode")
    return status, item_id


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
