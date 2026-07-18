"""Tests for BrowseWindow: paged loading via library.iter_items_paged(),
Play All/Shuffle (visible only when browsing a MusicAlbum's tracks), and
building the right track-id queue.

onInit() only starts _load() on a background thread (so a slow fetch can't
block the GUI thread) - these tests call _load() directly for a
deterministic, non-racy assertion instead of onInit().
"""

import re

import lib.windows.browse as browse_mod


def _make_window(client, parent_item_type=None):
    window = browse_mod.BrowseWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client, parent_id="parent-1", title="Title", parent_item_type=parent_item_type)
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
    }
    assert window.closed
