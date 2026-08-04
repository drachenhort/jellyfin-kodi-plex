"""Tests for LoginWindow's sign-in/Quick Connect flows.

Sign-in and Quick-Connect-initiate now run on a background thread rather
than inline on Kodi's GUI thread (see lib/windows/login.py) - these tests
call the worker methods (_do_sign_in/_initiate_and_poll_quick_connect)
directly to exercise that logic synchronously/deterministically rather
than racing a real thread, the same approach tests/test_home.py uses for
HomeWindow._load().
"""

import lib.jellyfin.client as client_mod
import lib.windows.login as login_mod
from tests.fakes import FakeRequests, FakeResponse


def _make_window():
    window = login_mod.LoginWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(default_server_url="", device_id="test-device-id")
    return window


def test_do_sign_in_finishes_on_success(monkeypatch):
    fake = FakeRequests([
        FakeResponse({"AccessToken": "abc123", "User": {"Id": "user-1", "Name": "steve"}}),
    ])
    monkeypatch.setattr(client_mod, "requests", fake)
    window = _make_window()

    window._do_sign_in("http://jellyfin.example:8096", "steve", "hunter2")

    assert window.result == {
        "server_url": "http://jellyfin.example:8096",
        "access_token": "abc123",
        "user_id": "user-1",
        "device_id": "test-device-id",
    }
    assert window.closed


def test_do_sign_in_reports_failure_status(monkeypatch):
    fake = FakeRequests([FakeResponse(status_code=401, text="Invalid credentials")])
    monkeypatch.setattr(client_mod, "requests", fake)
    window = _make_window()

    window._do_sign_in("http://jellyfin.example:8096", "steve", "wrong-password")

    assert window.result is None
    assert not window.closed
    assert "Sign in failed" in window.getControl(login_mod.CTRL_STATUS_LABEL).getLabel()


def test_do_sign_in_does_not_touch_controls_after_window_already_closed(monkeypatch):
    """User pressed Back while the request was in flight - doModal() has
    already returned by the time this finishes, so it must not touch a
    torn-down window's controls (or set a result nobody will read)."""
    fake = FakeRequests([FakeResponse(status_code=401, text="Invalid credentials")])
    monkeypatch.setattr(client_mod, "requests", fake)
    window = _make_window()
    window.close()  # simulate Back having already closed the window

    window._do_sign_in("http://jellyfin.example:8096", "steve", "wrong-password")

    assert window.result is None


def test_initiate_and_poll_quick_connect_shows_code_then_finishes(monkeypatch):
    fake = FakeRequests([
        FakeResponse({"Secret": "the-secret", "Code": "ABCD12"}),
        FakeResponse({"Authenticated": True}),
        FakeResponse({"AccessToken": "qc-token", "User": {"Id": "user-2", "Name": "quickuser"}}),
    ])
    monkeypatch.setattr(client_mod, "requests", fake)
    monkeypatch.setattr(login_mod.xbmc, "sleep", lambda ms: None)
    window = _make_window()

    window._initiate_and_poll_quick_connect("http://jellyfin.example:8096")

    assert window.getControl(login_mod.CTRL_QUICK_CONNECT_CODE).getLabel() == "ABCD12"
    assert window.result["access_token"] == "qc-token"
    assert window.closed


def test_initiate_and_poll_quick_connect_does_not_touch_controls_after_close(monkeypatch):
    """Same race as sign-in, but for the initiate call specifically - a
    slow/laggy server answering after the user already backed out must not
    write the Quick Connect code label into a torn-down window."""
    fake = FakeRequests([FakeResponse({"Secret": "the-secret", "Code": "ABCD12"})])
    monkeypatch.setattr(client_mod, "requests", fake)
    window = _make_window()
    window.close()

    window._initiate_and_poll_quick_connect("http://jellyfin.example:8096")

    assert window.getControl(login_mod.CTRL_QUICK_CONNECT_CODE).getLabel() == ""


def test_poll_quick_connect_does_not_touch_controls_after_stop_requested(monkeypatch):
    """_quick_connect_stop is set by close() - a poll response arriving just
    after Back must not call _finish()/_set_status() on a torn-down window."""
    fake = FakeRequests([FakeResponse({"Authenticated": True})])
    monkeypatch.setattr(client_mod, "requests", fake)
    window = _make_window()
    client = client_mod.JellyfinClient("http://jellyfin.example:8096", device_id="test-device-id")
    window._quick_connect_stop.set()

    window._poll_quick_connect(client, "the-secret")

    assert window.result is None
    assert not window.closed
