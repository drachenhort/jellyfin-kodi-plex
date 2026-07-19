"""Tests for SearchWindow's _start_search()/_search() split: pressing the
Search button must not block the GUI thread while the query is in flight,
and a second press while one is still running must not start an
overlapping second query.
"""

import threading

import lib.windows.search as search_mod


def _make_window(client):
    window = search_mod.SearchWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client)
    window.onInit()
    return window


def test_start_search_runs_query_in_a_background_thread(client, monkeypatch):
    started = threading.Event()
    finished = threading.Event()

    def slow_search_items(c, term, limit=50):
        started.set()
        assert finished.wait(2), "background thread never called search_items"
        return {"Items": []}

    monkeypatch.setattr(search_mod.library, "search_items", slow_search_items)

    window = _make_window(client)
    window.getControl(search_mod.CTRL_QUERY).setText("alien")
    window._start_search()  # must return without waiting for slow_search_items

    assert started.wait(2)
    finished.set()
    window._search_thread.join(timeout=2)


def test_start_search_ignores_a_second_click_while_one_is_in_flight(client, monkeypatch):
    calls = []
    release = threading.Event()

    def slow_search_items(c, term, limit=50):
        calls.append(term)
        release.wait(2)
        return {"Items": []}

    monkeypatch.setattr(search_mod.library, "search_items", slow_search_items)

    window = _make_window(client)
    window.getControl(search_mod.CTRL_QUERY).setText("alien")
    window._start_search()
    window._start_search()  # should be a no-op - a search is already running

    release.set()
    window._search_thread.join(timeout=2)
    assert calls == ["alien"]


def test_search_populates_results_and_focuses_grid(client, monkeypatch):
    monkeypatch.setattr(
        search_mod.library, "search_items",
        lambda c, term, limit=50: {"Items": [{"Id": "m1", "Name": "Alien", "Type": "Movie"}]},
    )
    monkeypatch.setattr(search_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(search_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client)
    window._search("alien")

    grid = window.getControl(search_mod.CTRL_RESULTS_GRID)
    assert [li.getLabel() for li in grid.items] == ["Alien"]
    assert window.getFocusId() == search_mod.CTRL_RESULTS_GRID
    assert window.getControl(search_mod.CTRL_STATUS_LABEL).getLabel() == ""


def test_search_shows_no_results_label(client, monkeypatch):
    monkeypatch.setattr(search_mod.library, "search_items", lambda c, term, limit=50: {"Items": []})

    window = _make_window(client)
    window._search("nonexistent")

    assert window.getControl(search_mod.CTRL_STATUS_LABEL).getLabel() == "No results"


def test_back_button_closes_with_no_result(client):
    window = _make_window(client)
    window.handle_click(search_mod.CTRL_BACK_BUTTON)

    assert window.result is None
    assert window.closed


def test_empty_query_clears_status_without_searching(client, monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("must not search on an empty query")

    monkeypatch.setattr(search_mod.library, "search_items", fail_if_called)

    window = _make_window(client)
    window.getControl(search_mod.CTRL_QUERY).setText("   ")
    window._start_search()

    assert window.getControl(search_mod.CTRL_STATUS_LABEL).getLabel() == ""
