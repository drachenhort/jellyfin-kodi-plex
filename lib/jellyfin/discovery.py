"""Jellyfin server autodiscovery: a UDP broadcast protocol inherited from
Emby/MediaBrowser. No xbmc*/xbmcgui imports here on purpose, same rule as the
rest of lib.jellyfin — this must be importable and testable with plain
pytest, outside of a running Kodi process.
"""

import json
import socket
import time

DISCOVERY_MESSAGE = b"who is JellyfinServer?"
DISCOVERY_PORT = 7359
DEFAULT_TIMEOUT = 2.0


def discover_servers(timeout=DEFAULT_TIMEOUT):
    """Broadcast a discovery request and collect replies for `timeout` seconds.

    Returns a list of {"Address": ..., "Id": ..., "Name": ...} dicts, one per
    responding server, deduplicated by Id. Any datagram that isn't valid JSON
    (or lacks an Id) is silently ignored rather than raising.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    servers = {}
    try:
        sock.sendto(DISCOVERY_MESSAGE, ("255.255.255.255", DISCOVERY_PORT))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                break
            try:
                info = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            server_id = info.get("Id")
            if server_id:
                servers[server_id] = info
    finally:
        sock.close()
    return list(servers.values())
