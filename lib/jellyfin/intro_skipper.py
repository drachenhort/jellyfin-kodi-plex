"""Client for the (optional, server-side) Intro Skipper plugin
(https://github.com/intro-skipper/intro-skipper). Not part of stock
Jellyfin - a server without the plugin installed 404s on this endpoint,
which is treated the same as "no segments for this episode" rather than
an error, so playback works identically whether or not the plugin is
present.
"""

from lib.jellyfin.client import JellyfinApiError

# The plugin has shipped both a "Start"/"End" and an "IntroStart"/"IntroEnd"
# key naming across releases - segment_bounds() below accepts either so this
# client doesn't need to track which plugin version a given server runs.
_START_KEYS = ("IntroStart", "Start")
_END_KEYS = ("IntroEnd", "End")


def get_segments(client, item_id):
    """GET /Episode/{itemId}/IntroSkipperSegments - a dict keyed by segment
    type ("Introduction", "Credits"), or {} if the plugin isn't installed
    or this episode has no detected segments."""
    try:
        result = client.get(f"/Episode/{item_id}/IntroSkipperSegments")
    except JellyfinApiError as exc:
        if exc.status_code == 404:
            return {}
        raise
    return result or {}


def segment_bounds(segments, segment_type):
    """Returns (start_seconds, end_seconds) for the given segment type
    ("Introduction", "Credits"), or None if absent/malformed."""
    segment = (segments or {}).get(segment_type)
    if not segment:
        return None
    start = end = None
    for key in _START_KEYS:
        if key in segment:
            start = segment[key]
            break
    for key in _END_KEYS:
        if key in segment:
            end = segment[key]
            break
    if start is None or end is None or end <= start:
        return None
    return float(start), float(end)
