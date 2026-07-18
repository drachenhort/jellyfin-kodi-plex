"""Tests for BrowseWindow's Play All/Shuffle controls: visible only when
browsing a MusicAlbum's tracks, and building the right track-id queue.

onInit() only starts _load() on a background thread (so a slow fetch can't
block the GUI thread) - these tests call _load() directly for a
deterministic, non-racy assertion instead of onInit().
"""

import lib.windows.browse as browse_mod


def _make_window(client, parent_item_type=None):
    window = browse_mod.BrowseWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client, parent_id="parent-1", title="Title", parent_item_type=parent_item_type)
    return window


ALBUM_TRACKS = [
    {"Id": "track-1", "Name": "One", "Type": "Audio"},
    {"Id": "track-2", "Name": "Two", "Type": "Audio"},
    {"Id": "track-3", "Name": "Three", "Type": "Audio"},
]


def test_play_controls_visible_for_album(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()

    assert window.getControl(browse_mod.CTRL_PLAY_ALL).visible is True
    assert window.getControl(browse_mod.CTRL_SHUFFLE).visible is True


def test_play_controls_hidden_for_non_album_container(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})

    window = _make_window(client, parent_item_type="MusicArtist")
    window._load()

    assert window.getControl(browse_mod.CTRL_PLAY_ALL).visible is False
    assert window.getControl(browse_mod.CTRL_SHUFFLE).visible is False


def test_play_controls_hidden_for_empty_album(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": []})

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()

    assert window.getControl(browse_mod.CTRL_PLAY_ALL).visible is False
    assert window.getControl(browse_mod.CTRL_SHUFFLE).visible is False


def test_load_hides_the_loading_indicator_on_success(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})

    window = _make_window(client)
    assert window.getControl(browse_mod.CTRL_LOADING).visible is True

    window._load()

    assert window.getControl(browse_mod.CTRL_LOADING).visible is False


def test_load_leaves_the_loading_indicator_alone_if_window_already_closed(client, monkeypatch):
    """If the user backs out while the fetch is still in flight, _load()
    must return without touching any control once the response arrives -
    see the matching test in test_home.py."""
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})

    window = _make_window(client)
    window.closed_event.set()  # simulate Back already having fired

    window._load()

    assert window.getControl(browse_mod.CTRL_LOADING).visible is True
    assert window.getControl(browse_mod.CTRL_GRID).items == []


def test_play_all_queues_tracks_in_listing_order(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})

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
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})

    window = _make_window(client, parent_item_type="MusicAlbum")
    window._load()
    window.handle_click(browse_mod.CTRL_SHUFFLE)

    assert window.result["action"] == "play_queue"
    assert window.result["item_type"] == "Audio"
    assert sorted(window.result["item_ids"]) == ["track-1", "track-2", "track-3"]
    assert window.closed


def test_play_all_no_op_when_no_tracks(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": []})

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
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": EPISODES})
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="Season")
    window._load()

    assert [i.getProperty("jellyfin_id") for i in window.getControl(browse_mod.CTRL_EPISODE_LIST).items] == [
        "ep-1", "ep-2",
    ]
    assert window.getControl(browse_mod.CTRL_GRID).items == []


def test_non_season_children_still_populate_grid(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})
    monkeypatch.setattr(browse_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(browse_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client, parent_item_type="Series")
    window._load()

    assert len(window.getControl(browse_mod.CTRL_GRID).items) == 3
    assert window.getControl(browse_mod.CTRL_EPISODE_LIST).items == []


def test_episode_list_click_opens_selected_episode(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": EPISODES})
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

    assert window.getControl(browse_mod.CTRL_LOADING).getLabel() == "Loading Title…"


def test_grid_click_still_opens_selected_item(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})
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
