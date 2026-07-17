"""Tests for BrowseWindow's Play All/Shuffle controls: visible only when
browsing a MusicAlbum's tracks, and building the right track-id queue.
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
    window.onInit()

    assert window.getControl(browse_mod.CTRL_PLAY_ALL).visible is True
    assert window.getControl(browse_mod.CTRL_SHUFFLE).visible is True


def test_play_controls_hidden_for_non_album_container(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})

    window = _make_window(client, parent_item_type="MusicArtist")
    window.onInit()

    assert window.getControl(browse_mod.CTRL_PLAY_ALL).visible is False
    assert window.getControl(browse_mod.CTRL_SHUFFLE).visible is False


def test_play_controls_hidden_for_empty_album(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": []})

    window = _make_window(client, parent_item_type="MusicAlbum")
    window.onInit()

    assert window.getControl(browse_mod.CTRL_PLAY_ALL).visible is False
    assert window.getControl(browse_mod.CTRL_SHUFFLE).visible is False


def test_play_all_queues_tracks_in_listing_order(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})

    window = _make_window(client, parent_item_type="MusicAlbum")
    window.onInit()
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
    window.onInit()
    window.handle_click(browse_mod.CTRL_SHUFFLE)

    assert window.result["action"] == "play_queue"
    assert window.result["item_type"] == "Audio"
    assert sorted(window.result["item_ids"]) == ["track-1", "track-2", "track-3"]
    assert window.closed


def test_play_all_no_op_when_no_tracks(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": []})

    window = _make_window(client, parent_item_type="MusicAlbum")
    window.onInit()
    window.handle_click(browse_mod.CTRL_PLAY_ALL)

    assert window.result is None
    assert not window.closed


def test_grid_click_still_opens_selected_item(client, monkeypatch):
    monkeypatch.setattr(browse_mod.library, "get_items", lambda *a, **k: {"Items": ALBUM_TRACKS})
    monkeypatch.setattr(
        browse_mod.images, "primary_image_url", lambda *a, **k: None
    )
    monkeypatch.setattr(
        browse_mod.images, "backdrop_image_url", lambda *a, **k: None
    )

    window = _make_window(client, parent_item_type="MusicAlbum")
    window.onInit()
    window.handle_click(browse_mod.CTRL_GRID)

    assert window.result == {
        "action": "open",
        "item_id": "track-1",
        "item_type": "Audio",
        "item_name": "One",
    }
    assert window.closed
