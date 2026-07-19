"""Tests for HomeWindow's hub-row population, in particular the Recently
Added Music row added alongside the existing Movies/TV rows.

onInit() only starts a background thread (_load() does the actual fetching
and control population) so a slow/large library doesn't block the GUI
thread - these tests call _load() directly to exercise that logic
synchronously/deterministically rather than racing a real thread.
"""

import re
import threading

import xbmcaddon

import lib.windows.home as home_mod


def _make_window(client, monkeypatch, hide_playlists_setting=None, select_control_id=None, select_item_id=None,
                  extra_settings=None):
    # home.py's ADDON is a single module-level instance shared across the
    # whole test session - give every test its own fresh stub so a
    # setSetting() call in one test can't leak into another's assertions.
    addon = xbmcaddon.Addon()
    if hide_playlists_setting is not None:
        addon.setSetting(home_mod.HIDE_PLAYLISTS_SETTING, hide_playlists_setting)
    for key, value in (extra_settings or {}).items():
        addon.setSetting(key, value)
    monkeypatch.setattr(home_mod, "ADDON", addon)
    window = home_mod.HomeWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client, select_control_id=select_control_id, select_item_id=select_item_id)
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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(client, monkeypatch)
    window._load()

    assert window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC).items == []


def test_recently_added_tv_lists_episodes_individually_not_grouped_by_series(client, monkeypatch):
    """Two episodes of the same show added recently must both show up as
    separate items, in newest-added order - not merged/deduplicated down to
    one tile per series."""
    views = [
        {"Id": "lib-tv", "Name": "TV Shows", "CollectionType": "tvshows"},
    ]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])

    def fake_get_latest_episodes(c, parent_id=None, limit=10):
        if parent_id == "lib-tv":
            return [
                {"Id": "ep-1", "Name": "S01E02", "Type": "Episode", "SeriesId": "series-1", "SeriesName": "Show A"},
                {"Id": "ep-2", "Name": "S01E01", "Type": "Episode", "SeriesId": "series-1", "SeriesName": "Show A"},
                {"Id": "ep-3", "Name": "S01E01", "Type": "Episode", "SeriesId": "series-2", "SeriesName": "Show B"},
            ]
        return []

    monkeypatch.setattr(home_mod.library, "get_latest_episodes", fake_get_latest_episodes)

    window = _make_window(client, monkeypatch)
    window._load()

    tv_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_TV)
    assert [li.getProperty("jellyfin_id") for li in tv_row.items] == ["ep-1", "ep-2", "ep-3"]


def test_recently_added_tv_tiles_show_series_poster_not_episode_thumb(client, monkeypatch):
    """Tiles must show the show's poster, not the episode's own landscape
    screengrab - images.primary_image_url() would prefer that screengrab
    when the episode has one of its own (most do), so this row always goes
    straight to the series poster via series_poster_url() instead."""
    views = [
        {"Id": "lib-tv", "Name": "TV Shows", "CollectionType": "tvshows"},
    ]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])

    def fake_get_latest_episodes(c, parent_id=None, limit=10):
        if parent_id == "lib-tv":
            return [{
                "Id": "ep-1", "Name": "S01E02", "Type": "Episode", "SeriesId": "series-1",
                "SeriesName": "Show A", "SeriesPrimaryImageTag": "poster-tag",
                "ImageTags": {"Primary": "episode-thumb-tag"},
            }]
        return []

    monkeypatch.setattr(home_mod.library, "get_latest_episodes", fake_get_latest_episodes)

    window = _make_window(client, monkeypatch)
    window._load()

    tv_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_TV)
    art_url = tv_row.items[0].art["thumb"]
    assert "/Items/series-1/Images/Primary" in art_url
    assert "tag=poster-tag" in art_url


def test_load_hides_the_loading_indicator_once_everything_has_fetched(client, monkeypatch):
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(client, monkeypatch)
    assert window.getControl(home_mod.CTRL_LOADING).visible is True

    window._load()

    assert window.getControl(home_mod.CTRL_LOADING).visible is False


def test_load_marks_loading_done_once_everything_has_fetched(client, monkeypatch):
    """loading_done gates the background progress ticker (_tick_progress) -
    once set, the ticker stops updating the label on its next wake."""
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(client, monkeypatch)
    assert not window.loading_done.is_set()

    window._load()

    assert window.loading_done.is_set()


def test_onInit_sets_the_loading_label_to_zero_percent(client, monkeypatch):
    # get_views blocks (an Event, not a real sleep) so the background
    # _load() thread can't race ahead of this assertion and finish all 6
    # steps before it runs - xbmc.sleep() is a no-op in tests, so without
    # blocking here, _load() (and the independent _tick_progress ticker)
    # can complete/advance well before this synchronous assert executes.
    started = threading.Event()

    def blocking_get_views(c):
        started.set()
        threading.Event().wait(2)  # never actually set; just stalls _load()
        return []

    monkeypatch.setattr(home_mod.library, "get_views", blocking_get_views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(client, monkeypatch)
    window.onInit()

    # Exact "0%" isn't pinned down - the background progress ticker spins
    # without a real delay in tests (xbmc.sleep() is a no-op stub), so it
    # may have ticked the simulated percentage up by the time this runs.
    # "0 of 6" is deterministic though, since get_views is blocked.
    label = window.getControl(home_mod.CTRL_LOADING).getLabel()
    match = re.fullmatch(r"Loading library… (\d+)% \(0 of 6\)", label)
    assert match, label
    assert int(match.group(1)) < 10
    assert started.wait(2), "background thread never called get_views"


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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(client, monkeypatch)
    window._load()

    assert window.result is None  # nothing closed it - this is just the initial state
    assert not window.closed
    assert window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC).items == []
    movies_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MOVIES)
    assert [li.getLabel() for li in movies_row.items] == ["Alien"]


# -- Restoring selection after Back ------------------------------------------

def test_load_reselects_the_given_hub_row_item_once_it_arrives(client, monkeypatch):
    """When Home is shown again after Back (e.g. from a detail page opened
    by clicking a Recently Added Movies tile), select_control_id/
    select_item_id should land the selection back on that same tile
    instead of defaulting to the first item in the row."""
    views = [{"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"}]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])

    def fake_get_latest(c, parent_id=None, limit=10):
        if parent_id == "lib-movies":
            return [
                {"Id": "movie-1", "Name": "Alien", "Type": "Movie"},
                {"Id": "movie-2", "Name": "Aliens", "Type": "Movie"},
            ]
        return []

    monkeypatch.setattr(home_mod.library, "get_latest", fake_get_latest)
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(
        client, monkeypatch,
        select_control_id=home_mod.CTRL_RECENTLY_ADDED_MOVIES, select_item_id="movie-2",
    )
    window._load()

    movies_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MOVIES)
    assert movies_row.getSelectedItem().getProperty("jellyfin_id") == "movie-2"
    assert window.getFocusId() == home_mod.CTRL_RECENTLY_ADDED_MOVIES


def test_load_reselects_a_library_tile_once_it_arrives(client, monkeypatch):
    views = [
        {"Id": "lib-movies", "Name": "Filme", "CollectionType": "movies"},
        {"Id": "lib-tv", "Name": "Serien", "CollectionType": "tvshows"},
    ]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(
        client, monkeypatch,
        select_control_id=home_mod.CTRL_LIBRARIES, select_item_id="lib-tv",
    )
    window._load()

    libraries_row = window.getControl(home_mod.CTRL_LIBRARIES)
    assert libraries_row.getSelectedItem().getProperty("jellyfin_id") == "lib-tv"
    assert window.getFocusId() == home_mod.CTRL_LIBRARIES


def test_load_leaves_default_focus_when_no_selection_to_restore(client, monkeypatch):
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(client, monkeypatch)
    window._load()

    assert window.getFocusId() is None


# -- Per-row Home visibility toggles (addon settings) ------------------------

def test_hub_row_toggles_default_to_shown_when_settings_unset(client, monkeypatch):
    window = _make_window(client, monkeypatch)
    assert window.show_continue_watching is True
    assert window.show_next_up is True
    assert window.show_recently_added_movies is True
    assert window.show_recently_added_tv is True
    assert window.show_recently_added_music is True


def test_disabled_hub_row_is_never_fetched_or_populated(client, monkeypatch):
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])

    def fail_if_called(*a, **k):
        raise AssertionError("a disabled hub row must not be fetched")

    monkeypatch.setattr(home_mod.library, "get_next_up", fail_if_called)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(client, monkeypatch, extra_settings={home_mod.SHOW_NEXT_UP_SETTING: "false"})
    window._load()

    assert window.getControl(home_mod.CTRL_NEXT_UP).items == []


def test_disabled_hub_row_still_counts_as_a_completed_loading_step(client, monkeypatch):
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window = _make_window(client, monkeypatch, extra_settings={home_mod.SHOW_NEXT_UP_SETTING: "false"})
    window._load()

    assert window.loaded_steps == home_mod.TOTAL_LOAD_STEPS


def test_enabled_hub_rows_still_populate_when_a_sibling_row_is_disabled(client, monkeypatch):
    views = [{"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"}]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    def fake_get_latest(c, parent_id=None, limit=10):
        if parent_id == "lib-movies":
            return [{"Id": "movie-1", "Name": "Alien", "Type": "Movie"}]
        return []

    monkeypatch.setattr(home_mod.library, "get_latest", fake_get_latest)

    window = _make_window(client, monkeypatch, extra_settings={home_mod.SHOW_NEXT_UP_SETTING: "false"})
    window._load()

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

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


# -- Settings button (opens Kodi's native addon settings dialog) ------------

def test_clicking_settings_opens_the_native_settings_dialog(client, monkeypatch):
    window = _make_window(client, monkeypatch)
    opened = []
    monkeypatch.setattr(home_mod.ADDON, "openSettings", lambda: opened.append(True))
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window.handle_click(home_mod.CTRL_SETTINGS)

    assert opened == [True]


def test_settings_dialog_picks_up_a_setting_changed_while_it_was_open(client, monkeypatch):
    """openSettings() blocks until the user closes the dialog - by the time
    it returns here, whatever they toggled is already saved, so the
    in-memory flags must be re-read from ADDON rather than staying stale."""
    window = _make_window(client, monkeypatch)
    assert window.show_next_up is True

    def fake_open_settings():
        home_mod.ADDON.setSetting(home_mod.SHOW_NEXT_UP_SETTING, "false")

    monkeypatch.setattr(home_mod.ADDON, "openSettings", fake_open_settings)
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20: [])

    window.handle_click(home_mod.CTRL_SETTINGS)

    assert window.show_next_up is False


def test_settings_dialog_does_not_touch_controls_if_window_closed_while_open(client, monkeypatch):
    window = _make_window(client, monkeypatch)

    def fake_open_settings():
        window.closed_event.set()  # simulate Back firing while the native dialog was up

    monkeypatch.setattr(home_mod.ADDON, "openSettings", fake_open_settings)

    def fail_if_called(*a, **k):
        raise AssertionError("must not reload after the window was closed")

    monkeypatch.setattr(home_mod.library, "get_views", fail_if_called)

    window.handle_click(home_mod.CTRL_SETTINGS)  # must return quietly, not raise
