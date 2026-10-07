"""The Clean Up screen's "to be deleted" list: movie ids the user has marked
for deletion but not deleted yet, kept per server/user so it survives
closing the addon.

Pure JSON (de)serialization over a single hidden addon setting, no xbmc*
imports - same split as lib/servers.py: the window owns reading/writing the
setting, this module only knows the format. Stored as {key: [item ids]}
where key identifies one server login (see queue_key)."""

import json


def queue_key(server_url: str, user_id: str) -> str:
    return f"{server_url.rstrip('/').lower()}|{user_id}"


def _deserialize(raw_json: str) -> dict:
    if not raw_json:
        return {}
    try:
        data = json.loads(raw_json)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def load(raw_json: str, key: str) -> list:
    """The queued ids for `key`, in the order they were added."""
    ids = _deserialize(raw_json).get(key)
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


def save(raw_json: str, key: str, ids: list) -> str:
    """`raw_json` with `key`'s queue replaced by `ids` - other servers'
    queues are kept untouched. An empty queue drops the key entirely."""
    data = _deserialize(raw_json)
    if ids:
        data[key] = list(ids)
    else:
        data.pop(key, None)
    return json.dumps(data)
