"""Tests for lib.windows.detail's pure metadata-line helper, covering the
new music-track branch alongside its existing movie/episode behavior, plus
DetailWindow's click-before-loaded guard.

The skin's defaultcontrol focuses the Play button before onInit() even
runs, and onInit() only starts the actual fetch on a background thread
(_load()) rather than blocking the GUI thread for it - so a click can land
while self.item is still None, which handle_click() must not crash on.
"""

import lib.windows.detail as detail_mod
from lib.windows.detail import _meta_line


def test_meta_line_movie_unchanged():
    item = {
        "ProductionYear": 1979,
        "RunTimeTicks": 72_000_000_000,
        "CommunityRating": 8.4,
        "Genres": ["Horror", "Sci-Fi"],
    }
    assert _meta_line(item) == "1979  •  120 min  •  8.4★  •  Horror, Sci-Fi"


def test_meta_line_track_shows_artist_and_album():
    item = {
        "Type": "Audio",
        "Artists": ["Radiohead"],
        "Album": "OK Computer",
        "ProductionYear": 1997,
        "RunTimeTicks": 4 * 60 * 10_000_000,
    }
    assert _meta_line(item) == "Radiohead  •  OK Computer  •  1997  •  4 min"


def test_meta_line_track_falls_back_to_album_artist():
    item = {"Type": "Audio", "AlbumArtist": "Various Artists", "Album": "Compilation"}
    assert _meta_line(item) == "Various Artists  •  Compilation"


def test_meta_line_track_with_no_artist_or_album_omits_them():
    item = {"Type": "Audio", "RunTimeTicks": 3 * 60 * 10_000_000}
    assert _meta_line(item) == "3 min"


def test_meta_line_appends_watched_when_played():
    item = {"ProductionYear": 1979, "UserData": {"Played": True}}
    assert _meta_line(item) == "1979  •  Watched"


def test_meta_line_omits_watched_when_not_played():
    item = {"ProductionYear": 1979, "UserData": {"Played": False}}
    assert _meta_line(item) == "1979"


def _make_window(client, item_id="item-1"):
    window = detail_mod.DetailWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client, item_id=item_id)
    return window


def test_clicking_play_before_item_is_loaded_is_a_no_op(client):
    window = _make_window(client)
    # Simulates the skin's defaultcontrol landing a click on the Play
    # button before the background _load() thread has finished fetching.
    assert window.item is None

    window.handle_click(detail_mod.CTRL_PLAY_BUTTON)

    assert window.result is None
    assert not window.closed


def test_play_click_after_load_includes_item_type_and_resume_ticks(client, monkeypatch):
    monkeypatch.setattr(detail_mod.library, "get_item", lambda c, item_id, fields=None: {
        "Id": "item-1", "Name": "Alien", "Type": "Movie",
        "UserData": {"PlaybackPositionTicks": 20 * 10_000_000},
    })
    monkeypatch.setattr(detail_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(detail_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client)
    window._load()
    window.handle_click(detail_mod.CTRL_PLAY_BUTTON)

    assert window.result == {
        "action": "play",
        "item_id": "item-1",
        "item_type": "Movie",
        "resume_ticks": 20 * 10_000_000,
    }
    assert window.closed


# -- watched/unwatched toggle -----------------------------------------------
# handle_click() spawns _toggle_watched() on a background thread (same
# reasoning as _load() above), so these tests call _toggle_watched()
# directly for deterministic, non-racy assertions.

def _loaded_window(client, monkeypatch, played):
    monkeypatch.setattr(detail_mod.library, "get_item", lambda c, item_id, fields=None: {
        "Id": "item-1", "Name": "Alien", "Type": "Movie",
        "UserData": {"Played": played},
    })
    monkeypatch.setattr(detail_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(detail_mod.images, "backdrop_image_url", lambda *a, **k: None)
    window = _make_window(client)
    window._load()
    return window


def test_watched_button_label_for_unwatched_item(client, monkeypatch):
    window = _loaded_window(client, monkeypatch, played=False)
    assert window.getControl(detail_mod.CTRL_WATCHED_BUTTON).getLabel() == "Mark as Watched"


def test_watched_button_label_for_watched_item(client, monkeypatch):
    window = _loaded_window(client, monkeypatch, played=True)
    assert window.getControl(detail_mod.CTRL_WATCHED_BUTTON).getLabel() == "Mark as Unwatched"


def test_toggle_watched_marks_played_when_currently_unwatched(client, monkeypatch):
    window = _loaded_window(client, monkeypatch, played=False)
    calls = []
    monkeypatch.setattr(detail_mod.library, "mark_played", lambda c, item_id: calls.append(item_id))

    window._toggle_watched()

    assert calls == ["item-1"]
    assert window.item["UserData"]["Played"] is True
    assert window.getControl(detail_mod.CTRL_WATCHED_BUTTON).getLabel() == "Mark as Unwatched"
    assert "Watched" in window.getControl(detail_mod.CTRL_META).getLabel()


def test_toggle_watched_marks_unplayed_when_currently_watched(client, monkeypatch):
    window = _loaded_window(client, monkeypatch, played=True)
    calls = []
    monkeypatch.setattr(detail_mod.library, "mark_unplayed", lambda c, item_id: calls.append(item_id))

    window._toggle_watched()

    assert calls == ["item-1"]
    assert window.item["UserData"]["Played"] is False
    assert window.getControl(detail_mod.CTRL_WATCHED_BUTTON).getLabel() == "Mark as Watched"
    assert "Watched" not in window.getControl(detail_mod.CTRL_META).getLabel()


def test_toggle_watched_leaves_state_unchanged_on_server_error(client, monkeypatch):
    window = _loaded_window(client, monkeypatch, played=False)

    def raise_error(c, item_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(detail_mod.library, "mark_played", raise_error)

    window._toggle_watched()

    assert window.item["UserData"]["Played"] is False
    assert window.getControl(detail_mod.CTRL_WATCHED_BUTTON).getLabel() == "Mark as Watched"


def test_clicking_watched_button_before_item_is_loaded_is_a_no_op(client):
    window = _make_window(client)
    assert window.item is None

    window.handle_click(detail_mod.CTRL_WATCHED_BUTTON)

    assert window.result is None
    assert not window.closed


# -- "More Like This" (similar items) ---------------------------------------

def test_load_similar_populates_the_similar_control(client, monkeypatch):
    monkeypatch.setattr(detail_mod.library, "get_similar", lambda c, item_id, limit=12: [
        {"Id": "s1", "Name": "Similar One", "Type": "Movie"},
        {"Id": "s2", "Name": "Similar Two", "Type": "Movie"},
    ])
    monkeypatch.setattr(detail_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(detail_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client)
    window._load_similar()

    assert window.getControl(detail_mod.CTRL_SIMILAR).items[0].getLabel() == "Similar One"
    assert window.getControl(detail_mod.CTRL_SIMILAR).items[1].getLabel() == "Similar Two"


def test_load_similar_leaves_the_row_empty_on_failure(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(detail_mod.library, "get_similar", boom)

    window = _make_window(client)
    window._load_similar()  # must not raise

    assert window.getControl(detail_mod.CTRL_SIMILAR).items == []


def test_load_similar_does_nothing_if_window_already_closed(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        detail_mod.library, "get_similar",
        lambda c, item_id, limit=12: (calls.append(1), [{"Id": "s1", "Name": "X", "Type": "Movie"}])[1],
    )

    window = _make_window(client)
    window.closed_event.set()
    window._load_similar()

    assert calls == [1]  # the request itself still happens...
    assert window.getControl(detail_mod.CTRL_SIMILAR).items == []  # ...but nothing gets populated


def test_clicking_similar_item_sets_open_result_and_closes(client, monkeypatch):
    monkeypatch.setattr(detail_mod.library, "get_similar", lambda c, item_id, limit=12: [
        {"Id": "s1", "Name": "Similar One", "Type": "Movie", "Overview": "A similar plot."},
    ])
    monkeypatch.setattr(detail_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(detail_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client)
    window._load_similar()
    window.getControl(detail_mod.CTRL_SIMILAR).selectItem(0)

    window.handle_click(detail_mod.CTRL_SIMILAR)

    assert window.result == {
        "action": "open",
        "item_id": "s1",
        "item_type": "Movie",
        "item_name": "Similar One",
        "item_overview": "A similar plot.",
    }
    assert window.closed


def test_clicking_similar_item_before_any_selection_is_a_no_op(client):
    window = _make_window(client)

    window.handle_click(detail_mod.CTRL_SIMILAR)

    assert window.result is None
    assert not window.closed


def test_clicking_similar_item_works_even_before_main_item_is_loaded(client, monkeypatch):
    """handle_click()'s self.item is None guard must not swallow a
    CTRL_SIMILAR click - similar items load on their own thread and could
    finish before the main item fetch does."""
    monkeypatch.setattr(detail_mod.library, "get_similar", lambda c, item_id, limit=12: [
        {"Id": "s1", "Name": "Similar One", "Type": "Movie"},
    ])
    monkeypatch.setattr(detail_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(detail_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client)
    assert window.item is None
    window._load_similar()
    window.getControl(detail_mod.CTRL_SIMILAR).selectItem(0)

    window.handle_click(detail_mod.CTRL_SIMILAR)

    assert window.result["item_id"] == "s1"
    assert window.closed
