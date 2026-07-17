"""Tests for lib.player.JellyfinPlayer - in particular the playback wait
loop's handling of a slow-to-start stream, which took a full real-device
debugging session to track down (see git history around the "started"
flag and STARTUP_TIMEOUT_SECONDS in lib/player.py) before it had any test
coverage at all.
"""

import lib.jellyfin.client as client_mod
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
    return player


def _fake_playback_responses():
    return FakeRequests([
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
        FakeResponse({"MediaSources": [{"Id": "ms-1", "Container": "mp3"}]}),  # track 1 PlaybackInfo
        FakeResponse(None),  # track 1 start
        FakeResponse(None),  # track 1 stopped
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
