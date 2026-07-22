"""Tests for lib.main.run()'s singleton guard: Kodi doesn't stop a script
addon being launched again while a previous run is still on screen, and a
second independent instance meant quitting one left the other running
underneath - see RUNNING_PROPERTY's docstring in lib/main.py.
"""

import xbmc
import xbmcgui

import lib.main as main_mod


class _AbortMonitor:
    def abortRequested(self):
        return True


# -- _home_loop: skip the quit confirmation dialog on Kodi shutdown ---------

def test_home_loop_returns_without_confirm_dialog_on_abort(monkeypatch):
    monkeypatch.setattr(main_mod.HomeWindow, "open", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(xbmc, "Monitor", _AbortMonitor)

    def fail_if_called():
        raise AssertionError("must not prompt for confirmation during shutdown")

    monkeypatch.setattr(main_mod, "_confirm_quit", fail_if_called)

    assert main_mod._home_loop(client=object()) is None


def test_home_loop_still_confirms_quit_when_not_aborting(monkeypatch):
    monkeypatch.setattr(main_mod.HomeWindow, "open", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(main_mod, "_confirm_quit", lambda: True)

    assert main_mod._home_loop(client=object()) is None


def test_home_loop_still_loops_when_quit_declined_and_not_aborting(monkeypatch):
    opens = []

    def fake_open(*a, **k):
        opens.append(1)
        return None if len(opens) == 1 else {"action": "servers"}

    monkeypatch.setattr(main_mod.HomeWindow, "open", staticmethod(fake_open))
    monkeypatch.setattr(main_mod, "_confirm_quit", lambda: False)
    monkeypatch.setattr(main_mod, "_manage_servers", lambda client: "new-client")

    assert main_mod._home_loop(client=object()) == "new-client"
    assert len(opens) == 2


def test_home_loop_does_not_reopen_home_if_abort_fires_during_confirm_dialog(monkeypatch):
    """Reproduces a real-device crash: Kodi can force the quit-confirmation
    dialog closed mid-shutdown, handing back a falsy "No" just as abort
    becomes true - looping back into HomeWindow.open() at that exact moment
    crashed with "maximum number of windows reached" (Kodi already
    mid-teardown, refusing to construct a new window)."""
    opens = []

    def fail_if_reopened(*a, **k):
        opens.append(1)
        if len(opens) > 1:
            raise AssertionError("must not reopen Home once abort has fired")
        return None

    monkeypatch.setattr(main_mod.HomeWindow, "open", staticmethod(fail_if_reopened))

    class _AbortAfterDialogMonitor:
        checks = 0

        def abortRequested(self):
            _AbortAfterDialogMonitor.checks += 1
            # False for the pre-open() and post-close() checks, True only
            # once _confirm_quit() itself has been (attempted to be) shown.
            return _AbortAfterDialogMonitor.checks > 2

    monkeypatch.setattr(xbmc, "Monitor", _AbortAfterDialogMonitor)
    monkeypatch.setattr(main_mod, "_confirm_quit", lambda: False)

    assert main_mod._home_loop(client=object()) is None


# -- _detail_loop: opening a "More Like This" item nests and returns -------

def test_detail_loop_opens_a_similar_item_then_returns_to_the_original(monkeypatch):
    calls = []

    def fake_open(addon_path, client=None, item_id=None):
        calls.append(item_id)
        if item_id == "item-1" and calls.count("item-1") == 1:
            return {"action": "open", "item_id": "item-2", "item_type": "Movie", "item_name": "Other"}
        return None

    monkeypatch.setattr(main_mod.DetailWindow, "open", staticmethod(fake_open))

    main_mod._detail_loop(client=object(), item_id="item-1")

    # item-1 opened, clicked through to item-2 (nested _detail_loop), backed
    # out of item-2 straight to None, then the outer loop re-shows item-1
    # (the same "loop back to the detail page" pattern the Play action
    # already uses) before finally backing out of that too.
    assert calls == ["item-1", "item-2", "item-1"]


def test_run_refuses_to_start_a_second_instance(monkeypatch):
    calls = []
    monkeypatch.setattr(main_mod, "_migrate_legacy_settings", lambda: calls.append("migrate"))

    home_window = xbmcgui.Window(main_mod.HOME_WINDOW_ID)
    home_window.setProperty(main_mod.RUNNING_PROPERTY, "true")
    try:
        main_mod.run()
    finally:
        home_window.clearProperty(main_mod.RUNNING_PROPERTY)

    assert calls == []


def test_run_sets_and_clears_the_running_property_on_normal_exit(monkeypatch):
    home_window = xbmcgui.Window(main_mod.HOME_WINDOW_ID)
    home_window.clearProperty(main_mod.RUNNING_PROPERTY)

    seen_during_run = []
    monkeypatch.setattr(main_mod, "_migrate_legacy_settings", lambda: None)
    monkeypatch.setattr(
        main_mod, "_load_saved_client",
        lambda: seen_during_run.append(home_window.getProperty(main_mod.RUNNING_PROPERTY)) or None,
    )
    monkeypatch.setattr(main_mod, "_login", lambda: None)

    main_mod.run()

    assert seen_during_run == ["true"]
    assert home_window.getProperty(main_mod.RUNNING_PROPERTY) == ""


def test_run_clears_the_running_property_even_on_an_unhandled_exception(monkeypatch):
    home_window = xbmcgui.Window(main_mod.HOME_WINDOW_ID)
    home_window.clearProperty(main_mod.RUNNING_PROPERTY)

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(main_mod, "_migrate_legacy_settings", boom)

    try:
        main_mod.run()
    except RuntimeError:
        pass

    assert home_window.getProperty(main_mod.RUNNING_PROPERTY) == ""


# -- run(): a "maximum number of windows reached" RuntimeError from a window
# loop is a shutdown-teardown race (see lib/windows/kodigui.py's open()
# docstring), not a bug - caught exactly once here rather than retried.

def test_run_treats_window_limit_runtime_error_as_a_clean_exit_when_aborting(monkeypatch):
    home_window = xbmcgui.Window(main_mod.HOME_WINDOW_ID)
    home_window.clearProperty(main_mod.RUNNING_PROPERTY)

    monkeypatch.setattr(main_mod, "_migrate_legacy_settings", lambda: None)
    monkeypatch.setattr(main_mod, "_load_saved_client", lambda: "some-client")

    calls = []

    def fake_home_loop(client):
        calls.append(client)
        raise RuntimeError("maximum number of windows reached")

    monkeypatch.setattr(main_mod, "_home_loop", fake_home_loop)
    monkeypatch.setattr(xbmc, "Monitor", _AbortMonitor)

    main_mod.run()  # must not raise

    assert calls == ["some-client"]  # never retried
    assert home_window.getProperty(main_mod.RUNNING_PROPERTY) == ""


def test_run_reraises_window_limit_runtime_error_when_not_aborting(monkeypatch):
    home_window = xbmcgui.Window(main_mod.HOME_WINDOW_ID)
    home_window.clearProperty(main_mod.RUNNING_PROPERTY)

    monkeypatch.setattr(main_mod, "_migrate_legacy_settings", lambda: None)
    monkeypatch.setattr(main_mod, "_load_saved_client", lambda: "some-client")

    def fake_home_loop(client):
        raise RuntimeError("maximum number of windows reached")

    monkeypatch.setattr(main_mod, "_home_loop", fake_home_loop)

    try:
        main_mod.run()
        assert False, "expected RuntimeError to propagate"
    except RuntimeError:
        pass

    assert home_window.getProperty(main_mod.RUNNING_PROPERTY) == ""


# -- _load_saved_client: falls back to another saved server when the active
# one can't be reached (down, unreachable, 5xx), and always notifies why.

def _stub_server(name, server_id):
    return {
        "id": server_id, "name": name, "server_url": f"http://{name}",
        "access_token": "tok", "user_id": "user",
    }


def test_load_saved_client_uses_active_server_when_reachable(monkeypatch):
    server = _stub_server("primary", "s1")
    monkeypatch.setattr(main_mod, "_load_servers", lambda: [server])
    monkeypatch.setattr(main_mod, "_get_active_server_id", lambda: "s1")

    def fake_probe(srv):
        assert srv["id"] == "s1"
        client = object.__new__(main_mod.JellyfinClient)
        client.is_authenticated = lambda: True
        return client, None

    monkeypatch.setattr(main_mod, "_probe_server", fake_probe)

    notifications = []
    monkeypatch.setattr(
        xbmcgui.Dialog, "notification",
        lambda self, *a, **k: notifications.append(a),
    )

    result = main_mod._load_saved_client()

    assert result is not None
    assert notifications == []  # no notification when the active server just works


def test_load_saved_client_falls_back_and_notifies_why(monkeypatch):
    primary = _stub_server("primary", "s1")
    backup = _stub_server("backup", "s2")
    monkeypatch.setattr(main_mod, "_load_servers", lambda: [primary, backup])
    monkeypatch.setattr(main_mod, "_get_active_server_id", lambda: "s1")

    set_ids = []
    monkeypatch.setattr(main_mod, "_set_active_server_id", set_ids.append)

    def fake_probe(srv):
        if srv["id"] == "s1":
            return None, "503 Service Unavailable"
        client = object.__new__(main_mod.JellyfinClient)
        client.is_authenticated = lambda: True
        return client, None

    monkeypatch.setattr(main_mod, "_probe_server", fake_probe)

    notifications = []
    monkeypatch.setattr(
        xbmcgui.Dialog, "notification",
        lambda self, *a, **k: notifications.append(a),
    )

    result = main_mod._load_saved_client()

    assert result is not None
    assert set_ids == ["s2"]
    assert len(notifications) == 1
    message = notifications[0][1]
    assert "primary" in message and "503 Service Unavailable" in message and "backup" in message


def test_load_saved_client_notifies_and_returns_none_when_nothing_reachable(monkeypatch):
    primary = _stub_server("primary", "s1")
    backup = _stub_server("backup", "s2")
    monkeypatch.setattr(main_mod, "_load_servers", lambda: [primary, backup])
    monkeypatch.setattr(main_mod, "_get_active_server_id", lambda: "s1")
    monkeypatch.setattr(main_mod, "_probe_server", lambda srv: (None, "connection refused"))

    notifications = []
    monkeypatch.setattr(
        xbmcgui.Dialog, "notification",
        lambda self, *a, **k: notifications.append(a),
    )

    result = main_mod._load_saved_client()

    assert result is None
    assert len(notifications) == 1
    assert "primary" in notifications[0][1] and "connection refused" in notifications[0][1]


def test_probe_server_returns_reason_on_api_error(monkeypatch):
    server = _stub_server("primary", "s1")
    monkeypatch.setattr(
        main_mod.system, "get_public_info",
        lambda client: (_ for _ in ()).throw(main_mod.client_mod.JellyfinApiError(503, "Service Unavailable")),
    )

    client, error = main_mod._probe_server(server)

    assert client is None
    assert "503" in error
