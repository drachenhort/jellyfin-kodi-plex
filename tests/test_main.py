"""Tests for lib/main.py's active-server-label bookkeeping.

Only the new pure-logic pieces get unit tests here (matching this module's
existing convention: run()/_home_loop/_login/_manage_servers are orchestration
glue verified manually in real Kodi, not unit-tested). ADDON is a
module-level singleton in lib.main, so each test gets its own fresh stub via
monkeypatch to avoid leaking setSetting() calls between tests (same pattern
as tests/test_home.py).
"""

import xbmcaddon

import lib.main as main_mod
from lib import servers


def _make_addon(monkeypatch, server_list=None, active_server_id=""):
    addon = xbmcaddon.Addon()
    if server_list is not None:
        addon.setSetting("servers", servers.serialize(server_list))
    if active_server_id:
        addon.setSetting("active_server_id", active_server_id)
    monkeypatch.setattr(main_mod, "ADDON", addon)
    return addon


TOWER = {
    "id": "abc",
    "name": "Tower",
    "server_url": "http://192.168.1.5:8096",
    "access_token": "tok",
    "user_id": "uid",
}


def test_set_active_server_id_writes_info_for_known_server(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[TOWER])

    main_mod._set_active_server_id("abc")

    assert addon.getSetting("active_server_id") == "abc"
    assert addon.getSetting("active_server_info") == "Tower (http://192.168.1.5:8096)"


def test_set_active_server_id_writes_empty_info_for_unknown_server(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[])

    main_mod._set_active_server_id("does-not-exist")

    assert addon.getSetting("active_server_id") == "does-not-exist"
    assert addon.getSetting("active_server_info") == ""


def test_backfill_active_server_info_noop_when_already_set(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[TOWER], active_server_id="abc")
    addon.setSetting("active_server_info", "Custom (unchanged)")

    main_mod._backfill_active_server_info()

    assert addon.getSetting("active_server_info") == "Custom (unchanged)"


def test_backfill_active_server_info_populates_from_active_id(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[TOWER], active_server_id="abc")

    main_mod._backfill_active_server_info()

    assert addon.getSetting("active_server_info") == "Tower (http://192.168.1.5:8096)"


def test_backfill_active_server_info_noop_when_no_active_server(monkeypatch):
    addon = _make_addon(monkeypatch, server_list=[])

    main_mod._backfill_active_server_info()

    assert addon.getSetting("active_server_info") == ""
