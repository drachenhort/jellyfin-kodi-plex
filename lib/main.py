"""App bootstrap and window navigation.

Each window's open() blocks (via doModal()) until it closes, so the natural
way to build a "stack" of screens — where Back returns to the previous
screen instead of exiting the addon — is nested loops: showing a screen
again after a deeper screen closes with no result (Back) is just looping;
moving to a deeper screen is just a nested function call. Only backing out
of the root Home loop actually ends the script.
"""

import uuid

import xbmc
import xbmcaddon
import xbmcgui

from lib import player
from lib.jellyfin import JellyfinClient, auth
from lib.windows.browse import BrowseWindow
from lib.windows.detail import DetailWindow
from lib.windows.home import HomeWindow
from lib.windows.login import LoginWindow

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo("path")

# Item types that are containers to drill down into rather than play.
CONTAINER_TYPES = {"Series", "Season", "MusicArtist", "MusicAlbum", "BoxSet", "Folder"}


def _get_device_id():
    device_id = ADDON.getSetting("device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
        ADDON.setSetting("device_id", device_id)
    return device_id


def _load_saved_client():
    server_url = ADDON.getSetting("server_url")
    access_token = ADDON.getSetting("access_token")
    user_id = ADDON.getSetting("user_id")
    if not (server_url and access_token and user_id):
        return None
    client = JellyfinClient(server_url, _get_device_id())
    client.access_token = access_token
    client.user_id = user_id
    return client


def _save_client(client):
    ADDON.setSetting("server_url", client.server_url)
    ADDON.setSetting("access_token", client.access_token)
    ADDON.setSetting("user_id", client.user_id)


def _login():
    default_server_url = ADDON.getSetting("server_url")
    result = LoginWindow.open(
        ADDON_PATH, default_server_url=default_server_url, device_id=_get_device_id()
    )
    if not result:
        return None
    client = JellyfinClient(result["server_url"], result["device_id"])
    client.access_token = result["access_token"]
    client.user_id = result["user_id"]
    _save_client(client)
    return client


def _detail_loop(client, item_id):
    while True:
        result = DetailWindow.open(ADDON_PATH, client=client, item_id=item_id)
        if not result:
            return
        if result["action"] == "play":
            try:
                player.play_item(
                    client,
                    result["item_id"],
                    resume_ticks=result.get("resume_ticks", 0),
                    title=result.get("title", ""),
                )
            except Exception as exc:  # noqa: BLE001 - surface playback failures, don't crash the addon
                xbmcgui.Dialog().notification("Jellyfin", f"Playback failed: {exc}")
            # Loop back to the detail page (e.g. to show updated resume state).


def _open_item(client, item_id, item_type, item_name):
    if item_type in CONTAINER_TYPES:
        _browse_loop(client, item_id, item_name)
    else:
        _detail_loop(client, item_id)


def _browse_loop(client, parent_id, title):
    while True:
        result = BrowseWindow.open(ADDON_PATH, client=client, parent_id=parent_id, title=title)
        if not result:
            return
        if result["action"] == "open":
            _open_item(client, result["item_id"], result["item_type"], result["item_name"])


def _home_loop(client):
    while True:
        result = HomeWindow.open(ADDON_PATH, client=client)
        if not result:
            return
        if result["action"] == "browse":
            _browse_loop(client, result["library_id"], result["library_name"])
        elif result["action"] == "open":
            _open_item(client, result["item_id"], result["item_type"], result["item_name"])


def run():
    client = _load_saved_client()
    if not client:
        client = _login()
    if not client:
        return
    _home_loop(client)
