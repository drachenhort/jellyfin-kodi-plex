"""Image URL construction — no HTTP calls, just URL building.

Falls back to a parent item's art when the item itself has none, since e.g.
episodes usually don't carry their own Primary image.
"""

PRIMARY = "Primary"
BACKDROP = "Backdrop"
THUMB = "Thumb"


def image_url(client, item_id, image_type=PRIMARY, tag=None, max_width=None, index=None):
    path = f"/Items/{item_id}/Images/{image_type}"
    if index is not None:
        path += f"/{index}"
    params = []
    if tag:
        params.append(f"tag={tag}")
    if max_width:
        params.append(f"maxWidth={max_width}")
    if client.access_token:
        params.append(f"api_key={client.access_token}")
    url = client.build_url(path)
    if params:
        url += "?" + "&".join(params)
    return url


def primary_image_url(client, item, max_width=None):
    """Poster art for `item`, falling back to its series' (or, for a music
    track, its album's) art if needed - tracks essentially never carry their
    own Primary image, only AlbumId/AlbumPrimaryImageTag."""
    tag = item.get("ImageTags", {}).get(PRIMARY)
    if tag:
        return image_url(client, item["Id"], PRIMARY, tag=tag, max_width=max_width)
    series_id = item.get("SeriesId")
    series_tag = item.get("SeriesPrimaryImageTag")
    if series_id and series_tag:
        return image_url(client, series_id, PRIMARY, tag=series_tag, max_width=max_width)
    album_id = item.get("AlbumId")
    album_tag = item.get("AlbumPrimaryImageTag")
    if album_id and album_tag:
        return image_url(client, album_id, PRIMARY, tag=album_tag, max_width=max_width)
    return None


def series_poster_url(client, episode, season=None, max_width=None):
    """Portrait show poster for an Episode item (e.g. for Next Up, where the
    episode's own landscape screengrab isn't wanted): the current season's
    own poster if it has one, else the series poster. `season` is that
    episode's Season item dict (fetched separately — Jellyfin doesn't inline
    the season's own ImageTags onto the episode)."""
    if season:
        season_tag = season.get("ImageTags", {}).get(PRIMARY)
        if season_tag:
            return image_url(client, season["Id"], PRIMARY, tag=season_tag, max_width=max_width)
    series_id = episode.get("SeriesId")
    series_tag = episode.get("SeriesPrimaryImageTag")
    if series_id and series_tag:
        return image_url(client, series_id, PRIMARY, tag=series_tag, max_width=max_width)
    return None


def backdrop_image_url(client, item, max_width=None, index=0):
    """Fanart/backdrop for `item`, falling back to its parent's backdrop."""
    tags = item.get("BackdropImageTags") or []
    if tags:
        return image_url(client, item["Id"], BACKDROP, tag=tags[index], max_width=max_width, index=index)
    parent_id = item.get("ParentBackdropItemId")
    parent_tags = item.get("ParentBackdropImageTags") or []
    if parent_id and parent_tags:
        return image_url(client, parent_id, BACKDROP, tag=parent_tags[index], max_width=max_width, index=index)
    return None
