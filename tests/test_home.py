"""Tests for HomeWindow's hub-row population, in particular the Recently
Added Music row added alongside the existing Movies/TV rows.

onInit() only starts a background thread (_load() does the actual fetching
and control population) so a slow/large library doesn't block the GUI
thread - these tests call _load() directly to exercise that logic
synchronously/deterministically rather than racing a real thread.
"""

import threading

import lib.windows.home as home_mod


def _make_window(client):
    window = home_mod.HomeWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client)
    return window


def test_recently_added_music_populated_from_music_library(client, monkeypatch):
    views = [
        {"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"},
        {"Id": "lib-music", "Name": "Music", "CollectionType": "music"},
    ]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])

    def fake_get_latest(c, parent_id=None, limit=10):
        if parent_id == "lib-music":
            return [{"Id": "album-1", "Name": "OK Computer", "Type": "MusicAlbum"}]
        return []

    monkeypatch.setattr(home_mod.library, "get_latest", fake_get_latest)

    window = _make_window(client)
    window._load()

    music_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC)
    assert [li.getLabel() for li in music_row.items] == ["OK Computer"]
    assert music_row.items[0].getProperty("jellyfin_id") == "album-1"
    assert music_row.items[0].getProperty("jellyfin_type") == "MusicAlbum"

    # Movies row still only pulls from the movies-CollectionType view.
    movies_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MOVIES)
    assert movies_row.items == []


def test_recently_added_music_empty_when_no_music_library(client, monkeypatch):
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [
        {"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"},
    ])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])

    window = _make_window(client)
    window._load()

    assert window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC).items == []


def test_oninit_loads_in_a_background_thread_not_the_caller(client, monkeypatch):
    """The whole point of the fix: onInit() must return immediately even if
    the fetch is slow, rather than blocking Kodi's GUI thread for its
    duration (which is what produced the "Read timed out"/frozen-UI report
    against a real, large Music library)."""
    started = threading.Event()
    finished = threading.Event()

    def slow_get_views(c):
        started.set()
        assert finished.wait(2), "background thread never called get_views"
        return []

    monkeypatch.setattr(home_mod.library, "get_views", slow_get_views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])

    window = _make_window(client)
    window.onInit()  # must return without waiting for slow_get_views

    assert started.wait(2)
    finished.set()


def test_load_does_not_touch_controls_after_window_closed(client, monkeypatch):
    """If the user backs out (WindowMixin.close() sets closed_event) while
    _load() is still waiting on the network, it must not go on to populate
    controls (or worse, overwrite self.result/close an already-closing
    window) once the response finally arrives."""
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])

    def fail_if_called(*a, **k):
        raise AssertionError("must not populate after the window was closed")

    monkeypatch.setattr(home_mod.library, "get_resume", fail_if_called)

    window = _make_window(client)
    window.closed_event.set()  # simulate Back already having fired

    window._load()  # must return quietly, not raise or touch self.result


def test_a_slow_or_broken_hub_row_does_not_blank_the_others(client, monkeypatch):
    """Real-world case that exposed this: get_resume/get_next_up/latest
    movies/latest tvshows all succeeded quickly, but latest music timed out
    - previously that one exception, from inside a single shared try/except,
    aborted the whole Home screen (closing it with result=None) even though
    four of the five rows had already loaded fine."""
    views = [
        {"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"},
        {"Id": "lib-music", "Name": "Music", "CollectionType": "music"},
    ]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])

    def flaky_get_latest(c, parent_id=None, limit=10):
        if parent_id == "lib-music":
            raise RuntimeError("Read timed out")
        return [{"Id": "movie-1", "Name": "Alien", "Type": "Movie"}] if parent_id == "lib-movies" else []

    monkeypatch.setattr(home_mod.library, "get_latest", flaky_get_latest)

    window = _make_window(client)
    window._load()

    assert window.result is None  # nothing closed it - this is just the initial state
    assert not window.closed
    assert window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC).items == []
    movies_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MOVIES)
    assert [li.getLabel() for li in movies_row.items] == ["Alien"]
