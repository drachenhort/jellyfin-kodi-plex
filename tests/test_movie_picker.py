"""Tests for MoviePickerWindow: the Clean Up screen's full-page movie
picker - ticking/unticking rows, All Watched, Clear, Done and Cancel."""

import lib.windows.movie_picker as picker_mod

MOVIES = [
    {"Id": "m1", "Name": "Alien", "Type": "Movie", "UserData": {"Played": True}},
    {"Id": "m2", "Name": "Brazil", "Type": "Movie", "UserData": {"Played": True}},
    {"Id": "u1", "Name": "Dune", "Type": "Movie", "UserData": {"Played": False}},
]


def _window(client, monkeypatch, selected_ids=()):
    monkeypatch.setattr(picker_mod.images, "primary_image_url", lambda *a, **k: None)
    window = picker_mod.MoviePickerWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client, movies=MOVIES, selected_ids=selected_ids)
    window.onInit()
    return window


def _checked(window):
    return [li.getProperty("jellyfin_id") for li in window.list_items if li.getProperty("checked") == "true"]


def _click_row(window, index):
    control = window.getControl(picker_mod.CTRL_MOVIE_LIST)
    control.selectItem(index)
    window.handle_click(picker_mod.CTRL_MOVIE_LIST)


def test_rows_show_preselected_checks_and_unwatched_flag(client, monkeypatch):
    window = _window(client, monkeypatch, selected_ids={"m2"})

    assert _checked(window) == ["m2"]
    assert [li.getProperty("unwatched") for li in window.list_items] == ["", "", "true"]
    assert window.getControl(picker_mod.CTRL_STATUS).getLabel().startswith("1 of 3 selected")


def test_clicking_a_row_toggles_it(client, monkeypatch):
    window = _window(client, monkeypatch, selected_ids={"m2"})

    _click_row(window, 0)
    _click_row(window, 1)

    assert _checked(window) == ["m1"]
    assert not window.closed


def test_all_watched_ticks_only_watched_movies(client, monkeypatch):
    window = _window(client, monkeypatch)

    window.handle_click(picker_mod.CTRL_ALL_WATCHED_BUTTON)

    assert _checked(window) == ["m1", "m2"]


def test_clear_unticks_everything(client, monkeypatch):
    window = _window(client, monkeypatch, selected_ids={"m1", "u1"})

    window.handle_click(picker_mod.CTRL_CLEAR_BUTTON)

    assert _checked(window) == []


def test_done_returns_ticked_ids_in_movie_order(client, monkeypatch):
    window = _window(client, monkeypatch, selected_ids={"u1"})
    _click_row(window, 0)

    window.handle_click(picker_mod.CTRL_DONE_BUTTON)

    assert window.result == ["m1", "u1"]
    assert window.closed


def test_cancel_returns_none(client, monkeypatch):
    window = _window(client, monkeypatch, selected_ids={"u1"})
    _click_row(window, 0)

    window.handle_click(picker_mod.CTRL_CANCEL_BUTTON)

    assert window.result is None
    assert window.closed
