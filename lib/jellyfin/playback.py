"""Playback resolution and progress reporting.

get_playback_info() tells us whether Jellyfin will DirectPlay/DirectStream
the item or transcode it, and gives us the URL to actually play. The
report_* functions push position/state back so watched-state (resume point,
played flag) stays in sync with other Jellyfin clients.
"""

import uuid

# Minimal device profile: claim support for the common direct-play containers
# so the server prefers DirectPlay over transcoding when it can.
DEFAULT_DEVICE_PROFILE = {
    "MaxStreamingBitrate": 120000000,
    "DirectPlayProfiles": [
        {"Container": "mp4,m4v,mkv,avi", "Type": "Video"},
        {"Container": "mp3,flac,m4a,aac,ogg,wav,wma", "Type": "Audio"},
    ],
    "TranscodingProfiles": [
        {"Container": "ts", "Type": "Video", "AudioCodec": "aac,mp3", "VideoCodec": "h264", "Context": "Streaming"},
        {"Container": "mp3", "Type": "Audio", "AudioCodec": "mp3", "Context": "Streaming"},
    ],
}


def get_playback_info(client, item_id, device_profile=None):
    """POST /Items/{itemId}/PlaybackInfo. Returns the raw PlaybackInfoResponse."""
    return client.post(
        f"/Items/{item_id}/PlaybackInfo",
        json={"DeviceProfile": device_profile or DEFAULT_DEVICE_PROFILE},
        params={"UserId": client.user_id},
    )


def stream_url(client, item_id, media_source, item_type=None):
    """Build the direct playback URL for a MediaSourceInfo from PlaybackInfo.

    Jellyfin serves audio items (Track/"Audio") from a separate /Audio/
    endpoint rather than /Videos/ - passing the wrong one 404s.
    """
    container = media_source.get("Container", "mp4")
    play_session_id = str(uuid.uuid4())
    endpoint = "Audio" if item_type == "Audio" else "Videos"
    return (
        client.build_url(f"/{endpoint}/{item_id}/stream.{container}")
        + f"?static=true&mediaSourceId={media_source['Id']}"
        f"&api_key={client.access_token}&PlaySessionId={play_session_id}"
    ), play_session_id


def report_playback_start(client, item_id, play_session_id, position_ticks=0):
    client.post(
        "/Sessions/Playing",
        json={
            "ItemId": item_id,
            "PlaySessionId": play_session_id,
            "PositionTicks": position_ticks,
        },
    )


def report_playback_progress(client, item_id, play_session_id, position_ticks, is_paused=False):
    client.post(
        "/Sessions/Playing/Progress",
        json={
            "ItemId": item_id,
            "PlaySessionId": play_session_id,
            "PositionTicks": position_ticks,
            "IsPaused": is_paused,
        },
    )


def report_playback_stopped(client, item_id, play_session_id, position_ticks):
    client.post(
        "/Sessions/Playing/Stopped",
        json={
            "ItemId": item_id,
            "PlaySessionId": play_session_id,
            "PositionTicks": position_ticks,
        },
    )
