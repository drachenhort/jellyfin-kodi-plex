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

from lib import player, servers
from lib.jellyfin import JellyfinClient, auth, system
from lib.windows.browse import BrowseWindow
from lib.windows.detail import DetailWindow
from lib.windows.home import HomeWindow
from lib.windows.login import LoginWindow
from lib.windows.search import SearchWindow
from lib.windows.servers import ServerListWindow

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


def _load_servers():
    return servers.deserialize(ADDON.getSetting("servers"))


def _save_servers(server_list):
    ADDON.setSetting("servers", servers.serialize(server_list))


def _get_active_server_id():
    return ADDON.getSetting("active_server_id")


def _set_active_server_id(server_id):
    ADDON.setSetting("active_server_id", server_id)


def _client_from_server(server):
    client = JellyfinClient(server["server_url"], _get_device_id())
    client.access_token = server["access_token"]
    client.user_id = server["user_id"]
    return client


def _load_saved_client():
    server_list = _load_servers()
    if not server_list:
        return None
    server = servers.find(server_list, _get_active_server_id())
    if not server:
        server = server_list[0]
        _set_active_server_id(server["id"])
    return _client_from_server(server)


def _migrate_legacy_settings():
    """One-time best-effort carry-over from the pre-multi-server single
    server_url/access_token/user_id settings, so an existing install doesn't
    get logged out by this update. Never raises: a failed migration just
    means one re-login, not data loss."""
    try:
        if ADDON.getSetting("servers"):
            return
        server_url = ADDON.getSetting("server_url")
        access_token = ADDON.getSetting("access_token")
        user_id = ADDON.getSetting("user_id")
        if not (server_url and access_token and user_id):
            return
        server_list, server_id = servers.upsert([], {
            "name": server_url,
            "server_url": server_url,
            "access_token": access_token,
            "user_id": user_id,
        })
        _save_servers(server_list)
        _set_active_server_id(server_id)
    except Exception:  # noqa: BLE001 - best-effort, never block startup
        pass


def _server_name(client):
    try:
        info = system.get_public_info(client)
        return (info or {}).get("ServerName") or client.server_url
    except Exception:  # noqa: BLE001 - name is cosmetic, never fail login over it
        return client.server_url


def _login():
    result = LoginWindow.open(
        ADDON_PATH, default_server_url="", device_id=_get_device_id()
    )
    if not result:
        return None
    client = JellyfinClient(result["server_url"], result["device_id"])
    client.access_token = result["access_token"]
    client.user_id = result["user_id"]

    server_list, server_id = servers.upsert(_load_servers(), {
        "name": _server_name(client),
        "server_url": client.server_url,
        "access_token": client.access_token,
        "user_id": client.user_id,
    })
    _save_servers(server_list)
    _set_active_server_id(server_id)
    return client


def _manage_servers(client):
    """Home's "Servers" action. Loops the server-management screen, letting
    the user add/remove/switch saved servers. Returns a new client to switch
    to, or None to resume the Home loop unchanged."""
    while True:
        server_list = _load_servers()
        active_id = _get_active_server_id()
        result = ServerListWindow.open(
            ADDON_PATH, servers=server_list, active_id=active_id
        )
        if not result:
            return None
        if result["action"] == "add":
            new_client = _login()
            if new_client is None:
                continue
            return new_client
        elif result["action"] == "remove":
            _save_servers(servers.remove(server_list, result["server_id"]))
            continue
        elif result["action"] == "select":
            if result["server_id"] == active_id:
                return None
            server = servers.find(server_list, result["server_id"])
            if not server:
                continue
            _set_active_server_id(server["id"])
            return _client_from_server(server)


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


def _search_loop(client):
    while True:
        result = SearchWindow.open(ADDON_PATH, client=client)
        if not result:
            return
        if result["action"] == "open":
            _open_item(client, result["item_id"], result["item_type"], result["item_name"])


def _confirm_quit():
    return xbmcgui.Dialog().yesno("Jellyfin", "Quit and return to Kodi?")


def _home_loop(client):
    """Runs Home for one server session. Returns a new client to switch the
    active server to, or None once the user backs all the way out."""
    while True:
        result = HomeWindow.open(ADDON_PATH, client=client)
        if not result:
            if _confirm_quit():
                return None
            continue
        if result["action"] == "browse":
            _browse_loop(client, result["library_id"], result["library_name"])
        elif result["action"] == "open":
            _open_item(client, result["item_id"], result["item_type"], result["item_name"])
        elif result["action"] == "search":
            _search_loop(client)
        elif result["action"] == "servers":
            new_client = _manage_servers(client)
            if new_client is not None:
                return new_client


def run():
    _migrate_legacy_settings()
    client = _load_saved_client()
    if not client:
        client = _login()
    while client:
        client = _home_loop(client)
