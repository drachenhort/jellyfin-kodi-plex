"""Thin HTTP client for the Jellyfin REST API.

No xbmc/xbmcgui imports here on purpose: this module (and the rest of the
lib.jellyfin package) must be importable and testable with plain pytest,
outside of a running Kodi process.
"""

import requests

CLIENT_NAME = "Jellyfin Plex-style Kodi Client"
CLIENT_VERSION = "0.1.0"


class JellyfinApiError(Exception):
    def __init__(self, status_code, message):
        super().__init__(f"Jellyfin API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class JellyfinClient:
    """Holds server/session state and performs authenticated requests.

    Construct once per server connection; `access_token`/`user_id` start
    unset and get filled in by lib.jellyfin.auth once login succeeds.
    """

    def __init__(self, server_url, device_id, device_name="Kodi"):
        self.server_url = server_url.rstrip("/")
        self.device_id = device_id
        self.device_name = device_name
        self.access_token = None
        self.user_id = None

    def is_authenticated(self):
        return bool(self.access_token and self.user_id)

    def auth_header(self):
        parts = [
            f'Client="{CLIENT_NAME}"',
            f'Device="{self.device_name}"',
            f'DeviceId="{self.device_id}"',
            f'Version="{CLIENT_VERSION}"',
        ]
        if self.access_token:
            parts.append(f'Token="{self.access_token}"')
        return "MediaBrowser " + ", ".join(parts)

    def _headers(self):
        return {
            "Authorization": self.auth_header(),
            "Accept": "application/json",
        }

    def build_url(self, path):
        return f"{self.server_url}{path}"

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def post(self, path, json=None, params=None):
        return self._request("POST", path, json=json, params=params)

    def _request(self, method, path, json=None, params=None):
        response = requests.request(
            method,
            self.build_url(path),
            headers=self._headers(),
            json=json,
            params=params,
            timeout=15,
        )
        if response.status_code >= 400:
            raise JellyfinApiError(response.status_code, response.text)
        if not response.content:
            return None
        return response.json()
