"""Tests for the server/network error-handling paths added to Home, Browse,
Detail (close with result=None + notify) and Search (inline status label,
window stays open since it already loaded fine before the query ran).

None of these windows have their onInit() invoked automatically by the
tests/kodi_stubs WindowXML stand-in (doModal() there is a no-op, unlike real
Kodi) - so each test builds the window directly and calls onInit() itself.
"""

import xbmcgui

import lib.windows.browse as browse_mod
import lib.windows.detail as detail_mod
import lib.windows.home as home_mod
import lib.windows.search as search_mod


class FakeDialog:
    notifications = []

    def notification(self, heading, message, icon=None, time=None, sound=True):
        FakeDialog.notifications.append((heading, message))


def _make_window(window_cls, **setup_kwargs):
    window = window_cls(None, "/fake/addon/path", "Main", "1080i")
    window.setup(**setup_kwargs)
    return window


def test_home_window_closes_with_no_result_on_load_failure(client, monkeypatch):
    FakeDialog.notifications.clear()
    monkeypatch.setattr(xbmcgui, "Dialog", FakeDialog)
    monkeypatch.setattr(
        home_mod.library, "get_views", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    window = _make_window(home_mod.HomeWindow, client=client)
    window.onInit()

    assert window.result is None
    assert window.closed
    assert FakeDialog.notifications
    assert "boom" in FakeDialog.notifications[-1][1]


def test_browse_window_closes_with_no_result_on_load_failure(client, monkeypatch):
    FakeDialog.notifications.clear()
    monkeypatch.setattr(xbmcgui, "Dialog", FakeDialog)
    monkeypatch.setattr(
        browse_mod.library, "get_items", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))
    )

    window = _make_window(browse_mod.BrowseWindow, client=client, parent_id="lib-1", title="Movies")
    window.onInit()

    assert window.result is None
    assert window.closed
    assert FakeDialog.notifications
    assert "offline" in FakeDialog.notifications[-1][1]


def test_detail_window_closes_with_no_result_on_load_failure(client, monkeypatch):
    FakeDialog.notifications.clear()
    monkeypatch.setattr(xbmcgui, "Dialog", FakeDialog)
    monkeypatch.setattr(
        detail_mod.library, "get_item", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout"))
    )

    window = _make_window(detail_mod.DetailWindow, client=client, item_id="item-1")
    window.onInit()

    assert window.result is None
    assert window.closed
    assert FakeDialog.notifications
    assert "timeout" in FakeDialog.notifications[-1][1]


def test_search_window_shows_inline_error_and_stays_open(client, monkeypatch):
    monkeypatch.setattr(
        search_mod.library,
        "search_items",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("server unreachable")),
    )

    window = _make_window(search_mod.SearchWindow, client=client)
    window.onInit()
    window.getControl(search_mod.CTRL_QUERY).setText("alien")

    window._search()

    assert window.result is None
    assert not window.closed
    status = window.getControl(search_mod.CTRL_STATUS_LABEL).getLabel()
    assert "server unreachable" in status
