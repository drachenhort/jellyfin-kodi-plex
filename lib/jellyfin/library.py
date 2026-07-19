"""Library/item browsing: views, item listings, and home-screen hubs."""

# People (cast) is the most expensive field for Jellyfin to hydrate per item,
# and it's only ever displayed on the single-item Detail page (_cast_line in
# lib/windows/detail.py) - every other call here returns many items at once
# (a 200-item Browse page, hub rows, search results), so requesting it there
# too was pure overhead nobody saw, on exactly the kind of large listing
# (e.g. a big real Music library) most likely to make a slow query timeout.
LISTING_ITEM_FIELDS = "Overview,Genres,RunTimeTicks,ProductionYear,CommunityRating,CriticRating"
DEFAULT_ITEM_FIELDS = LISTING_ITEM_FIELDS + ",People"


def get_views(client):
    """GET /Users/{userId}/Views — the user's top-level libraries."""
    result = client.get(f"/Users/{client.user_id}/Views")
    return result.get("Items", [])


def get_items(client, parent_id=None, start_index=0, limit=50, sort_by="SortName",
              sort_order="Ascending", include_item_types=None, recursive=True,
              search_term=None, fields=LISTING_ITEM_FIELDS):
    """GET /Users/{userId}/Items — browse within a library/folder, paged."""
    params = {
        "StartIndex": start_index,
        "Limit": limit,
        "SortBy": sort_by,
        "SortOrder": sort_order,
        "Recursive": str(recursive).lower(),
        "Fields": fields,
    }
    if parent_id:
        params["ParentId"] = parent_id
    if include_item_types:
        params["IncludeItemTypes"] = include_item_types
    if search_term:
        params["SearchTerm"] = search_term
    return client.get(f"/Users/{client.user_id}/Items", params=params)


def get_item(client, item_id, fields=DEFAULT_ITEM_FIELDS):
    """GET /Users/{userId}/Items/{itemId} — full detail for one item."""
    return client.get(
        f"/Users/{client.user_id}/Items/{item_id}",
        params={"Fields": fields},
    )


def get_resume(client, limit=20):
    """GET /Users/{userId}/Items/Resume — Continue Watching hub."""
    result = client.get(
        f"/Users/{client.user_id}/Items/Resume",
        params={"Limit": limit, "Fields": LISTING_ITEM_FIELDS},
    )
    return result.get("Items", [])


def get_next_up(client, limit=20):
    """GET /Shows/NextUp — Next Up hub."""
    result = client.get(
        "/Shows/NextUp",
        params={"UserId": client.user_id, "Limit": limit, "Fields": LISTING_ITEM_FIELDS},
    )
    return result.get("Items", [])


def get_items_by_ids(client, item_ids, fields="ImageTags"):
    """GET /Users/{userId}/Items?Ids=... — batch lookup by id, e.g. to check
    which seasons in a Next Up list have their own poster art."""
    if not item_ids:
        return []
    result = client.get(f"/Users/{client.user_id}/Items", params={
        "Ids": ",".join(item_ids),
        "Fields": fields,
    })
    return result.get("Items", [])


def get_latest(client, parent_id=None, limit=20):
    """GET /Users/{userId}/Items/Latest — Recently Added hub, per library."""
    params = {"Limit": limit, "Fields": LISTING_ITEM_FIELDS}
    if parent_id:
        params["ParentId"] = parent_id
    result = client.get(f"/Users/{client.user_id}/Items/Latest", params=params)
    return result or []


def get_latest_episodes(client, parent_id=None, limit=20):
    """Recently added episodes (TV libraries), newest-added first, listed
    individually rather than grouped/deduplicated by series - two episodes
    of the same show added recently both show up as separate items."""
    result = get_items(
        client, parent_id=parent_id, limit=limit, sort_by="DateCreated",
        sort_order="Descending", include_item_types="Episode", recursive=True,
        fields=LISTING_ITEM_FIELDS,
    )
    return result.get("Items", [])


def mark_played(client, item_id):
    """POST /Users/{userId}/PlayedItems/{itemId} — mark an item watched."""
    return client.post(f"/Users/{client.user_id}/PlayedItems/{item_id}")


def mark_unplayed(client, item_id):
    """DELETE /Users/{userId}/PlayedItems/{itemId} — mark an item unwatched."""
    return client.delete(f"/Users/{client.user_id}/PlayedItems/{item_id}")


def iter_items_paged(client, parent_id=None, include_item_types=None, fields="",
                      sort_by="SortName", sort_order="Ascending", recursive=True,
                      page_size=50, timeout=(5, 300)):
    """GET /Users/{userId}/Items, paged via StartIndex/Limit — for walking a whole
    library too large to hold in memory at once (e.g. a ~100k-track Music library).

    Yields each page's Items list as it arrives rather than collecting every page
    first, so the caller can process a page (index it, write it out, ...) and let
    it go before the next one is fetched. EnableTotalRecordCount=false skips
    Jellyfin computing a total count on every page - the walk already terminates
    on a short/empty page, so it isn't needed. The default timeout is a (connect,
    read) tuple: fail fast if the server's unreachable, but allow a slow real
    query for a big page plenty of room before giving up.
    """
    start_index = 0
    while True:
        params = {
            "StartIndex": start_index,
            "Limit": page_size,
            "SortBy": sort_by,
            "SortOrder": sort_order,
            "Recursive": str(recursive).lower(),
            "Fields": fields,
            "EnableTotalRecordCount": "false",
        }
        if parent_id:
            params["ParentId"] = parent_id
        if include_item_types:
            params["IncludeItemTypes"] = include_item_types
        response = client.get(f"/Users/{client.user_id}/Items", params=params, timeout=timeout)
        items = response.get("Items", [])
        if not items:
            return
        yield items
        if len(items) < page_size:
            return
        start_index += page_size


SEARCH_ITEM_TYPES = "Movie,Series,MusicArtist,MusicAlbum,Audio,Episode"


def search_items(client, term, limit=50, fields=LISTING_ITEM_FIELDS):
    """GET /Users/{userId}/Items with SearchTerm — used by the Search screen."""
    return get_items(
        client, limit=limit, recursive=True, search_term=term,
        include_item_types=SEARCH_ITEM_TYPES, fields=fields,
    )
