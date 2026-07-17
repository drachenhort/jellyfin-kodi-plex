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
