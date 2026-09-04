"""Library/item browsing: views, item listings, and home-screen hubs."""

import time

# People (cast) is the most expensive field for Jellyfin to hydrate per item,
# and it's only ever displayed on the single-item Detail page (_cast_line in
# lib/windows/detail.py) - every other call here returns many items at once
# (a 200-item Browse page, hub rows, search results), so requesting it there
# too was pure overhead nobody saw, on exactly the kind of large listing
# (e.g. a big real Music library) most likely to make a slow query timeout.
LISTING_ITEM_FIELDS = "Overview,Genres,RunTimeTicks,ProductionYear,CommunityRating,CriticRating"
# MediaSources (and its nested MediaStreams) is only needed for the Detail
# screen's audio/subtitle track pickers - the other of get_item()'s two
# callers (lib/player.py, just for the ListItem title) doesn't use it, but
# there's only the one caller that matters cost-wise and it's a single-item
# fetch, not a listing, so the extra payload is negligible.
DEFAULT_ITEM_FIELDS = LISTING_ITEM_FIELDS + ",People,MediaSources"


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


def is_played(item):
    """Whether a Jellyfin item dict has been marked watched, per its
    UserData.Played flag - shared by every "hide watched" filter (Recently
    Added Movies/TV/Music) so they all read the same field the same way."""
    return bool((item.get("UserData") or {}).get("Played"))


def get_items(client, parent_id=None, start_index=0, limit=50, sort_by="SortName",
              sort_order="Ascending", include_item_types=None, recursive=True,
              search_term=None, genre_id=None, fields=LISTING_ITEM_FIELDS):
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
    if genre_id:
        params["GenreIds"] = genre_id
    return client.get(f"/Users/{client.user_id}/Items", params=params)


def get_genres(client, parent_id=None):
    """GET /Genres — the distinct genres present under `parent_id` (a
    library's Id), for the Movies library's genre filter buttons. Recursive
    so a genre only present on a deep child (there are no deep children in a
    flat Movies library today, but this stays correct if that changes) still
    shows up."""
    params = {"UserId": client.user_id, "Recursive": "true", "SortBy": "SortName"}
    if parent_id:
        params["ParentId"] = parent_id
    result = client.get("/Genres", params=params)
    return result.get("Items", [])


def get_item(client, item_id, fields=DEFAULT_ITEM_FIELDS):
    """GET /Users/{userId}/Items/{itemId} — full detail for one item."""
    return client.get(
        f"/Users/{client.user_id}/Items/{item_id}",
        params={"Fields": fields},
    )


# Session-scoped, same reasoning/invalidation as _browse_cache below (these
# items carry watched-state too) - keyed by (client, item_id) rather than
# by browse level, since each Detail page only ever asks for one item's own
# Similar list.
_similar_cache = {}  # (client, item_id) -> items list


def get_similar(client, item_id, limit=12):
    """GET /Items/{itemId}/Similar — items similar to this one (genre, cast,
    etc. per Jellyfin's own recommendation logic), for the Detail screen's
    "More Like This" row. Cached per (client, item_id) for the rest of the
    session - see _similar_cache and clear_browse_cache()."""
    cache_key = (client, item_id)
    cached = _similar_cache.get(cache_key)
    if cached is not None:
        return cached
    result = client.get(
        f"/Items/{item_id}/Similar",
        params={"UserId": client.user_id, "Limit": limit, "Fields": LISTING_ITEM_FIELDS},
    )
    items = result.get("Items", [])
    _similar_cache[cache_key] = items
    return items


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


# A season contributing at least this many recently-added episodes collapses
# into a single "Season" block item instead of showing each episode as its
# own tile - avoids a big binge-added season flooding the whole row.
SEASON_BLOCK_THRESHOLD = 3


def get_latest_episodes(client, parent_id=None, limit=20, block_threshold=SEASON_BLOCK_THRESHOLD,
                         hide_watched=False):
    """Recently added episodes (TV libraries), as up to `limit` tiles. A
    season that got at least `block_threshold` episodes added at once
    collapses into a single block item (Type "Season") rather than showing
    each episode as its own tile; a season with fewer new episodes still
    lists them individually.

    The raw API fetch pulls in more than `limit` episodes (see
    _episode_fetch_limit()) since one big season dump can itself contain
    `limit`-or-more episodes - fetching only `limit` raw episodes would let
    that single season's batch crowd out every other show's recently added
    episodes, even though it only ends up costing the row one tile.

    `hide_watched`, when set, drops watched episodes before grouping rather
    than after: a synthetic season block has no Played flag of its own to
    filter on, so filtering post-grouping would never hide an
    already-fully-watched batch, and a partially-watched batch would still
    count its watched episodes in the block's episode tally."""
    result = get_items(
        client, parent_id=parent_id, limit=_episode_fetch_limit(limit, block_threshold),
        sort_by="DateCreated", sort_order="Descending", include_item_types="Episode",
        recursive=True, fields=LISTING_ITEM_FIELDS,
    )
    items = result.get("Items", [])
    if hide_watched:
        items = [item for item in items if not is_played(item)]
    return _group_latest_episodes(items, block_threshold)[:limit]


def _episode_fetch_limit(limit, block_threshold):
    """How many raw episodes to request so that `limit` distinct season
    groups can still be found even in the worst case: every one of them
    sitting right at `block_threshold` episodes, since that's the point
    where a season "costs" the most raw episodes (block_threshold of them)
    per single tile it ends up producing - `limit * block_threshold` raw
    episodes is therefore enough to guarantee `limit` tiles are found.
    Doubled for slack against ties/uneven distributions, with a floor so a
    small "item limit" setting doesn't undersize the fetch, and a cap so a
    large one doesn't turn into a huge request."""
    return min(max(limit * block_threshold * 2, 50), 500)


def _group_latest_episodes(items, block_threshold=SEASON_BLOCK_THRESHOLD):
    """Groups episodes by season - most-recently-added season first, per the
    DateCreated-descending fetch above - then orders each season's episodes
    ascending by episode number. A whole season scanned in at once isn't
    guaranteed to get sequential DateCreated timestamps (depends on
    filesystem enumeration / metadata-fetch order), which otherwise shows up
    as e.g. S9E2, then E9, then E7, before finally E1. A season with
    `block_threshold` or more episodes in the batch is collapsed into a
    single season block item instead of listing each one."""
    groups = {}
    season_order = []
    for item in items:
        # Falls back to the episode's own Id on the rare item missing
        # SeasonId, making it a "group" of one that can never reach
        # block_threshold - it just stays an individual tile rather than
        # being dropped or crashing the grouping below.
        season_id = item.get("SeasonId") or item.get("Id")
        if season_id not in groups:
            groups[season_id] = []
            season_order.append(season_id)
        groups[season_id].append(item)
    ordered = []
    for season_id in season_order:
        group = groups[season_id]
        group.sort(key=lambda i: (i.get("ParentIndexNumber") or 0, i.get("IndexNumber") or 0))
        if len(group) >= block_threshold:
            ordered.append(_season_block_item(group))
        else:
            ordered.extend(group)
    return ordered


def _season_block_item(episodes):
    """Synthetic "Season" item standing in for a batch of recently-added
    episodes, so it opens (via the normal Series/Season/... container click
    handling) straight to that season's episode list rather than playing a
    single episode. Reuses UnplayedItemCount so the same unwatched-count
    badge existing Season/Series tiles show applies here too."""
    first = episodes[0]
    season_number = first.get("ParentIndexNumber")
    series_name = first.get("SeriesName") or ""
    name = f"{series_name} - Season {season_number}" if season_number is not None else series_name
    return {
        "Id": first.get("SeasonId"),
        "Type": "Season",
        "Name": name,
        "SeriesId": first.get("SeriesId"),
        "SeriesName": series_name,
        "SeriesPrimaryImageTag": first.get("SeriesPrimaryImageTag"),
        "ParentIndexNumber": season_number,
        "UserData": {"UnplayedItemCount": len(episodes)},
    }


def _get_all_children(client, parent_id, item_type):
    """All items of `item_type` directly under `parent_id`, sorted by
    IndexNumber ascending. Uses a high limit since these are used for
    season/episode listings that fit well within it."""
    return get_items(
        client, parent_id=parent_id, limit=1000, sort_by="IndexNumber",
        sort_order="Ascending", include_item_types=item_type, fields=LISTING_ITEM_FIELDS,
    ).get("Items", [])


def get_next_episode_in_season(client, item_id):
    """The episode immediately after `item_id`, by IndexNumber - within the
    same season if one follows, otherwise the first episode of the next
    season (by season IndexNumber) if the show continues there. None if
    `item_id` isn't an Episode, has no season, or is the show's last episode
    overall. Used to offer auto-play after an episode finishes (lib/main.py)."""
    current = get_item(client, item_id, fields=LISTING_ITEM_FIELDS)
    if not current or current.get("Type") != "Episode":
        return None
    season_id = current.get("SeasonId") or current.get("ParentId")
    if not season_id:
        return None
    siblings = _get_all_children(client, season_id, "Episode")
    for index, episode in enumerate(siblings):
        if episode.get("Id") == item_id:
            if index + 1 < len(siblings):
                return siblings[index + 1]
            return _get_first_episode_of_next_season(client, current, season_id)
    return None


def _get_first_episode_of_next_season(client, current_episode, season_id):
    """The first episode (by IndexNumber) of the season immediately after
    `season_id` within the same series, by season IndexNumber - or None if
    there's no series, no next season, or that season has no episodes."""
    series_id = current_episode.get("SeriesId")
    if not series_id:
        return None
    season = get_item(client, season_id, fields=LISTING_ITEM_FIELDS)
    season_number = season.get("IndexNumber") if season else None
    if season_number is None:
        return None
    seasons = _get_all_children(client, series_id, "Season")
    next_seasons = [
        s for s in seasons
        if s.get("IndexNumber") is not None and s.get("IndexNumber") > season_number
    ]
    if not next_seasons:
        return None
    next_season = min(next_seasons, key=lambda s: s.get("IndexNumber"))
    episodes = _get_all_children(client, next_season.get("Id"), "Episode")
    return episodes[0] if episodes else None


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
# after a manual watched/unwatched toggle). Also clears get_similar()'s
# _similar_cache above, for the same reason.
_browse_cache = {}  # (client, parent_id, sort_by, sort_order) -> items list


def _browse_cache_key(client, parent_id, sort_by, sort_order, genre_id=None):
    return (client, parent_id, sort_by, sort_order, genre_id)


def get_cached_children(client, parent_id, sort_by, sort_order, genre_id=None):
    """The fully-loaded children previously cached for this exact browse
    level, or None if not cached (never loaded, or invalidated since)."""
    return _browse_cache.get(_browse_cache_key(client, parent_id, sort_by, sort_order, genre_id))


def cache_children(client, parent_id, sort_by, sort_order, items, genre_id=None):
    _browse_cache[_browse_cache_key(client, parent_id, sort_by, sort_order, genre_id)] = items


def clear_browse_cache():
    _browse_cache.clear()
    _similar_cache.clear()


def iter_items_paged(client, parent_id=None, include_item_types=None, fields="",
                      sort_by="SortName", sort_order="Ascending", recursive=True,
                      genre_id=None, page_size=50, timeout=(5, 300)):
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
        if genre_id:
            params["GenreIds"] = genre_id
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
