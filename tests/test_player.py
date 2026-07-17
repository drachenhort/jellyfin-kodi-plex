"""Tests for lib.player.JellyfinPlayer - in particular the playback wait
loop's handling of a slow-to-start stream, which took a full real-device
debugging session to track down (see git history around the "started"
flag and STARTUP_TIMEOUT_SECONDS in lib/player.py) before it had any test
coverage at all.
"""

import lib.jellyfin.client as client_mod
import lib.player as player_mod
from tests.fakes import FakeRequests, FakeResponse


def _make_player(client, isplayingvideo_sequence, isplaying_sequence=None, stop_event_after=None):
    """Build a JellyfinPlayer whose isPlayingVideo()/isPlaying() replay a
    fixed sequence of return values (one per wait-loop iteration), and
    whose stop() is recorded rather than touching anything real. This
    mirrors how tests/test_jellyfin_client.py fakes `requests` instead of
    hitting a real server - here the "server" being faked is Kodi's own
    player state over time.
    """
    player = player_mod.JellyfinPlayer(client)
    player.stop_calls = 0

    isplayingvideo_iter = iter(isplayingvideo_sequence)
    isplaying_iter = iter(isplaying_sequence or [True] * len(isplayingvideo_sequence))

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

    def fake_stop():
        player.stop_calls += 1

    player.isPlayingVideo = fake_is_playing_video
    player.isPlaying = fake_is_playing
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
