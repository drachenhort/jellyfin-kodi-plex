"""Saved multi-server list: plain-dict CRUD over a JSON blob.

No xbmc*/xbmcgui imports here on purpose, same rule as lib/jellyfin/* — this
must be importable and testable with plain pytest. lib/main.py owns actually
reading/writing the JSON string from/to an addon setting; this module only
knows how to (de)serialize it and manipulate the list.

A server entry is {"id", "name", "server_url", "access_token", "user_id"}.
device_id is deliberately not part of it — one Kodi install has a single
device_id shared across every saved server.
"""

import json
import uuid


def deserialize(raw_json):
    """Parse the `servers` setting string. Empty/invalid/non-list -> []."""
    if not raw_json:
        return []
    try:
        data = json.loads(raw_json)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def serialize(servers):
    return json.dumps(servers)


def find(servers, server_id):
    for server in servers:
        if server.get("id") == server_id:
            return server
    return None


def upsert(servers, server):
    """Add `server` (a dict without "id") to `servers`, or update in place.

    Matches an existing entry by server_url (case-insensitive) so re-logging
    in to an already-saved server refreshes its token/user/name instead of
    creating a duplicate. Returns (new_list, server_id).
    """
    url = server["server_url"]
    for existing in servers:
        if existing["server_url"].lower() == url.lower():
            existing_id = existing["id"]
            existing.update(server)
            existing["id"] = existing_id
            return list(servers), existing_id

    new_server = dict(server)
    new_server["id"] = str(uuid.uuid4())
    return servers + [new_server], new_server["id"]


def remove(servers, server_id):
    return [server for server in servers if server.get("id") != server_id]
