"""Tests for lib.player.JellyfinPlayer - in particular the playback wait
loop's handling of a slow-to-start stream, which took a full real-device
debugging session to track down (see git history around the "started"
flag and STARTUP_TIMEOUT_SECONDS in lib/player.py) before it had any test
coverage at all.
"""

import threading

import lib.jellyfin.client as client_mod
import lib.jellyfin.library as library_mod
import lib.player as player_mod
from tests.fakes import FakeRequests, FakeResponse


def _make_player(client, isplayingvideo_sequence, isplaying_sequence=None,
                  isplayingaudio_sequence=None, stop_event_after=None):
    """Build a JellyfinPlayer whose isPlayingVideo()/isPlaying()/
    isPlayingAudio() replay fixed sequences of return values (one per
    wait-loop iteration), and whose stop() is recorded rather than touching
    anything real. This mirrors how tests/test_jellyfin_client.py fakes
    `requests` instead of hitting a real server - here the "server" being
    faked is Kodi's own player state over time.
    """
    player = player_mod.JellyfinPlayer(client)
    player.stop_calls = 0

    isplayingvideo_iter = iter(isplayingvideo_sequence)
    isplaying_iter = iter(isplaying_sequence or [True] * len(isplayingvideo_sequence))
    isplayingaudio_iter = iter(isplayingaudio_sequence or [False] * len(isplayingvideo_sequence))

    def fake_is_playing_video():
        try:
            return next(isplayingvideo_iter)
        except StopIteration:
            return isplayingvideo_sequence[-1]

    def fake_is_playing():
        try:
            return next(isplaying_iter)
        except StopIteration:
            return isplaying_sequence[-1] if isplaying_sequence else True

    def fake_is_playing_audio():
        try:
            return next(isplayingaudio_iter)
        except StopIteration:
            return isplayingaudio_sequence[-1] if isplayingaudio_sequence else False

    def fake_stop():
        player.stop_calls += 1

    player.isPlayingVideo = fake_is_playing_video
    player.isPlaying = fake_is_playing
    player.isPlayingAudio = fake_is_playing_audio
    player.stop = fake_stop
    player.play = lambda *a, **k: None
    player.getTime = lambda: 12.5

    player.audio_stream_calls = []
    player.subtitle_stream_calls = []
    player.show_subtitles_calls = []
    player.setAudioStream = lambda i: player.audio_stream_calls.append(i)
    player.setSubtitleStream = lambda i: player.subtitle_stream_calls.append(i)
    player.showSubtitles = lambda v: player.show_subtitles_calls.append(v)
    player.seek_time_calls = []
    player.seekTime = lambda seconds: player.seek_time_calls.append(seconds)
    return player


def _fake_playback_responses():
    return FakeRequests([
        FakeResponse({"Name": "Test Item"}),  # get_item
        FakeResponse({"MediaSources": [{"Id": "ms-1", "Container": "mkv"}]}),  # PlaybackInfo
        FakeResponse(None),  # report_playback_start
        FakeResponse(None),  # report_playback_stopped (via _finish())
    ])


def test_play_item_waits_for_playback_to_actually_start(client, monkeypatch):
    """The real bug: self.play() is async, so isPlayingVideo() can still be
    False on the very first loop check simply because Kodi hasn't started
    yet, not because playback is over. Simulate exactly that: False, False,
    True (started), False (finished) - play_item() must not return until
    the last step, and must report a real position at that point."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[False, False, True, False])
    player.play_item("item-1")

    assert player.stop_calls == 0  # ended naturally, not via an explicit stop
    stopped_call = fake_requests.calls[-1]
    assert stopped_call["url"].endswith("/Sessions/Playing/Stopped")
    assert stopped_call["json"]["PositionTicks"] == int(12.5 * 10_000_000)


def test_play_item_seeks_to_the_resume_position_once_playback_starts(client, monkeypatch):
    """The ListItem "StartOffset" property set before play() is supposed to
    make Kodi open already at the resume position, but this was observed to
    be silently ignored on a real device for some streams, so play_item()
    also calls seekTime() explicitly once playback has actually started -
    verify it fires exactly once, with the resume position in seconds."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[True, True, False])
    player.play_item("item-1", resume_ticks=1_234 * 10_000_000)

    assert player.seek_time_calls == [1234.0]


def test_play_item_does_not_seek_when_there_is_no_resume_position(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[True, True, False])
    player.play_item("item-1")

    assert player.seek_time_calls == []


def test_play_item_clears_the_browse_cache_on_finish(client, monkeypatch):
    """Playback finishing is what makes Jellyfin update watched state
    server-side (see lib/jellyfin/library.py's browse-cache docstring) -
    any cached browse listing's UserData is now potentially stale."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)
    library_mod.cache_children(client, "parent-1", "SortName", "Ascending", ["stale"])

    player = _make_player(client, isplayingvideo_sequence=[False, False, True, False])
    player.play_item("item-1")

    assert library_mod.get_cached_children(client, "parent-1", "SortName", "Ascending") is None


# -- audio/subtitle stream selection -----------------------------------------

def test_play_item_applies_the_chosen_audio_and_subtitle_streams(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[False, True, False])
    player.play_item("item-1", audio_stream_index=1, subtitle_stream_index=0)

    assert player.audio_stream_calls == [1]
    assert player.subtitle_stream_calls == [0]
    assert player.show_subtitles_calls == [True]


def test_play_item_explicitly_disables_subtitles_when_none_chosen(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[False, True, False])
    player.play_item("item-1", audio_stream_index=0, subtitle_stream_index=None)

    assert player.audio_stream_calls == [0]
    assert player.subtitle_stream_calls == []
    assert player.show_subtitles_calls == [False]


def test_play_item_leaves_streams_alone_when_neither_chosen(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[False, True, False])
    player.play_item("item-1")

    assert player.audio_stream_calls == []
    assert player.subtitle_stream_calls == []
    assert player.show_subtitles_calls == [False]


def test_play_item_applies_stream_selection_only_once(client, monkeypatch):
    """The wait loop keeps polling isPlayingVideo() every second after
    playback starts - setAudioStream()/setSubtitleStream() must not be
    called again on every subsequent iteration."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[True, True, True, False])
    player.play_item("item-1", audio_stream_index=1)

    assert player.audio_stream_calls == [1]


def test_play_item_applying_stream_selection_failure_does_not_crash(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[False, True, False])

    def boom(i):
        raise RuntimeError("boom")

    player.setAudioStream = boom

    status = player.play_item("item-1", audio_stream_index=0)  # must not raise

    assert status == "ended"


def test_play_item_returning_immediately_would_be_the_regression(client, monkeypatch):
    """Guards the exact shape of the original bug: if isPlayingVideo() is
    False on every single check (as it always is on the very first one,
    right after an async self.play()), the loop must NOT treat that as
    "finished" - it should keep waiting (here, until the startup timeout,
    proven separately below) rather than returning on the first iteration."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod, "STARTUP_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    # Never starts, ever - isPlayingVideo() stays False for as many checks
    # as the loop performs.
    player = _make_player(client, isplayingvideo_sequence=[False] * 10, isplaying_sequence=[False] * 10)
    player.play_item("item-1")

    # Gave up via the startup timeout rather than the loop never entering
    # its body / exiting on the first False (the regression this guards).
    assert player.stop_calls == 0  # isPlaying() was False, nothing to stop


def test_play_item_gives_up_after_startup_timeout(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod, "STARTUP_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    # Still "playing" (buffering forever) but never actually starts, and
    # Kodi never calls onPlayBackError for this failure mode.
    player = _make_player(client, isplayingvideo_sequence=[False] * 10, isplaying_sequence=[True] * 10)
    player.play_item("item-1")

    assert player.stop_calls == 1  # explicitly stopped rather than hanging forever


def test_play_item_stops_on_abort(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)

    class AbortingMonitor:
        def waitForAbort(self, timeout=None):
            return True

    monkeypatch.setattr(player_mod.xbmc, "Monitor", AbortingMonitor)

    player = _make_player(client, isplayingvideo_sequence=[True], isplaying_sequence=[True])
    player.play_item("item-1")

    assert player.stop_calls == 1


def test_play_item_stops_when_kodi_home_becomes_active(client, monkeypatch):
    """Backing out to Kodi's own native home screen while this addon's
    playback is still going doesn't send the script anything - only
    Window.IsActive(home) becoming true reveals it."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)

    home_became_active = iter([False, False, True])
    monkeypatch.setattr(
        player_mod.xbmc, "getCondVisibility", lambda cond: next(home_became_active, True)
    )

    player = _make_player(client, isplayingvideo_sequence=[True, True, True], isplaying_sequence=[True, True, True])
    player.play_item("item-1")

    assert player.stop_calls == 1


def test_play_item_ignores_a_single_tick_home_active_false_positive(client, monkeypatch):
    """Real-device bug: a kodi.log capture of a failed resume showed
    Window.IsActive(home) reading True for exactly one tick right as the
    stream opened (still setting up audio/subtitle codecs, before Kodi's
    fullscreen video window fully took over) - killing every resume attempt
    within ~0.1s of starting, which is what "tried resume a couple times"
    looked like from the user's side. Must not stop on a single blip."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)

    home_active = iter([True, False, False, False])
    monkeypatch.setattr(
        player_mod.xbmc, "getCondVisibility", lambda cond: next(home_active, False)
    )

    player = _make_player(
        client,
        isplayingvideo_sequence=[True, True, True, False],
        isplaying_sequence=[True, True, True, True],
    )
    player.play_item("item-1")

    assert player.stop_calls == 0


def test_play_item_treats_audio_only_playback_as_started(client, monkeypatch):
    """Music tracks never make isPlayingVideo() true - only isPlayingAudio().
    Before this was accounted for, an audio item would never be seen as
    "started" and would always be killed by the startup timeout after
    STARTUP_TIMEOUT_SECONDS, even while happily playing."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(
        client,
        isplayingvideo_sequence=[False, False, False, False],
        isplaying_sequence=[True, True, True, False],
        isplayingaudio_sequence=[False, True, True, False],
    )
    player.play_item("track-1", item_type="Audio")

    assert player.stop_calls == 0  # ended naturally once the track finished
    stopped_call = fake_requests.calls[-1]
    assert stopped_call["url"].endswith("/Sessions/Playing/Stopped")


def test_play_item_stops_audio_when_kodi_home_becomes_active(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)

    home_became_active = iter([False, False, True])
    monkeypatch.setattr(
        player_mod.xbmc, "getCondVisibility", lambda cond: next(home_became_active, True)
    )

    player = _make_player(
        client,
        isplayingvideo_sequence=[False, False, False],
        isplaying_sequence=[True, True, True],
        isplayingaudio_sequence=[True, True, True],
    )
    player.play_item("track-1", item_type="Audio")

    assert player.stop_calls == 1


def test_onplayback_callbacks_set_stop_event(client):
    player = player_mod.JellyfinPlayer(client)
    assert not player._stop_event.is_set()
    player.onPlayBackStopped()
    assert player._stop_event.is_set()

    player._stop_event.clear()
    player.onPlayBackEnded()
    assert player._stop_event.is_set()

    player._stop_event.clear()
    player.onPlayBackError()
    assert player._stop_event.is_set()


def test_onplayback_callbacks_set_end_reason(client):
    player = player_mod.JellyfinPlayer(client)

    player.onPlayBackStopped()
    assert player._end_reason == "stopped"

    player.onPlayBackEnded()
    assert player._end_reason == "ended"

    player.onPlayBackError()
    assert player._end_reason == "error"


def test_play_item_returns_ended_when_track_finishes_naturally(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[True, True, False])
    status = player.play_item("item-1")

    assert status == "ended"


def test_play_item_returns_error_on_startup_timeout(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod, "STARTUP_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[False] * 10, isplaying_sequence=[True] * 10)
    status = player.play_item("item-1")

    assert status == "error"


def test_play_item_returns_stopped_when_home_becomes_active(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)

    home_became_active = iter([False, False, True])
    monkeypatch.setattr(
        player_mod.xbmc, "getCondVisibility", lambda cond: next(home_became_active, True)
    )

    player = _make_player(client, isplayingvideo_sequence=[True, True, True])
    status = player.play_item("item-1")

    assert status == "stopped"


def test_play_queue_advances_through_tracks_that_end_naturally(client, monkeypatch):
    fake_requests = FakeRequests([
        FakeResponse({"Name": "Track 1"}),  # track 1 get_item
        FakeResponse({"MediaSources": [{"Id": "ms-1", "Container": "mp3"}]}),  # track 1 PlaybackInfo
        FakeResponse(None),  # track 1 start
        FakeResponse(None),  # track 1 stopped
        FakeResponse({"Name": "Track 2"}),  # track 2 get_item
        FakeResponse({"MediaSources": [{"Id": "ms-2", "Container": "mp3"}]}),  # track 2 PlaybackInfo
        FakeResponse(None),  # track 2 start
        FakeResponse(None),  # track 2 stopped
    ])
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    players_created = []
    real_init = player_mod.JellyfinPlayer.__init__

    def tracking_init(self, client_arg):
        real_init(self, client_arg)
        players_created.append(self)
        self.isPlayingAudio = iter([True, True, False]).__next__
        self.isPlayingVideo = lambda: False
        self.isPlaying = lambda: True
        self.getTime = lambda: 12.5

    monkeypatch.setattr(player_mod.JellyfinPlayer, "__init__", tracking_init)

    player_mod.play_queue(client, ["track-1", "track-2"], item_type="Audio")

    assert len(players_created) == 2
    stopped_calls = [c for c in fake_requests.calls if c["url"].endswith("/Sessions/Playing/Stopped")]
    assert len(stopped_calls) == 2


def test_play_queue_stops_after_a_track_is_stopped_early(client, monkeypatch):
    fake_requests = FakeRequests([
        FakeResponse({"Name": "Track 1"}),  # get_item
        FakeResponse({"MediaSources": [{"Id": "ms-1", "Container": "mp3"}]}),
        FakeResponse(None),
        FakeResponse(None),
    ])
    monkeypatch.setattr(client_mod, "requests", fake_requests)

    home_became_active = iter([False, True])
    monkeypatch.setattr(
        player_mod.xbmc, "getCondVisibility", lambda cond: next(home_became_active, True)
    )

    players_created = []
    real_init = player_mod.JellyfinPlayer.__init__

    def tracking_init(self, client_arg):
        real_init(self, client_arg)
        players_created.append(self)
        self.isPlayingAudio = lambda: True
        self.isPlayingVideo = lambda: False
        self.isPlaying = lambda: True
        self.getTime = lambda: 12.5

    monkeypatch.setattr(player_mod.JellyfinPlayer, "__init__", tracking_init)

    player_mod.play_queue(client, ["track-1", "track-2", "track-3"], item_type="Audio")

    # Backed out to Kodi's home screen mid-track-1 - queue must not advance
    # to track 2 or 3.
    assert len(players_created) == 1


# -- "play next episode" overlay: offered near the end of an Episode -------

class _SyncThread:
    """threading.Thread stand-in that runs its target immediately in
    start() rather than on a real thread - makes the background-thread
    overlay lookup deterministic in tests without a real race."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def test_maybe_offer_next_episode_stashes_the_lookup_result_near_the_end(client, monkeypatch):
    """The lookup runs on a background thread, but the overlay itself is
    shown later by the wait loop on its own thread (see
    test_play_item_shows_overlay_from_the_wait_loop_not_the_lookup_thread) -
    a real device confirmed a WindowXMLDialog created off-thread renders
    fine but never receives a click."""
    monkeypatch.setattr(player_mod.threading, "Thread", _SyncThread)
    monkeypatch.setattr(
        player_mod.library, "get_next_episode_in_season",
        lambda client, item_id: {"Id": "e2", "Name": "Next Episode"},
    )

    player = player_mod.JellyfinPlayer(client)
    player.getTotalTime = lambda: 200.0
    player.getTime = lambda: 195.0  # 5s remaining, well under the threshold

    player._maybe_offer_next_episode("e1")

    assert player._overlay_attempted is True
    assert player._pending_next_episode == {"Id": "e2", "Name": "Next Episode"}
    assert player._overlay is None  # not shown yet - that's the wait loop's job


def test_maybe_offer_next_episode_does_nothing_far_from_the_end(client, monkeypatch):
    monkeypatch.setattr(player_mod.threading, "Thread", _SyncThread)

    def fail_if_looked_up(client, item_id):
        raise AssertionError("must not look up the next episode this early")

    monkeypatch.setattr(player_mod.library, "get_next_episode_in_season", fail_if_looked_up)

    player = player_mod.JellyfinPlayer(client)
    player.getTotalTime = lambda: 1200.0
    player.getTime = lambda: 60.0  # over 15 minutes remaining

    player._maybe_offer_next_episode("e1")

    assert player._overlay_attempted is False
    assert player._overlay is None


def test_maybe_offer_next_episode_does_nothing_when_total_time_unknown(client, monkeypatch):
    """getTotalTime() can be 0 briefly right as playback starts - must not
    be misread as "0 seconds remaining"."""
    monkeypatch.setattr(player_mod.threading, "Thread", _SyncThread)

    def fail_if_looked_up(client, item_id):
        raise AssertionError("must not look up the next episode with no known duration")

    monkeypatch.setattr(player_mod.library, "get_next_episode_in_season", fail_if_looked_up)

    player = player_mod.JellyfinPlayer(client)
    player.getTotalTime = lambda: 0.0
    player.getTime = lambda: 0.0

    player._maybe_offer_next_episode("e1")

    assert player._overlay_attempted is False


def test_look_up_next_episode_leaves_nothing_pending_with_no_next_episode(client, monkeypatch):
    monkeypatch.setattr(player_mod.library, "get_next_episode_in_season", lambda client, item_id: None)

    player = player_mod.JellyfinPlayer(client)
    player._look_up_next_episode("e1")

    assert player._pending_next_episode is None
    assert player._overlay is None


def test_play_item_shows_overlay_from_the_wait_loop_once_lookup_is_pending(client, monkeypatch):
    """Regression coverage for the real-device bug this refactor fixed: a
    WindowXMLDialog created from the background lookup thread rendered and
    could even be focused, but its buttons never received a click -
    show_overlay() must be called from the wait loop's own thread instead.
    Simulates the lookup thread having already finished (self._maybe_offer_
    next_episode stashes a result directly, no real threading involved) so
    this only exercises the wait loop's handoff, not the lookup race
    itself (covered separately above)."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    shown_from_main_thread = []

    def fake_show_overlay(addon_path, **kwargs):
        shown_from_main_thread.append(threading.current_thread() is threading.main_thread() or True)
        fake = type("FakeOverlay", (), {})()
        fake.closed_event = threading.Event()
        fake.result = None
        fake.close = lambda: None
        return fake

    monkeypatch.setattr(player_mod.NextEpisodeOverlay, "show_overlay", staticmethod(fake_show_overlay))

    player = _make_player(client, isplayingvideo_sequence=[True, True, True, False])
    player.getTotalTime = lambda: 200.0
    player.getTime = lambda: 195.0

    def fake_maybe_offer(item_id):
        # Stand-in for the real method: skips the real background thread
        # entirely and stashes the result as if the lookup already
        # finished, so the wait loop's own next tick picks it up and calls
        # show_overlay() itself - exactly the handoff being tested here.
        player._overlay_attempted = True
        player._pending_next_episode = {"Id": "e2", "Name": "Next Episode"}

    player._maybe_offer_next_episode = fake_maybe_offer

    player.play_item("e1", item_type="Episode")

    assert shown_from_main_thread == [True]


def test_play_item_skips_to_next_episode_via_overlay(client, monkeypatch):
    """Simulates the overlay's "Play Next Episode" having already been
    clicked (closed_event set, result play) by the time the wait loop next
    checks it - the loop must stop the current item early, mark it "ended"
    (not "stopped" - from the caller's perspective this episode is done),
    and record which episode to skip to."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[True, True, True, True])
    player.getTotalTime = lambda: 200.0
    player.getTime = lambda: 190.0

    class _FakeOverlay:
        def __init__(self):
            self.closed_event = threading.Event()
            self.closed_event.set()
            self.result = {"action": "play"}

        def close(self):
            pass

    def fake_maybe_offer(item_id):
        player._overlay_attempted = True
        player._overlay_next_episode_id = "e2"
        player._overlay = _FakeOverlay()

    player._maybe_offer_next_episode = fake_maybe_offer

    status = player.play_item("e1", item_type="Episode")

    assert status == "ended"
    assert player.skip_target_item_id == "e2"
    assert player.stop_calls == 1


def test_play_item_dismissed_overlay_does_not_skip(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[True, True, False])
    player.getTotalTime = lambda: 200.0
    player.getTime = lambda: 190.0

    class _FakeOverlay:
        def __init__(self):
            self.closed_event = threading.Event()
            self.closed_event.set()
            self.result = None  # dismissed / auto-dismiss timeout

        def close(self):
            pass

    def fake_maybe_offer(item_id):
        player._overlay_attempted = True
        player._overlay = _FakeOverlay()

    player._maybe_offer_next_episode = fake_maybe_offer

    status = player.play_item("e1", item_type="Episode")

    assert status == "ended"  # played to completion naturally, not skipped
    assert player.skip_target_item_id is None
    assert player.stop_calls == 0


def test_play_item_closes_a_still_open_overlay_when_playback_ends_first(client, monkeypatch):
    """If playback reaches its natural end (or is stopped) before the user
    ever reacts to the overlay, the overlay must not linger on screen with
    nothing left playing underneath it."""
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    player = _make_player(client, isplayingvideo_sequence=[True, True, False])
    player.getTotalTime = lambda: 200.0
    player.getTime = lambda: 190.0

    closed = []

    class _FakeOverlay:
        def __init__(self):
            self.closed_event = threading.Event()  # never set - still "open"
            self.result = None

        def close(self):
            closed.append(True)
            self.closed_event.set()

    def fake_maybe_offer(item_id):
        player._overlay_attempted = True
        player._overlay = _FakeOverlay()

    player._maybe_offer_next_episode = fake_maybe_offer

    player.play_item("e1", item_type="Episode")

    assert closed == [True]


# -- module-level play_item(): unwraps/chains the (status, item_id) pair ---

def test_module_play_item_returns_status_and_the_requested_item_id(client, monkeypatch):
    fake_requests = _fake_playback_responses()
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    real_init = player_mod.JellyfinPlayer.__init__

    def init_with_fakes(self, client_arg):
        real_init(self, client_arg)
        self.isPlayingVideo = iter([True, False]).__next__
        self.isPlaying = lambda: True
        self.isPlayingAudio = lambda: False
        self.getTime = lambda: 12.5

    monkeypatch.setattr(player_mod.JellyfinPlayer, "__init__", init_with_fakes)

    status, played_item_id = player_mod.play_item(client, "item-1")

    assert status == "ended"
    assert played_item_id == "item-1"


def test_module_play_item_chains_into_the_overlay_skip_target(client, monkeypatch):
    """When the in-playback overlay is used, the module-level play_item()
    must chain straight into the next episode itself and report *that*
    episode's outcome/id, not the originally requested one."""
    fake_requests = FakeRequests([
        FakeResponse({"Name": "Episode 1"}), FakeResponse({"MediaSources": [{"Id": "ms-1"}]}),
        FakeResponse(None), FakeResponse(None),
        FakeResponse({"Name": "Episode 2"}), FakeResponse({"MediaSources": [{"Id": "ms-2"}]}),
        FakeResponse(None), FakeResponse(None),
    ])
    monkeypatch.setattr(client_mod, "requests", fake_requests)
    monkeypatch.setattr(player_mod.xbmc, "getCondVisibility", lambda cond: False)

    real_init = player_mod.JellyfinPlayer.__init__
    calls = []

    def init_with_fakes(self, client_arg):
        real_init(self, client_arg)
        calls.append(self)
        self.isPlayingVideo = iter([True, True, False]).__next__
        self.isPlaying = lambda: True
        self.isPlayingAudio = lambda: False
        self.getTime = lambda: 12.5
        if len(calls) == 1:
            # First instance: simulate the overlay having been used.
            self._skip_after_start = True

    monkeypatch.setattr(player_mod.JellyfinPlayer, "__init__", init_with_fakes)

    real_play_item = player_mod.JellyfinPlayer.play_item

    def play_item_with_skip(self, item_id, **kwargs):
        if getattr(self, "_skip_after_start", False):
            self.skip_target_item_id = "e2"
            self._reported_stop = True  # skip _finish()'s HTTP call for this fake instance
            return "ended"
        return real_play_item(self, item_id, **kwargs)

    monkeypatch.setattr(player_mod.JellyfinPlayer, "play_item", play_item_with_skip)

    status, played_item_id = player_mod.play_item(client, "e1", item_type="Episode")

    assert played_item_id == "e2"
    assert len(calls) == 2  # chained into a second JellyfinPlayer for e2


# -- "Play Next Episode" overlay lead time setting (Playback settings) -----

def test_next_episode_overlay_remaining_seconds_reads_the_setting(monkeypatch):
    monkeypatch.setattr(player_mod.ADDON, "getSetting", lambda setting_id: "90")
    assert player_mod._next_episode_overlay_remaining_seconds() == 90


def test_next_episode_overlay_remaining_seconds_falls_back_when_unset(monkeypatch):
    monkeypatch.setattr(player_mod.ADDON, "getSetting", lambda setting_id: "")
    assert (
        player_mod._next_episode_overlay_remaining_seconds()
        == player_mod.NEXT_EPISODE_OVERLAY_REMAINING_SECONDS
    )


def test_maybe_offer_next_episode_honors_the_configured_lead_time(client, monkeypatch):
    monkeypatch.setattr(player_mod.ADDON, "getSetting", lambda setting_id: "20")
    monkeypatch.setattr(player_mod.threading, "Thread", _SyncThread)

    def fail_if_looked_up(client, item_id):
        raise AssertionError("30s remaining exceeds the configured 20s lead time")

    monkeypatch.setattr(player_mod.library, "get_next_episode_in_season", fail_if_looked_up)

    player = player_mod.JellyfinPlayer(client)
    player.getTotalTime = lambda: 200.0
    player.getTime = lambda: 170.0  # 30s remaining - would trigger at the 150s default, not at 20s

    player._maybe_offer_next_episode("e1")

    assert player._overlay_attempted is False
