"""Shared pytest fixtures.

lib.jellyfin.* has no xbmc/xbmcgui imports, so it runs under plain pytest
with no stubbing needed. This file will grow xbmc/xbmcgui stub modules once
tests are added for lib/windows/* and lib/player.py.
"""

import pytest

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
