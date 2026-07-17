"""Login window: manual server URL entry (autofilled from LAN autodiscovery
when a server is found, see lib/jellyfin/discovery.py), then Quick Connect
(preferred) or a username/password fallback.

On success, self.result is a dict with server_url/access_token/user_id/
device_id so lib/main.py can persist it via xbmcaddon settings and build a
JellyfinClient for the rest of the session.
"""

import threading
import uuid

import xbmc
import xbmcgui

from lib.jellyfin import JellyfinClient, auth, discovery
from lib.jellyfin.client import CLIENT_VERSION
from lib.windows.kodigui import ControlledWindow

CTRL_SERVER_URL = 101
CTRL_USERNAME = 102
CTRL_PASSWORD = 103
CTRL_SIGN_IN = 104
CTRL_QUICK_CONNECT = 105
CTRL_STATUS_LABEL = 106
CTRL_QUICK_CONNECT_CODE = 107
CTRL_DISCOVERED_SERVERS = 108

QUICK_CONNECT_POLL_SECONDS = 2
QUICK_CONNECT_TIMEOUT_SECONDS = 300


class LoginWindow(ControlledWindow):
    xmlFile = "script-jellyfin-login.xml"

    def setup(self, default_server_url="", device_id=None, client_version=None, **kwargs):
        super().setup(**kwargs)
        self.default_server_url = default_server_url
        self.device_id = device_id or str(uuid.uuid4())
        self.client_version = client_version or CLIENT_VERSION
        self._quick_connect_thread = None
        self._quick_connect_stop = threading.Event()
        self._discovery_stop = threading.Event()

    def onInit(self):
        if self.default_server_url:
            self.getControl(CTRL_SERVER_URL).setText(self.default_server_url)
        self.setFocusId(CTRL_SERVER_URL)
        self._start_discovery()

    def handle_click(self, control_id):
        if control_id == CTRL_SIGN_IN:
            self._sign_in_with_password()
        elif control_id == CTRL_QUICK_CONNECT:
            self._start_quick_connect()
        elif control_id == CTRL_DISCOVERED_SERVERS:
            self._select_discovered_server()

    def _start_discovery(self):
        thread = threading.Thread(target=self._discover_servers, daemon=True)
        thread.start()

    def _discover_servers(self):
        servers = discovery.discover_servers()
        if self._discovery_stop.is_set():
            return
        control = self.getControl(CTRL_DISCOVERED_SERVERS)
        control.reset()
        for server in servers:
            li = xbmcgui.ListItem(label=server.get("Name", server.get("Address", "")))
            li.setProperty("server_url", server.get("Address", ""))
            control.addItem(li)

    def _select_discovered_server(self):
        selected = self.getControl(CTRL_DISCOVERED_SERVERS).getSelectedItem()
        if not selected:
            return
        self.getControl(CTRL_SERVER_URL).setText(selected.getProperty("server_url"))
        self.setFocusId(CTRL_USERNAME)

    def _set_status(self, text):
        self.getControl(CTRL_STATUS_LABEL).setLabel(text)

    def _server_url(self):
        return self.getControl(CTRL_SERVER_URL).getText().strip()

    def _sign_in_with_password(self):
        server_url = self._server_url()
        username = self.getControl(CTRL_USERNAME).getText().strip()
        password = self.getControl(CTRL_PASSWORD).getText()
        if not server_url or not username:
            self._set_status("Server URL and username are required")
            return

        client = JellyfinClient(server_url, self.device_id, client_version=self.client_version)
        try:
            auth.authenticate_by_name(client, username, password)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            self._set_status(f"Sign in failed: {exc}")
            return

        self._finish(client)

    def _start_quick_connect(self):
        server_url = self._server_url()
        if not server_url:
            self._set_status("Enter a server URL first")
            return
        if self._quick_connect_thread and self._quick_connect_thread.is_alive():
            return

        client = JellyfinClient(server_url, self.device_id, client_version=self.client_version)
        try:
            initiated = auth.initiate_quick_connect(client)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Quick Connect unavailable: {exc}")
            return

        code = initiated["Code"]
        secret = initiated["Secret"]
        self.getControl(CTRL_QUICK_CONNECT_CODE).setLabel(code)
        self._set_status("Enter this code in another Jellyfin app to sign in")

        self._quick_connect_stop.clear()
        self._quick_connect_thread = threading.Thread(
            target=self._poll_quick_connect, args=(client, secret), daemon=True
        )
        self._quick_connect_thread.start()

    def _poll_quick_connect(self, client, secret):
        waited = 0
        while waited < QUICK_CONNECT_TIMEOUT_SECONDS:
            if self._quick_connect_stop.is_set():
                return
            try:
                if auth.poll_quick_connect(client, secret):
                    auth.authenticate_with_quick_connect(client, secret)
                    self._finish(client)
                    return
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"Quick Connect failed: {exc}")
                return
            xbmc.sleep(QUICK_CONNECT_POLL_SECONDS * 1000)
            waited += QUICK_CONNECT_POLL_SECONDS
        self._set_status("Quick Connect code expired, try again")

    def _finish(self, client):
        self.result = {
            "server_url": client.server_url,
            "access_token": client.access_token,
            "user_id": client.user_id,
            "device_id": self.device_id,
        }
        self.close()

    def close(self):
        self._quick_connect_stop.set()
        self._discovery_stop.set()
        super().close()
