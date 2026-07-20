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
