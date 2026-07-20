"""Library/item browsing: views, item listings, and home-screen hubs."""

import time

# People (cast) is the most expensive field for Jellyfin to hydrate per item,
# and it's only ever displayed on the single-item Detail page (_cast_line in
# lib/windows/detail.py) - every other call here returns many items at once
# (a 200-item Browse page, hub rows, search results), so requesting it there
# too was pure overhead nobody saw, on exactly the kind of large listing
# (e.g. a big real Music library) most likely to make a slow query timeout.
LISTING_ITEM_FIELDS = "Overview,Genres,RunTimeTicks,ProductionYear,CommunityRating,CriticRating"
DEFAULT_ITEM_FIELDS = LISTING_ITEM_FIELDS + ",People"


# Home re-fetches views on every visit (plain Back navigation, every
# settings-driven reload) even though a user's library list rarely changes
# within a session - a short per-client cache avoids a redundant round trip
# on each of those without meaningfully risking staleness (a newly added
# library just takes up to this long to show up on Home).
VIEWS_CACHE_TTL_SECONDS = 60

_views_cache = {}  # client -> (cached_at, views)


def get_views(client):
    """GET /Users/{userId}/Views — the user's top-level libraries.

    Cached per client for VIEWS_CACHE_TTL_SECONDS - see module comment."""
    cached = _views_cache.get(client)
    now = time.time()
    if cached is not None and now - cached[0] < VIEWS_CACHE_TTL_SECONDS:
        return cached[1]
    result = client.get(f"/Users/{client.user_id}/Views")
    views = result.get("Items", [])
    _views_cache[client] = (now, views)
    return views


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
    result = client.post(f"/Users/{client.user_id}/PlayedItems/{item_id}")
    clear_browse_cache()
    return result


def mark_unplayed(client, item_id):
    """DELETE /Users/{userId}/PlayedItems/{itemId} — mark an item unwatched."""
    result = client.delete(f"/Users/{client.user_id}/PlayedItems/{item_id}")
    clear_browse_cache()
    return result


# Caches a browse level's fully-loaded children (a library's top-level items,
# a series' seasons, a season's episodes, ...) for the rest of the session,
# so repeatedly backing into the same level (e.g. a big TV library's Series
# list) doesn't re-run the whole iter_items_paged() walk each time - see
# lib/windows/browse.py's _load(). Deliberately session-scoped rather than
# time-based like get_views()'s cache: these listings carry each item's
# watched-state (UserData.Played / UnplayedItemCount), which a TTL would let
# go stale in a much more visible way (a just-finished episode still shown
# unwatched) - clear_browse_cache() is called instead from the one place
# watched-state actually changes (lib/player.py after playback, and here
# after a manual watched/unwatched toggle).
_browse_cache = {}  # (client, parent_id, sort_by, sort_order) -> items list


def _browse_cache_key(client, parent_id, sort_by, sort_order):
    return (client, parent_id, sort_by, sort_order)


def get_cached_children(client, parent_id, sort_by, sort_order):
    """The fully-loaded children previously cached for this exact browse
    level, or None if not cached (never loaded, or invalidated since)."""
    return _browse_cache.get(_browse_cache_key(client, parent_id, sort_by, sort_order))


def cache_children(client, parent_id, sort_by, sort_order, items):
    _browse_cache[_browse_cache_key(client, parent_id, sort_by, sort_order)] = items


def clear_browse_cache():
    _browse_cache.clear()


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


def search_items(client, term, limit=50, fields=LISTING_ITEM_FIELDS,
                  include_item_types=SEARCH_ITEM_TYPES):
    """GET /Users/{userId}/Items with SearchTerm — used by the Search screen.

    `include_item_types` defaults to every searchable type but accepts a
    narrower comma-separated subset, e.g. to let the Search screen's
    Movies/TV/Music filter toggles exclude a category from the query
    entirely rather than just hiding results client-side.
    """
    return get_items(
        client, limit=limit, recursive=True, search_term=term,
        include_item_types=include_item_types, fields=fields,
    )
