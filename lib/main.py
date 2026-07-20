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
from lib.jellyfin import client as client_mod
from lib.windows.browse import BrowseWindow
from lib.windows.detail import DetailWindow
from lib.windows.home import HomeWindow
from lib.windows.kodigui import LOG_PREFIX
from lib.windows.login import LoginWindow
from lib.windows.search import SearchWindow
from lib.windows.servers import ServerListWindow

ADDON = xbmcaddon.Addon()
ADDON_PATH = ADDON.getAddonInfo("path")
ADDON_VERSION = ADDON.getAddonInfo("version")

# Window 10000 (Home) is one of Kodi's numbered system windows, whose
# properties persist for the life of the Kodi process regardless of which
# script or skin set them - used here purely as a cross-instance lock, not
# for anything about the Home *window* itself. Kodi doesn't stop a script
# addon from being launched again (e.g. re-selecting it from the Programs
# menu, or a stray remote keypress) while a previous run is still on
# screen; without this guard, a second instance starts a second independent
# window/navigation stack, and quitting one leaves the other running
# underneath, which reads as "quitting doesn't work" - Back closes what's
# on screen but the addon is still there.
RUNNING_PROPERTY = "script.jellyfin.plex.running"
HOME_WINDOW_ID = 10000

# Item types that are containers to drill down into rather than play.
CONTAINER_TYPES = {"Series", "Season", "MusicArtist", "MusicAlbum", "BoxSet", "Folder"}


def _get_device_id():
    device_id = ADDON.getSetting("device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
        ADDON.setSetting("device_id", device_id)
    return device_id


def _get_request_timeout():
    """The addon's "Server request timeout" setting, in seconds - falls
    back to JellyfinClient's own default if unset or not a valid int (e.g.
    on first run before the setting has ever been saved)."""
    try:
        return int(ADDON.getSetting("request_timeout_seconds"))
    except (TypeError, ValueError):
        return client_mod.REQUEST_TIMEOUT_SECONDS


def _load_servers():
    return servers.deserialize(ADDON.getSetting("servers"))


def _save_servers(server_list):
    ADDON.setSetting("servers", servers.serialize(server_list))


def _get_active_server_id():
    return ADDON.getSetting("active_server_id")


def _set_active_server_id(server_id):
    ADDON.setSetting("active_server_id", server_id)


def _client_from_server(server):
    client = JellyfinClient(
        server.get("server_url", ""), _get_device_id(), client_version=ADDON_VERSION,
        request_timeout=_get_request_timeout(),
    )
    client.access_token = server.get("access_token")
    client.user_id = server.get("user_id")
    return client


def _load_saved_client():
    server_list = _load_servers()
    if not server_list:
        return None
    server = servers.find(server_list, _get_active_server_id())
    if not server:
        server = server_list[0]
        _set_active_server_id(server["id"])
    client = _client_from_server(server)
    if not client.is_authenticated():
        return None
    return client


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
        ADDON_PATH,
        default_server_url="",
        device_id=_get_device_id(),
        client_version=ADDON_VERSION,
    )
    if not result:
        return None
    client = JellyfinClient(
        result["server_url"], result["device_id"], client_version=ADDON_VERSION,
        request_timeout=_get_request_timeout(),
    )
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
                    item_type=result.get("item_type"),
                    resume_ticks=result.get("resume_ticks", 0),
                )
            except Exception as exc:  # noqa: BLE001 - surface playback failures, don't crash the addon
                xbmcgui.Dialog().notification("Jellyfin", f"Playback failed: {exc}")
            # Loop back to the detail page (e.g. to show updated resume state).


def _open_item(client, item_id, item_type, item_name, item_overview=""):
    if item_type in CONTAINER_TYPES:
        _browse_loop(client, item_id, item_name, parent_item_type=item_type,
                     parent_overview=item_overview)
    else:
        _detail_loop(client, item_id)


def _browse_loop(client, parent_id, title, parent_item_type=None, parent_overview=""):
    # Remembers which item was last opened from this screen so that, when
    # BrowseWindow.open() runs again after Back, it re-selects that same
    # item instead of resetting focus to the top of the list.
    select_item_id = None
    while True:
        result = BrowseWindow.open(
            ADDON_PATH, client=client, parent_id=parent_id, title=title,
            parent_item_type=parent_item_type, select_item_id=select_item_id,
            parent_overview=parent_overview,
        )
        if not result:
            return
        if result["action"] == "open":
            select_item_id = result["item_id"]
            _open_item(client, result["item_id"], result["item_type"], result["item_name"],
                       item_overview=result.get("item_overview", ""))
        elif result["action"] == "play_queue":
            try:
                player.play_queue(client, result["item_ids"], item_type=result.get("item_type"))
            except Exception as exc:  # noqa: BLE001 - surface playback failures, don't crash the addon
                xbmcgui.Dialog().notification("Jellyfin", f"Playback failed: {exc}")


def _search_loop(client):
    while True:
        result = SearchWindow.open(ADDON_PATH, client=client)
        if not result:
            return
        if result["action"] == "open":
            _open_item(client, result["item_id"], result["item_type"], result["item_name"],
                       item_overview=result.get("item_overview", ""))


def _confirm_quit():
    return xbmcgui.Dialog().yesno("Jellyfin", "Quit and return to Kodi?")


def _home_loop(client):
    """Runs Home for one server session. Returns a new client to switch the
    active server to, or None once the user backs all the way out."""
    # Remembers which hub-row tile was last opened so that, when
    # HomeWindow.open() runs again after Back, it re-selects that same tile
    # instead of resetting focus to the Libraries row.
    select_control_id = None
    select_item_id = None
    while True:
        result = HomeWindow.open(
            ADDON_PATH, client=client,
            select_control_id=select_control_id, select_item_id=select_item_id,
        )
        if not result:
            # Kodi force-closes any open window and expects the script to
            # exit promptly on shutdown - popping a confirmation dialog here
            # would sit forever waiting for a click that will never come
            # (no one's driving the UI during shutdown), which is exactly
            # what made this loop miss Kodi's 5-second "stop the script"
            # grace period and get killed instead of exiting cleanly.
            if xbmc.Monitor().abortRequested():
                return None
            if _confirm_quit():
                return None
            continue
        if result["action"] == "browse":
            select_control_id = result["control_id"]
            select_item_id = result["item_id"]
            _browse_loop(client, result["library_id"], result["library_name"])
        elif result["action"] == "open":
            select_control_id = result["control_id"]
            select_item_id = result["item_id"]
            _open_item(client, result["item_id"], result["item_type"], result["item_name"],
                       item_overview=result.get("item_overview", ""))
        elif result["action"] == "search":
            _search_loop(client)
        elif result["action"] == "servers":
            new_client = _manage_servers(client)
            if new_client is not None:
                return new_client


def run():
    home_window = xbmcgui.Window(HOME_WINDOW_ID)
    if home_window.getProperty(RUNNING_PROPERTY) == "true":
        xbmc.log(
            f"{LOG_PREFIX} Already running in another instance - refusing to start a second one",
            xbmc.LOGWARNING,
        )
        xbmcgui.Dialog().notification("Jellyfin", "Already running")
        return
    home_window.setProperty(RUNNING_PROPERTY, "true")
    try:
        _migrate_legacy_settings()
        client = _load_saved_client()
        if not client:
            client = _login()
        while client:
            client = _home_loop(client)
    finally:
        # Always clears, even on an unhandled exception - a permanent
        # lockout after a crash would be worse than the bug this guards
        # against.
        home_window.clearProperty(RUNNING_PROPERTY)
