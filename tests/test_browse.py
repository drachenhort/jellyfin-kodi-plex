"""Tests for BrowseWindow: paged loading via library.iter_items_paged(),
Play All/Shuffle (visible only when browsing a MusicAlbum's tracks), and
building the right track-id queue.

onInit() only starts _load() on a background thread (so a slow fetch can't
block the GUI thread) - these tests call _load() directly for a
deterministic, non-racy assertion instead of onInit().
"""

import re

import xbmcaddon

import lib.windows.browse as browse_mod


def _make_window(client, parent_item_type=None, select_item_id=None, monkeypatch=None,
                  default_sort_by=None, parent_overview=""):
    if monkeypatch is not None and default_sort_by is not None:
        # browse.py's ADDON is a single module-level instance shared across
        # the whole test session - give the test its own fresh stub so a
        # setSetting() call here can't leak into another test's assertions.
        addon = xbmcaddon.Addon()
        addon.setSetting(browse_mod.DEFAULT_SORT_SETTING, default_sort_by)
        monkeypatch.setattr(browse_mod, "ADDON", addon)
    window = browse_mod.BrowseWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(
        client=client, parent_id="parent-1", title="Title", parent_item_type=parent_item_type,
        select_item_id=select_item_id, parent_overview=parent_overview,
    )
    return window


def _paged(*pages):
    """A fake iter_items_paged() that yields exactly the given pages (each
    a list of items) in order - `_paged(items)` mimics everything fitting
    in one page, `_paged(page1, page2)` mimics a multi-page fetch."""
    def fake(*a, **k):
        for page in pages:
            yield page
    return fake


def _failing_after(*pages, error):
    """A fake iter_items_paged() that yields the given pages successfully,
    then raises `error` as if a later page's request failed."""
    def fake(*a, **k):
        for page in pages:
            yield page
        raise error
    return fake


ALBUM_TRACKS = [
    {"Id": "track-1", "Name": "One", "Type": "Audio"},
    {"Id": "track-2", "Name": "Two", "Type": "Audio"},
    {"Id": "track-3", "Name": "Three", "Type": "Audio"},
]


def test_play_controls_visible_for_album(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()

    assert window.getControl(browse_mod.CTRL_PLAY_ALL).visible is True
    assert window.getControl(browse_mod.CTRL_SHUFFLE).visible is True


def test_play_controls_hidden_for_non_album_container(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))

    window = _make_window(client, parent_item_type="MusicArtist")
    window._load()

    assert window.getControl(browse_mod.CTRL_PLAY_ALL).visible is False
    assert window.getControl(browse_mod.CTRL_SHUFFLE).visible is False


def test_play_controls_hidden_for_empty_album(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged())

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()

    assert window.getControl(browse_mod.CTRL_PLAY_ALL).visible is False
    assert window.getControl(browse_mod.CTRL_SHUFFLE).visible is False


def test_load_hides_the_loading_indicator_on_success(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))

    window = _make_window(client)
    assert window.getControl(browse_mod.CTRL_LOADING).visible is True

    window._load()

    assert window.getControl(browse_mod.CTRL_LOADING).visible is False


def test_load_marks_loading_done_on_success(client, monkeypatch):
    """loading_done gates the background progress ticker (_tick_progress) -
    once set, the ticker stops updating the label on its next wake."""
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))

    window = _make_window(client)
    assert not window.loading_done.is_set()

    window._load()

    assert window.loading_done.is_set()


def test_load_marks_loading_done_on_first_page_failure(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _failing_after(error=RuntimeError("boom")))

    window = _make_window(client)
    window._load()

    assert window.loading_done.is_set()


def test_load_leaves_the_loading_indicator_alone_if_window_already_closed(client, monkeypatch):
    """If the user backs out while the fetch is still in flight, _load()
    must return without touching any control once the response arrives -
    see the matching test in test_home.py."""
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))

    window = _make_window(client)
    window.closed_event.set()  # simulate Back already having fired

    window._load()

    assert window.getControl(browse_mod.CTRL_LOADING).visible is True
    assert window.getControl(browse_mod.CTRL_GRID).items == []


def test_load_across_multiple_pages_accumulates_all_items(client, monkeypatch):
    page1 = [{"Id": "a1", "Name": "A1", "Type": "Audio"}]
    page2 = [{"Id": "a2", "Name": "A2", "Type": "Audio"}]
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(page1, page2))
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()

    assert [i.getProperty("jellyfin_id") for i in window.getControl(browse_mod.CTRL_GRID).items] == [
        "a1", "a2",
    ]
    assert window.items == page1 + page2


def test_load_sorts_by_name_ascending_when_no_setting_configured(client, monkeypatch):
    calls = []

    def fake_iter(c, **kwargs):
        calls.append(kwargs)
        return iter([])

    monkeypatch.setattr(browse_mod.library, "iter_items_paged", fake_iter)

    window = _make_window(client)
    window._load()

    assert calls[0]["sort_by"] == "SortName"
    assert calls[0]["sort_order"] == "Ascending"


def test_load_honors_the_default_sort_order_addon_setting(client, monkeypatch):
    calls = []

    def fake_iter(c, **kwargs):
        calls.append(kwargs)
        return iter([])

    monkeypatch.setattr(browse_mod.library, "iter_items_paged", fake_iter)

    window = _make_window(client, monkeypatch=monkeypatch, default_sort_by="date_added")
    window._load()

    assert calls[0]["sort_by"] == "DateCreated"
    assert calls[0]["sort_order"] == "Descending"


def test_load_failure_on_the_first_page_notifies_and_closes(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _failing_after(error=RuntimeError("boom")))

    window = _make_window(client)
    window._load()

    assert window.result is None
    assert window.closed


def test_load_failure_after_some_pages_keeps_what_loaded(client, monkeypatch):
    """A later page failing (e.g. a slow real library timing out mid-walk)
    shouldn't throw away pages that already loaded fine."""
    page1 = [{"Id": "a1", "Name": "A1", "Type": "Audio"}]
    monkeypatch.setattr(
        browse_mod.library, "iter_items_paged", _failing_after(page1, error=RuntimeError("boom"))
    )
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client)
    window._load()

    assert not window.closed
    assert window.items == page1
    assert [i.getProperty("jellyfin_id") for i in window.getControl(browse_mod.CTRL_GRID).items] == ["a1"]
    assert window.getControl(browse_mod.CTRL_LOADING).visible is False


def test_play_all_queues_tracks_in_listing_order(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()
    window.handle_click(browse_mod.CTRL_PLAY_ALL)

    assert window.result == {
        "action": "play_queue",
        "item_ids": ["track-1", "track-2", "track-3"],
        "item_type": "Audio",
    }
    assert window.closed


def test_shuffle_queues_all_tracks_in_some_order(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()
    window.handle_click(browse_mod.CTRL_SHUFFLE)

    assert window.result["action"] == "play_queue"
    assert window.result["item_type"] == "Audio"
    assert sorted(window.result["item_ids"]) == ["track-1", "track-2", "track-3"]
    assert window.closed


def test_play_all_no_op_when_no_tracks(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged())

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()
    window.handle_click(browse_mod.CTRL_PLAY_ALL)

    assert window.result is None
    assert not window.closed


# -- episode list (parent_item_type="Season") --------------------------

EPISODES = [
    {"Id": "ep-1", "Name": "Pilot", "Type": "Episode"},
    {"Id": "ep-2", "Name": "Redemption", "Type": "Episode"},
]


def test_season_children_populate_episode_list_not_grid(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(EPISODES))
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="Season")
    window._load()

    assert [i.getProperty("jellyfin_id") for i in window.getControl(browse_mod.CTRL_EPISODE_LIST).items] == [
        "ep-1", "ep-2",
    ]
    assert window.getControl(browse_mod.CTRL_GRID).items == []


def test_non_season_children_still_populate_grid(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="Series")
    window._load()

    assert len(window.getControl(browse_mod.CTRL_GRID).items) == 3
    assert window.getControl(browse_mod.CTRL_EPISODE_LIST).items == []


def test_load_refocuses_episode_list_once_items_arrive(client, monkeypatch):
    """onInit() calls setFocusId() before _load() has fetched anything, so
    Kodi refuses the focus request on the still-empty list (logged as
    "has been asked to focus, but it can't") and no episode is selectable.
    _load() must re-request focus once the list actually has items."""
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(EPISODES))
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="Season")
    window.setFocusId(browse_mod.CTRL_EPISODE_LIST)  # what onInit() does pre-fetch
    window._load()

    assert window.getFocusId() == browse_mod.CTRL_EPISODE_LIST


def test_load_refocuses_grid_once_items_arrive(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="Series")
    window.setFocusId(browse_mod.CTRL_GRID)
    window._load()

    assert window.getFocusId() == browse_mod.CTRL_GRID


def test_load_reselects_the_given_item_once_it_arrives(client, monkeypatch):
    """When this screen is being shown again after Back (e.g. from a
    detail page opened by clicking "Redemption"), select_item_id should
    make _load() land the selection back on that same episode instead of
    defaulting to the first item in the list."""
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(EPISODES))
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="Season", select_item_id="ep-2")
    window._load()

    selected = window.getControl(browse_mod.CTRL_EPISODE_LIST).getSelectedItem()
    assert selected.getProperty("jellyfin_id") == "ep-2"
    assert window.getFocusId() == browse_mod.CTRL_EPISODE_LIST


def test_load_leaves_default_selection_when_no_select_item_id_given(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(EPISODES))
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="Season")
    window._load()

    selected = window.getControl(browse_mod.CTRL_EPISODE_LIST).getSelectedItem()
    assert selected.getProperty("jellyfin_id") == "ep-1"


def test_episode_list_click_opens_selected_episode(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(EPISODES))
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="Season")
    window._load()
    window.handle_click(browse_mod.CTRL_EPISODE_LIST)

    assert window.result == {
        "action": "open",
        "item_id": "ep-1",
        "item_type": "Episode",
        "item_name": "Pilot",
        "item_overview": "",
    }
    assert window.closed


def test_onInit_shows_episode_list_and_hides_grid_for_season(client):
    window = _make_window(client, parent_item_type="Season")
    window.onInit()

    assert window.getControl(browse_mod.CTRL_EPISODE_LIST).visible is True
    assert window.getControl(browse_mod.CTRL_GRID).visible is False


def test_onInit_shows_grid_and_hides_episode_list_for_non_season(client):
    window = _make_window(client, parent_item_type="Series")
    window.onInit()

    assert window.getControl(browse_mod.CTRL_GRID).visible is True
    assert window.getControl(browse_mod.CTRL_EPISODE_LIST).visible is False


def test_onInit_sets_the_parent_overview_property_for_series(client):
    window = _make_window(client, parent_item_type="Series", parent_overview="A show about things.")
    window.onInit()

    # The skin's own <visible> conditions (Window.Property(parent_overview)
    # being empty or not) drive which of the static parent-overview pane and
    # the per-item plot pane actually renders - see the XML for why this is
    # a Window property rather than a direct getControl().setVisible() call.
    assert window.getProperty("parent_overview") == "A show about things."


def test_onInit_leaves_the_parent_overview_property_empty_when_series_has_no_overview(client):
    window = _make_window(client, parent_item_type="Series", parent_overview="")
    window.onInit()

    assert window.getProperty("parent_overview") == ""


def test_onInit_sets_the_parent_overview_property_for_season(client):
    window = _make_window(client, parent_item_type="Season", parent_overview="A season overview.")
    window.onInit()

    assert window.getProperty("parent_overview") == "A season overview."


def test_onInit_never_sets_parent_overview_for_non_summarized_parent_type(client):
    window = _make_window(client, parent_item_type="MusicAlbum", parent_overview="Liner notes.")
    window.onInit()

    assert window.getProperty("parent_overview") == ""


def test_onInit_sets_the_loading_label_to_the_screen_title(client):
    window = _make_window(client, parent_item_type="Series")
    window.onInit()

    # Exact "0%" isn't pinned down - the background progress ticker spins
    # without a real delay in tests (xbmc.sleep() is a no-op stub), so it
    # may have ticked the simulated percentage up by the time this runs.
    # "0 items" is deterministic though: iter_items_paged() isn't mocked
    # here, so no real page can have arrived yet.
    label = window.getControl(browse_mod.CTRL_LOADING).getLabel()
    match = re.fullmatch(r"Loading Title… (\d+)% \(0 items\)", label)
    assert match, label
    assert int(match.group(1)) < 10


def test_grid_click_still_opens_selected_item(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "iter_items_paged", _paged(ALBUM_TRACKS))
    monkeypatch.setattr(
        browse_mod.images, "primary_image_url", lambda *a, **k: None
    )
    monkeypatch.setattr(
        browse_mod.images, "backdrop_image_url", lambda *a, **k: None
    )

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()
    window.handle_click(browse_mod.CTRL_GRID)

    assert window.result == {
        "action": "open",
        "item_id": "track-1",
        "item_type": "Audio",
        "item_name": "One",
        "item_overview": "",
    }
    assert window.closed
