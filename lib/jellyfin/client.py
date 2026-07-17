"""Thin HTTP client for the Jellyfin REST API.

No xbmc/xbmcgui imports here on purpose: this module (and the rest of the
lib.jellyfin package) must be importable and testable with plain pytest,
outside of a running Kodi process.
"""

import requests

CLIENT_NAME = "Jellyfin Plex-style Kodi Client"
# Fallback only - real callers (lib/main.py) pass the addon's actual version
# from addon.xml via getAddonInfo("version"), so this constant doesn't need
# to be bumped by hand and can't drift from the version Jellyfin displays.
CLIENT_VERSION = "0.0.0"

# A large real library (seen in practice with Music: thousands of tracks)
# can take noticeably longer than a quick request to enumerate or compute
# "recently added" for, especially before Jellyfin's own caches are warm.
# lib/windows/*.py now runs this call on a background thread rather than
# Kodi's GUI thread, so a generous timeout here no longer costs a frozen
# UI - it's safe to give a slow real query more room before giving up.
REQUEST_TIMEOUT_SECONDS = 60


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

    def __init__(self, server_url, device_id, device_name="Kodi", client_version=CLIENT_VERSION):
        self.server_url = server_url.rstrip("/")
        self.device_id = device_id
        self.device_name = device_name
        self.client_version = client_version
        self.access_token = None
        self.user_id = None

    def is_authenticated(self):
        return bool(self.access_token and self.user_id)

    def auth_header(self):
        parts = [
            f'Client="{CLIENT_NAME}"',
            f'Device="{self.device_name}"',
            f'DeviceId="{self.device_id}"',
            f'Version="{self.client_version}"',
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

    def delete(self, path, params=None):
        return self._request("DELETE", path, params=params)

    def _request(self, method, path, json=None, params=None):
        response = requests.request(
            method,
            self.build_url(path),
            headers=self._headers(),
            json=json,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise JellyfinApiError(response.status_code, response.text)
        if not response.content:
            return None
        return response.json()
