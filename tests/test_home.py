"""Tests for HomeWindow's hub-row population, in particular the Recently
Added Music row added alongside the existing Movies/TV rows.

onInit() only starts a background thread (_load() does the actual fetching
and control population) so a slow/large library doesn't block the GUI
thread - these tests call _load() directly to exercise that logic
synchronously/deterministically rather than racing a real thread.
"""

import threading

import xbmcaddon

import lib.windows.home as home_mod


def _make_window(client, monkeypatch, hide_playlists_setting=None):
    # home.py's ADDON is a single module-level instance shared across the
    # whole test session - give every test its own fresh stub so a
    # setSetting() call in one test can't leak into another's assertions.
    addon = xbmcaddon.Addon()
    if hide_playlists_setting is not None:
        addon.setSetting(home_mod.HIDE_PLAYLISTS_SETTING, hide_playlists_setting)
    monkeypatch.setattr(home_mod, "ADDON", addon)
    window = home_mod.HomeWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client)
    return window


# -- _visible_library_views: hide Playlists, Movies/TV/Music order ---------

def test_visible_library_views_hides_playlists():
    views = [
        {"Name": "Movies", "CollectionType": "movies"},
        {"Name": "Playlists", "CollectionType": "playlists"},
        {"Name": "Serien", "CollectionType": "tvshows"},
    ]
    names = [v["Name"] for v in home_mod._visible_library_views(views)]
    assert "Playlists" not in names
    assert names == ["Movies", "Serien"]


def test_visible_library_views_places_music_after_tvshows():
    views = [
        {"Name": "Musik", "CollectionType": "music"},
        {"Name": "Filme", "CollectionType": "movies"},
        {"Name": "Serien", "CollectionType": "tvshows"},
    ]
    names = [v["Name"] for v in home_mod._visible_library_views(views)]
    assert names == ["Filme", "Serien", "Musik"]


def test_visible_library_views_keeps_unknown_types_after_known_ones_in_order():
    views = [
        {"Name": "Books", "CollectionType": "books"},
        {"Name": "Filme", "CollectionType": "movies"},
        {"Name": "Homevideos", "CollectionType": "homevideos"},
    ]
    names = [v["Name"] for v in home_mod._visible_library_views(views)]
    assert names == ["Filme", "Books", "Homevideos"]


def test_home_libraries_row_excludes_playlists_and_orders_music_last(client, monkeypatch):
    views = [
        {"Id": "lib-movies", "Name": "Filme", "CollectionType": "movies"},
        {"Id": "lib-music", "Name": "Musik", "CollectionType": "music"},
        {"Id": "lib-playlists", "Name": "Playlists", "CollectionType": "playlists"},
        {"Id": "lib-tv", "Name": "Serien", "CollectionType": "tvshows"},
    ]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])

    window = _make_window(client, monkeypatch)
    window._load()

    libraries_row = window.getControl(home_mod.CTRL_LIBRARIES)
    assert [li.getLabel() for li in libraries_row.items] == ["Filme", "Serien", "Musik"]


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

    window = _make_window(client, monkeypatch)
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

    window = _make_window(client, monkeypatch)
    window._load()

    assert window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC).items == []


def test_load_hides_the_loading_indicator_once_everything_has_fetched(client, monkeypatch):
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])

    window = _make_window(client, monkeypatch)
    assert window.getControl(home_mod.CTRL_LOADING).visible is True

    window._load()

    assert window.getControl(home_mod.CTRL_LOADING).visible is False


def test_load_leaves_the_loading_indicator_alone_if_window_already_closed(client, monkeypatch):
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])

    window = _make_window(client, monkeypatch)
    window.closed_event.set()

    window._load()

    assert window.getControl(home_mod.CTRL_LOADING).visible is True


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

    window = _make_window(client, monkeypatch)
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

    window = _make_window(client, monkeypatch)
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

    window = _make_window(client, monkeypatch)
    window._load()

    assert window.result is None  # nothing closed it - this is just the initial state
    assert not window.closed
    assert window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC).items == []
    movies_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MOVIES)
    assert [li.getLabel() for li in movies_row.items] == ["Alien"]


# -- Playlists show/hide toggle ---------------------------------------------

def _views_with_playlists():
    return [
        {"Id": "lib-movies", "Name": "Filme", "CollectionType": "movies"},
        {"Id": "lib-playlists", "Name": "Playlists", "CollectionType": "playlists"},
    ]


def test_hide_playlists_defaults_to_true_when_setting_unset(client, monkeypatch):
    window = _make_window(client, monkeypatch)
    assert window.hide_playlists is True


def test_hide_playlists_reads_persisted_setting(client, monkeypatch):
    window = _make_window(client, monkeypatch, hide_playlists_setting="false")
    assert window.hide_playlists is False


def test_playlists_toggle_button_label_reflects_default_hidden_state(client, monkeypatch):
    window = _make_window(client, monkeypatch)
    window.onInit()
    assert window.getControl(home_mod.CTRL_PLAYLISTS_TOGGLE).getLabel() == "Show Playlists"


def test_clicking_toggle_reveals_playlists_and_persists_setting(client, monkeypatch):
    views = _views_with_playlists()
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])

    window = _make_window(client, monkeypatch)
    window._load()
    assert [li.getLabel() for li in window.getControl(home_mod.CTRL_LIBRARIES).items] == ["Filme"]

    window.handle_click(home_mod.CTRL_PLAYLISTS_TOGGLE)

    assert window.hide_playlists is False
    assert home_mod.ADDON.getSetting(home_mod.HIDE_PLAYLISTS_SETTING) == "false"
    assert window.getControl(home_mod.CTRL_PLAYLISTS_TOGGLE).getLabel() == "Hide Playlists"
    labels = [li.getLabel() for li in window.getControl(home_mod.CTRL_LIBRARIES).items]
    assert labels == ["Filme", "Playlists"]


def test_clicking_toggle_again_hides_playlists_again(client, monkeypatch):
    views = _views_with_playlists()
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])

    window = _make_window(client, monkeypatch, hide_playlists_setting="false")
    window._load()

    window.handle_click(home_mod.CTRL_PLAYLISTS_TOGGLE)

    assert window.hide_playlists is True
    assert home_mod.ADDON.getSetting(home_mod.HIDE_PLAYLISTS_SETTING) == "true"
    assert window.getControl(home_mod.CTRL_PLAYLISTS_TOGGLE).getLabel() == "Show Playlists"
    labels = [li.getLabel() for li in window.getControl(home_mod.CTRL_LIBRARIES).items]
    assert labels == ["Filme"]


def test_clicking_toggle_before_load_is_a_no_op(client, monkeypatch):
    window = _make_window(client, monkeypatch)
    assert window.views is None

    window.handle_click(home_mod.CTRL_PLAYLISTS_TOGGLE)

    assert window.hide_playlists is True
