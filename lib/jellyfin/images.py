"""Image URL construction — no HTTP calls, just URL building.

Falls back to a parent item's art when the item itself has none, since e.g.
episodes usually don't carry their own Primary image.
"""

PRIMARY = "Primary"
BACKDROP = "Backdrop"
LOGO = "Logo"
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
    """Poster art for `item`, falling back to its series' art if needed."""
    tag = item.get("ImageTags", {}).get(PRIMARY)
    if tag:
        return image_url(client, item["Id"], PRIMARY, tag=tag, max_width=max_width)
    series_id = item.get("SeriesId")
    series_tag = item.get("SeriesPrimaryImageTag")
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
