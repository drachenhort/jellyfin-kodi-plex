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
from lib.jellyfin import library


class _FakeAction:
    def __init__(self, action_id):
        self._id = action_id

    def getId(self):
        return self._id


class _AbortMonitor:
    def abortRequested(self):
        return True


class _NoAbortMonitor:
    def abortRequested(self):
        return False


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


# -- onAction/Back: quit confirmation, asked by Home itself (not lib/main.py)
# so the dialog renders on top of Home's own screen instead of after Home
# has already closed and Kodi's own skin is showing behind it.

def test_back_action_asks_for_quit_confirmation(client, monkeypatch):
    monkeypatch.setattr(home_mod.xbmc, "Monitor", _NoAbortMonitor)
    asked = []
    monkeypatch.setattr(home_mod.xbmcgui, "Dialog", lambda: type(
        "D", (), {"yesno": lambda self, heading, message: asked.append((heading, message)) or True}
    )())
    window = _make_window(client, monkeypatch)

    window.onAction(_FakeAction(92))  # ACTION_NAV_BACK

    assert asked == [("Jellyfin", "Quit and return to Kodi?")]
    assert window.closed
    assert window.result is None


def test_back_action_declined_stays_on_home(client, monkeypatch):
    monkeypatch.setattr(home_mod.xbmc, "Monitor", _NoAbortMonitor)
    monkeypatch.setattr(home_mod.xbmcgui, "Dialog", lambda: type("D", (), {"yesno": lambda self, h, m: False})())
    window = _make_window(client, monkeypatch)

    window.onAction(_FakeAction(92))

    assert not window.closed
    assert window.result is None


def test_back_action_skips_dialog_when_kodi_is_aborting(client, monkeypatch):
    monkeypatch.setattr(home_mod.xbmc, "Monitor", _AbortMonitor)

    def fail_if_called():
        raise AssertionError("must not prompt for confirmation during shutdown")

    monkeypatch.setattr(home_mod.xbmcgui, "Dialog", fail_if_called)
    window = _make_window(client, monkeypatch)

    window.onAction(_FakeAction(92))

    assert window.closed
    assert window.result is None


def test_back_action_closes_even_if_declined_once_abort_fires_during_dialog(client, monkeypatch):
    """Reproduces a real-device crash: Kodi can force the quit-confirmation
    dialog closed mid-shutdown, handing back a falsy "No" just as abort
    becomes true - staying open at that exact moment is what caused a
    subsequent reopen elsewhere to crash with "maximum number of windows
    reached" (Kodi already mid-teardown, refusing to construct a new
    window)."""
    class _AbortAfterDialogMonitor:
        checks = 0

        def abortRequested(self):
            _AbortAfterDialogMonitor.checks += 1
            # False for the pre-dialog check, True for the post-dialog one.
            return _AbortAfterDialogMonitor.checks > 1

    monkeypatch.setattr(home_mod.xbmc, "Monitor", _AbortAfterDialogMonitor)
    monkeypatch.setattr(home_mod.xbmcgui, "Dialog", lambda: type("D", (), {"yesno": lambda self, h, m: False})())
    window = _make_window(client, monkeypatch)

    window.onAction(_FakeAction(92))

    assert window.closed
    assert window.result is None


def test_non_back_action_does_not_prompt(client, monkeypatch):
    monkeypatch.setattr(home_mod.xbmc, "Monitor", _NoAbortMonitor)

    def fail_if_called():
        raise AssertionError("must not prompt for an unrelated action")

    monkeypatch.setattr(home_mod.xbmcgui, "Dialog", fail_if_called)
    window = _make_window(client, monkeypatch)

    window.onAction(_FakeAction(999))

    assert not window.closed


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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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

    def fake_get_latest_episodes(c, parent_id=None, limit=10, block_threshold=3, hide_watched=False):
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

    def fake_get_latest_episodes(c, parent_id=None, limit=10, block_threshold=3, hide_watched=False):
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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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


def test_onInit_clears_the_browse_cache(client, monkeypatch):
    # A show/season the server only just finished scanning in can be
    # invisible in a library listing already cached from earlier this
    # session - returning to Home is the natural point to drop that cache
    # so browsing picks up newly-added items without needing an unrelated
    # watched-state change to clear it first.
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])
    home_mod.library.cache_children(client, "parent1", "SortName", "Ascending", [{"Id": "stale"}])

    window = _make_window(client, monkeypatch)
    window.onInit()

    assert home_mod.library.get_cached_children(client, "parent1", "SortName", "Ascending") is None


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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

    window = _make_window(client, monkeypatch)
    window._load()

    assert window.result is None  # nothing closed it - this is just the initial state
    assert not window.closed
    assert window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC).items == []
    movies_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MOVIES)
    assert [li.getLabel() for li in movies_row.items] == ["Alien"]


def test_a_broken_populate_step_does_not_blank_the_others_or_hang_loading(client, monkeypatch):
    """The fetch (get_resume) can succeed while the populate step still fails
    - _populate_episode_aware makes its own network call (get_items_by_ids)
    for season art. Previously only the fetch call was guarded, so a
    populate-time failure killed the whole background _load() thread
    silently, leaving every row after Continue Watching unpopulated and the
    loading overlay stuck on screen forever."""
    views = [{"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"}]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(
        home_mod.library, "get_resume",
        lambda c: [{"Id": "ep-1", "Name": "Ep 1", "Type": "Episode", "SeasonId": "season-1"}],
    )
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [
        {"Id": "movie-1", "Name": "Alien", "Type": "Movie"}
    ] if parent_id == "lib-movies" else [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

    def broken_get_items_by_ids(c, ids):
        raise RuntimeError("Read timed out")

    monkeypatch.setattr(home_mod.library, "get_items_by_ids", broken_get_items_by_ids)

    window = _make_window(client, monkeypatch)
    window._load()

    assert not window.closed
    assert window.getControl(home_mod.CTRL_CONTINUE_WATCHING).items == []
    movies_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MOVIES)
    assert [li.getLabel() for li in movies_row.items] == ["Alien"]
    assert window.loading_done.is_set()
    assert window.getControl(home_mod.CTRL_LOADING).visible is False


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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

    window = _make_window(client, monkeypatch, extra_settings={home_mod.SHOW_NEXT_UP_SETTING: "false"})
    window._load()

    assert window.getControl(home_mod.CTRL_NEXT_UP).items == []


def test_disabled_hub_row_still_counts_as_a_completed_loading_step(client, monkeypatch):
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

    window = _make_window(client, monkeypatch, extra_settings={home_mod.SHOW_NEXT_UP_SETTING: "false"})
    window._load()

    assert window.loaded_steps == home_mod.TOTAL_LOAD_STEPS


def test_enabled_hub_rows_still_populate_when_a_sibling_row_is_disabled(client, monkeypatch):
    views = [{"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"}]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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


def test_clock_settings_default_to_shown_and_24_hour(client, monkeypatch):
    window = _make_window(client, monkeypatch)
    assert window.show_clock is True
    assert window.clock_24_hour is True


def test_clock_settings_read_persisted_values(client, monkeypatch):
    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.SHOW_CLOCK_SETTING: "false", home_mod.CLOCK_24_HOUR_SETTING: "false"},
    )
    assert window.show_clock is False
    assert window.clock_24_hour is False


def test_oninit_sets_clock_window_properties(client, monkeypatch):
    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.CLOCK_24_HOUR_SETTING: "false"},
    )
    window.onInit()
    assert window.getProperty("show_clock") == "true"
    assert window.getProperty("clock_24_hour") == ""


def test_oninit_clears_clock_property_when_clock_disabled(client, monkeypatch):
    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.SHOW_CLOCK_SETTING: "false"},
    )
    window.onInit()
    assert window.getProperty("show_clock") == ""


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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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
    monkeypatch.setattr(home_mod.library, "get_latest_episodes", lambda c, parent_id=None, limit=20, block_threshold=3, hide_watched=False: [])

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


# -- Hide watched Recently Added Movies/TV (addon settings) -----------------

def test_hide_watched_recently_added_defaults_to_off(client, monkeypatch):
    window = _make_window(client, monkeypatch)
    assert window.hide_watched_recently_added_movies is False
    assert window.hide_watched_recently_added_tv is False
    assert window.hide_watched_recently_added_music is False


def test_hide_watched_recently_added_movies_filters_played_items(client, monkeypatch):
    views = [{"Id": "lib-movies", "Name": "Filme", "CollectionType": "movies"}]
    unwatched = {"Id": "m1", "Name": "Unwatched", "UserData": {"Played": False}}
    watched = {"Id": "m2", "Name": "Watched", "UserData": {"Played": True}}
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [unwatched, watched])

    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.HIDE_WATCHED_RECENTLY_ADDED_MOVIES_SETTING: "true"},
    )
    result = window._latest(views, "movies")

    assert result == [unwatched]


def test_hide_watched_recently_added_tv_setting_is_passed_to_get_latest_episodes(client, monkeypatch):
    # Unlike Movies/Music, TV filters watched episodes before grouping (see
    # library.get_latest_episodes) rather than after - a synthetic season
    # block has no Played flag of its own to filter on post-hoc - so this
    # asserts the flag reaches the library call rather than filtering here.
    views = [{"Id": "lib-tv", "Name": "Serien", "CollectionType": "tvshows"}]
    unwatched = {"Id": "e1", "Name": "Unwatched", "UserData": {"Played": False}}
    seen_hide_watched = []

    def fake_get_latest_episodes(c, parent_id=None, limit=10, block_threshold=3, hide_watched=False):
        seen_hide_watched.append(hide_watched)
        return [unwatched]

    monkeypatch.setattr(home_mod.library, "get_latest_episodes", fake_get_latest_episodes)

    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.HIDE_WATCHED_RECENTLY_ADDED_TV_SETTING: "true"},
    )
    result = window._latest_tv_episodes(views)

    assert seen_hide_watched == [True]
    assert result == [unwatched]


def test_hide_watched_recently_added_music_filters_played_tracks(client, monkeypatch):
    views = [{"Id": "lib-music", "Name": "Musik", "CollectionType": "music"}]
    unwatched = {"Id": "t1", "Name": "Unwatched", "UserData": {"Played": False}}
    watched = {"Id": "t2", "Name": "Watched", "UserData": {"Played": True}}
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [unwatched, watched])

    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.HIDE_WATCHED_RECENTLY_ADDED_MUSIC_SETTING: "true"},
    )
    result = window._latest(views, "music")

    assert result == [unwatched]


def test_hide_watched_setting_off_keeps_watched_items(client, monkeypatch):
    views = [{"Id": "lib-movies", "Name": "Filme", "CollectionType": "movies"}]
    watched = {"Id": "m2", "Name": "Watched", "UserData": {"Played": True}}
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [watched])

    window = _make_window(client, monkeypatch)
    result = window._latest(views, "movies")

    assert result == [watched]


# -- Recently Added item limit (addon setting) -------------------------------

def test_recently_added_item_limit_defaults_to_ten(client, monkeypatch):
    window = _make_window(client, monkeypatch)
    assert window.recently_added_item_limit == 10


def test_recently_added_item_limit_setting_is_passed_to_get_latest(client, monkeypatch):
    views = [{"Id": "lib-movies", "Name": "Filme", "CollectionType": "movies"}]
    seen_limits = []

    def fake_get_latest(c, parent_id=None, limit=10):
        seen_limits.append(limit)
        return []

    monkeypatch.setattr(home_mod.library, "get_latest", fake_get_latest)

    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.RECENTLY_ADDED_ITEM_LIMIT_SETTING: "25"},
    )
    window._latest(views, "movies")

    assert seen_limits == [25]


def test_recently_added_item_limit_setting_invalid_falls_back_to_default(client, monkeypatch):
    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.RECENTLY_ADDED_ITEM_LIMIT_SETTING: ""},
    )
    assert window.recently_added_item_limit == home_mod.DEFAULT_RECENTLY_ADDED_ITEM_LIMIT


# -- Season block threshold (addon setting) -----------------------------------

def test_season_block_threshold_defaults_to_library_default(client, monkeypatch):
    window = _make_window(client, monkeypatch)
    assert window.season_block_threshold == library.SEASON_BLOCK_THRESHOLD


def test_season_block_threshold_setting_is_passed_to_get_latest_episodes(client, monkeypatch):
    views = [{"Id": "lib-tv", "Name": "TV", "CollectionType": "tvshows"}]
    seen_thresholds = []

    def fake_get_latest_episodes(c, parent_id=None, limit=10, block_threshold=3, hide_watched=False):
        seen_thresholds.append(block_threshold)
        return []

    monkeypatch.setattr(home_mod.library, "get_latest_episodes", fake_get_latest_episodes)

    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.SEASON_BLOCK_THRESHOLD_SETTING: "5"},
    )
    window._latest_tv_episodes(views)

    assert seen_thresholds == [5]


def test_season_block_threshold_setting_invalid_falls_back_to_default(client, monkeypatch):
    window = _make_window(
        client, monkeypatch,
        extra_settings={home_mod.SEASON_BLOCK_THRESHOLD_SETTING: ""},
    )
    assert window.season_block_threshold == library.SEASON_BLOCK_THRESHOLD
