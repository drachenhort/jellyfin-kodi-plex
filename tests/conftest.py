"""Shared pytest fixtures.

lib.jellyfin.* has no xbmc/xbmcgui imports, so it runs under plain pytest
with no stubbing needed. lib/windows/* and lib/player.py do import them -
tests/kodi_stubs/ provides minimal stand-ins registered into sys.modules
below, before any test file gets a chance to `import lib.windows.home` (or
similar) and have that statement's own `import xbmcgui` fail.
"""

import sys

import pytest

from tests.kodi_stubs import xbmc as fake_xbmc
from tests.kodi_stubs import xbmcaddon as fake_xbmcaddon
from tests.kodi_stubs import xbmcgui as fake_xbmcgui

sys.modules.setdefault("xbmc", fake_xbmc)
sys.modules.setdefault("xbmcgui", fake_xbmcgui)
sys.modules.setdefault("xbmcaddon", fake_xbmcaddon)

from lib.jellyfin.client import JellyfinClient


@pytest.fixture
def client():
    c = JellyfinClient("http://jellyfin.example:8096", device_id="test-device-id")
    c.access_token = "test-token"
    c.user_id = "test-user-id"
    return c


@pytest.fixture
def anon_client():
    return JellyfinClient("http://jellyfin.example:8096", device_id="test-device-id")
