"""Tests for lib.windows.detail's pure metadata-line helper, covering the
new music-track branch alongside its existing movie/episode behavior, plus
DetailWindow's click-before-loaded guard.

The skin's defaultcontrol focuses the Play button before onInit() even
runs, and onInit() only starts the actual fetch on a background thread
(_load()) rather than blocking the GUI thread for it - so a click can land
while self.item is still None, which handle_click() must not crash on.
"""

import lib.windows.detail as detail_mod
from lib.windows.detail import _format_runtime, _meta_line


def test_meta_line_movie_unchanged():
    item = {
        "ProductionYear": 1979,
        "OfficialRating": "R",
        "RunTimeTicks": 72_000_000_000,
        "CommunityRating": 8.4,
        "Genres": ["Horror", "Sci-Fi"],
    }
    assert _meta_line(item) == "1979  •  R  •  2h 0min  •  8.4★  •  Horror, Sci-Fi"


def test_meta_line_omits_rating_when_absent():
    item = {"ProductionYear": 1979, "RunTimeTicks": 72_000_000_000}
    assert _meta_line(item) == "1979  •  2h 0min"


def test_meta_line_track_shows_artist_and_album():
    item = {
        "Type": "Audio",
        "Artists": ["Radiohead"],
        "Album": "OK Computer",
        "ProductionYear": 1997,
        "RunTimeTicks": 4 * 60 * 10_000_000,
    }
    assert _meta_line(item) == "Radiohead  •  OK Computer  •  1997  •  4min"


def test_meta_line_track_falls_back_to_album_artist():
    item = {"Type": "Audio", "AlbumArtist": "Various Artists", "Album": "Compilation"}
    assert _meta_line(item) == "Various Artists  •  Compilation"


def test_meta_line_track_with_no_artist_or_album_omits_them():
    item = {"Type": "Audio", "RunTimeTicks": 3 * 60 * 10_000_000}
    assert _meta_line(item) == "3min"


def test_meta_line_appends_watched_when_played():
    item = {"ProductionYear": 1979, "UserData": {"Played": True}}
    assert _meta_line(item) == "1979  •  Watched"


def test_meta_line_omits_watched_when_not_played():
    item = {"ProductionYear": 1979, "UserData": {"Played": False}}
    assert _meta_line(item) == "1979"


# -- _format_runtime ---------------------------------------------------------

def test_format_runtime_under_an_hour():
    assert _format_runtime(45 * 60 * 10_000_000) == "45min"


def test_format_runtime_exact_hour():
    assert _format_runtime(60 * 60 * 10_000_000) == "1h 0min"


def test_format_runtime_hours_and_minutes():
    assert _format_runtime(134 * 60 * 10_000_000) == "2h 14min"


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
        "audio_stream_index": None,
        "subtitle_stream_index": None,
    }
    assert window.closed


# -- audio/subtitle track pickers --------------------------------------------

AUDIO_STREAM_EN = {"Type": "Audio", "Index": 1, "DisplayTitle": "English 5.1 - AC3 - Default", "IsDefault": True}
AUDIO_STREAM_FR = {"Type": "Audio", "Index": 2, "DisplayTitle": "French 2.0 - AAC"}
SUBTITLE_STREAM_EN = {"Type": "Subtitle", "Index": 3, "DisplayTitle": "English - SRT"}
SUBTITLE_STREAM_FORCED = {"Type": "Subtitle", "Index": 4, "DisplayTitle": "English (Forced) - SRT", "IsForced": True}


def _window_with_streams(client, monkeypatch, streams):
    monkeypatch.setattr(detail_mod.library, "get_item", lambda c, item_id, fields=None: {
        "Id": "item-1", "Name": "Alien", "Type": "Movie",
        "MediaSources": [{"MediaStreams": streams}],
    })
    monkeypatch.setattr(detail_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(detail_mod.images, "backdrop_image_url", lambda *a, **k: None)
    window = _make_window(client)
    window._load()
    return window


def test_load_streams_defaults_audio_to_the_stream_flagged_default(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, AUDIO_STREAM_FR])
    assert window.selected_audio_index == 0
    assert window.getControl(detail_mod.CTRL_AUDIO_BUTTON).getLabel() == "Audio: English 5.1 - AC3 - Default"


def test_load_streams_defaults_subtitles_to_none_when_no_forced_track(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, SUBTITLE_STREAM_EN])
    assert window.selected_subtitle_index is None
    assert window.getControl(detail_mod.CTRL_SUBTITLE_BUTTON).getLabel() == "Subtitles: None"


def test_load_streams_defaults_subtitles_to_the_forced_track(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, SUBTITLE_STREAM_EN, SUBTITLE_STREAM_FORCED])
    assert window.selected_subtitle_index == 1
    assert window.getControl(detail_mod.CTRL_SUBTITLE_BUTTON).getLabel() == "Subtitles: English (Forced) - SRT"


def test_audio_button_hidden_with_zero_or_one_track(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN])
    assert window.getControl(detail_mod.CTRL_AUDIO_BUTTON).visible is False


def test_audio_button_visible_with_multiple_tracks(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, AUDIO_STREAM_FR])
    assert window.getControl(detail_mod.CTRL_AUDIO_BUTTON).visible is True


def test_subtitle_button_hidden_when_no_subtitle_tracks(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN])
    assert window.getControl(detail_mod.CTRL_SUBTITLE_BUTTON).visible is False


def test_subtitle_button_visible_with_a_subtitle_track(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, SUBTITLE_STREAM_EN])
    assert window.getControl(detail_mod.CTRL_SUBTITLE_BUTTON).visible is True


class _FakeSelectDialog:
    """xbmcgui.Dialog() stand-in whose select() returns a fixed choice
    regardless of the heading/options passed - same style as
    tests/test_error_handling.py's FakeDialog for notification()."""

    def __init__(self, choice):
        self.choice = choice

    def __call__(self):
        return self

    def select(self, heading, options, **kwargs):
        return self.choice


def test_pick_audio_updates_selection_and_label(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, AUDIO_STREAM_FR])
    monkeypatch.setattr(detail_mod.xbmcgui, "Dialog", _FakeSelectDialog(1))

    window.handle_click(detail_mod.CTRL_AUDIO_BUTTON)

    assert window.selected_audio_index == 1
    assert window.getControl(detail_mod.CTRL_AUDIO_BUTTON).getLabel() == "Audio: French 2.0 - AAC"


def test_pick_audio_cancelled_leaves_selection_unchanged(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, AUDIO_STREAM_FR])
    monkeypatch.setattr(detail_mod.xbmcgui, "Dialog", _FakeSelectDialog(-1))

    window.handle_click(detail_mod.CTRL_AUDIO_BUTTON)

    assert window.selected_audio_index == 0


def test_pick_subtitle_first_option_selects_none(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, SUBTITLE_STREAM_EN, SUBTITLE_STREAM_FORCED])
    assert window.selected_subtitle_index == 1  # starts on the forced track
    monkeypatch.setattr(detail_mod.xbmcgui, "Dialog", _FakeSelectDialog(0))

    window.handle_click(detail_mod.CTRL_SUBTITLE_BUTTON)

    assert window.selected_subtitle_index is None
    assert window.getControl(detail_mod.CTRL_SUBTITLE_BUTTON).getLabel() == "Subtitles: None"


def test_pick_subtitle_selects_a_track(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, SUBTITLE_STREAM_EN])
    monkeypatch.setattr(detail_mod.xbmcgui, "Dialog", _FakeSelectDialog(1))

    window.handle_click(detail_mod.CTRL_SUBTITLE_BUTTON)

    assert window.selected_subtitle_index == 0
    assert window.getControl(detail_mod.CTRL_SUBTITLE_BUTTON).getLabel() == "Subtitles: English - SRT"


def test_play_includes_the_selected_stream_indices(client, monkeypatch):
    window = _window_with_streams(client, monkeypatch, [AUDIO_STREAM_EN, AUDIO_STREAM_FR, SUBTITLE_STREAM_EN])
    monkeypatch.setattr(detail_mod.xbmcgui, "Dialog", _FakeSelectDialog(1))
    window.handle_click(detail_mod.CTRL_AUDIO_BUTTON)  # -> French (index 1)
    window.handle_click(detail_mod.CTRL_SUBTITLE_BUTTON)  # choice 1 -> English - SRT (index 0)

    window.handle_click(detail_mod.CTRL_PLAY_BUTTON)

    assert window.result["audio_stream_index"] == 1
    assert window.result["subtitle_stream_index"] == 0


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
