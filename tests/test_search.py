"""Tests for SearchWindow's _start_search()/_search() split: pressing the
Search button must not block the GUI thread while the query is in flight,
and a second press while one is still running must not start an
overlapping second query. Also covers _poll_query_once() (see module
docstring): search-as-you-type is a polling loop, not a real callback, so
its decision logic is tested directly rather than by racing onInit()'s
real background thread against xbmc.sleep() (a no-op in the test stub,
which would otherwise busy-spin for the rest of the process).
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

    def slow_search_items(c, term, limit=50, include_item_types=None):
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
    window.close()


def test_start_search_ignores_a_second_click_while_one_is_in_flight(client, monkeypatch):
    calls = []
    release = threading.Event()

    def slow_search_items(c, term, limit=50, include_item_types=None):
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
    window.close()


def test_search_populates_the_matching_category_row_and_focuses_it(client, monkeypatch):
    monkeypatch.setattr(
        search_mod.library, "search_items",
        lambda c, term, limit=50, include_item_types=None: {"Items": [{"Id": "m1", "Name": "Alien", "Type": "Movie"}]},
    )
    monkeypatch.setattr(search_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(search_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client)
    window._search("alien", search_mod.library.SEARCH_ITEM_TYPES)

    movies_row = window.getControl(search_mod.CTRL_RESULTS_MOVIES)
    assert [li.getLabel() for li in movies_row.items] == ["Alien"]
    assert window.getControl(search_mod.CTRL_RESULTS_TV).items == []
    assert window.getControl(search_mod.CTRL_RESULTS_MUSIC).items == []
    assert window.getFocusId() == search_mod.CTRL_RESULTS_MOVIES
    assert window.getControl(search_mod.CTRL_STATUS_LABEL).getLabel() == ""
    window.close()


def test_search_groups_results_into_their_matching_category_rows(client, monkeypatch):
    monkeypatch.setattr(
        search_mod.library, "search_items",
        lambda c, term, limit=50, include_item_types=None: {"Items": [
            {"Id": "m1", "Name": "Alien", "Type": "Movie"},
            {"Id": "s1", "Name": "Alien Nation", "Type": "Series"},
            {"Id": "e1", "Name": "Alien Autopsy", "Type": "Episode"},
            {"Id": "a1", "Name": "Alien Ant Farm", "Type": "MusicArtist"},
        ]},
    )
    monkeypatch.setattr(search_mod.images, "primary_image_url", lambda *a, **k: None)
    monkeypatch.setattr(search_mod.images, "backdrop_image_url", lambda *a, **k: None)

    window = _make_window(client)
    window._search("alien", search_mod.library.SEARCH_ITEM_TYPES)

    assert [li.getLabel() for li in window.getControl(search_mod.CTRL_RESULTS_MOVIES).items] == ["Alien"]
    assert [li.getLabel() for li in window.getControl(search_mod.CTRL_RESULTS_TV).items] == [
        "Alien Nation", "Alien Autopsy",
    ]
    assert [li.getLabel() for li in window.getControl(search_mod.CTRL_RESULTS_MUSIC).items] == ["Alien Ant Farm"]
    window.close()


def test_search_shows_no_results_label(client, monkeypatch):
    monkeypatch.setattr(search_mod.library, "search_items", lambda c, term, limit=50, include_item_types=None: {"Items": []})

    window = _make_window(client)
    window._search("nonexistent", search_mod.library.SEARCH_ITEM_TYPES)

    assert window.getControl(search_mod.CTRL_STATUS_LABEL).getLabel() == "No results"
    window.close()


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
    window.close()


def test_poll_does_not_search_while_text_is_still_changing(client, monkeypatch):
    monkeypatch.setattr(
        search_mod.library, "search_items",
        lambda c, term, limit=50, include_item_types=None: (_ for _ in ()).throw(AssertionError("must not search yet")),
    )

    window = _make_window(client)
    query = window.getControl(search_mod.CTRL_QUERY)
    query.setText("a")
    window._poll_query_once()
    query.setText("al")
    window._poll_query_once()  # text changed since the last poll - no search

    assert window._search_thread is None
    window.close()


def test_poll_searches_once_text_holds_steady_for_one_interval(client, monkeypatch):
    monkeypatch.setattr(
        search_mod.library, "search_items",
        lambda c, term, limit=50, include_item_types=None: {"Items": []},
    )

    window = _make_window(client)
    window.getControl(search_mod.CTRL_QUERY).setText("alien")
    window._poll_query_once()  # first sighting of "alien"
    window._poll_query_once()  # same text again - now it fires

    window._search_thread.join(timeout=2)
    assert window._last_submitted_text == "alien"
    window.close()


def test_filters_all_start_checked(client):
    window = _make_window(client)

    for control_id in search_mod.FILTER_ITEM_TYPES:
        assert window.getControl(control_id).getLabel().startswith("[x]")
    window.close()


def test_toggling_a_filter_updates_its_label_and_narrows_the_next_search(client, monkeypatch):
    seen_item_types = []
    monkeypatch.setattr(
        search_mod.library, "search_items",
        lambda c, term, limit=50, include_item_types=None: seen_item_types.append(include_item_types)
        or {"Items": []},
    )

    window = _make_window(client)
    window.getControl(search_mod.CTRL_QUERY).setText("alien")
    window.handle_click(search_mod.CTRL_FILTER_MUSIC)
    window._search_thread.join(timeout=2)

    assert window.getControl(search_mod.CTRL_FILTER_MUSIC).getLabel() == "[ ] Music"
    assert "MusicArtist" not in seen_item_types[-1]
    assert "Movie" in seen_item_types[-1] and "Series" in seen_item_types[-1]
    window.close()


def test_toggling_a_filter_back_on_restores_its_types(client, monkeypatch):
    seen_item_types = []
    monkeypatch.setattr(
        search_mod.library, "search_items",
        lambda c, term, limit=50, include_item_types=None: seen_item_types.append(include_item_types)
        or {"Items": []},
    )

    window = _make_window(client)
    window.getControl(search_mod.CTRL_QUERY).setText("alien")
    window.handle_click(search_mod.CTRL_FILTER_MUSIC)
    window._search_thread.join(timeout=2)
    window.handle_click(search_mod.CTRL_FILTER_MUSIC)
    window._search_thread.join(timeout=2)

    assert window.getControl(search_mod.CTRL_FILTER_MUSIC).getLabel() == "[x] Music"
    assert "MusicArtist" in seen_item_types[-1]
    window.close()


def test_unchecking_every_filter_shows_a_message_without_searching(client, monkeypatch):
    def fail_if_called(*a, **k):
        raise AssertionError("must not search with no categories selected")

    monkeypatch.setattr(search_mod.library, "search_items", fail_if_called)

    window = _make_window(client)
    window.getControl(search_mod.CTRL_QUERY).setText("alien")
    window.handle_click(search_mod.CTRL_FILTER_MOVIES)
    window.handle_click(search_mod.CTRL_FILTER_TV)
    window.handle_click(search_mod.CTRL_FILTER_MUSIC)

    assert window.getControl(search_mod.CTRL_STATUS_LABEL).getLabel() == "No categories selected"
    window.close()


def test_poll_does_not_resubmit_the_same_text_twice(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        search_mod.library, "search_items",
        lambda c, term, limit=50, include_item_types=None: calls.append(term) or {"Items": []},
    )

    window = _make_window(client)
    window.getControl(search_mod.CTRL_QUERY).setText("alien")
    window._poll_query_once()
    window._poll_query_once()
    window._search_thread.join(timeout=2)
    window._poll_query_once()  # still "alien", already submitted - no-op

    assert calls == ["alien"]
    window.close()
