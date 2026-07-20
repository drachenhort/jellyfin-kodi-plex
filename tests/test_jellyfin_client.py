import lib.jellyfin.client as client_mod
from lib.jellyfin import auth, images, library, playback
from tests.fakes import FakeRequests, FakeResponse


def test_auth_header_without_token(anon_client):
    header = anon_client.auth_header()
    assert header.startswith("MediaBrowser ")
    assert 'Client="Jellyfin Plex-style Kodi Client"' in header
    assert 'DeviceId="test-device-id"' in header
    assert "Token=" not in header


def test_auth_header_with_token(client):
    header = client.auth_header()
    assert 'Token="test-token"' in header


def test_requests_use_the_configured_timeout(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"ServerName": "Tower"})])
    monkeypatch.setattr(client_mod, "requests", fake)

    client.get("/System/Info/Public")

    assert fake.calls[0]["timeout"] == client_mod.REQUEST_TIMEOUT_SECONDS


def test_get_honors_an_explicit_timeout_override(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"ServerName": "Tower"})])
    monkeypatch.setattr(client_mod, "requests", fake)

    client.get("/System/Info/Public", timeout=(5, 300))

    assert fake.calls[0]["timeout"] == (5, 300)


def test_requests_use_a_constructor_provided_timeout(monkeypatch):
    """lib/main.py passes the addon's "Server request timeout" setting in
    here - it must actually take effect for calls that don't override it."""
    custom_client = client_mod.JellyfinClient(
        "http://jellyfin.example:8096", device_id="test-device-id", request_timeout=15,
    )
    fake = FakeRequests([FakeResponse({"ServerName": "Tower"})])
    monkeypatch.setattr(client_mod, "requests", fake)

    custom_client.get("/System/Info/Public")

    assert fake.calls[0]["timeout"] == 15


def test_authenticate_by_name_sets_token_and_user(anon_client, monkeypatch):
    fake = FakeRequests([
        FakeResponse({"AccessToken": "abc123", "User": {"Id": "user-1", "Name": "steve"}})
    ])
    monkeypatch.setattr(client_mod, "requests", fake)

    user = auth.authenticate_by_name(anon_client, "steve", "hunter2")

    assert anon_client.access_token == "abc123"
    assert anon_client.user_id == "user-1"
    assert user["Name"] == "steve"
    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/Users/AuthenticateByName")
    assert call["json"] == {"Username": "steve", "Pw": "hunter2"}


def test_quick_connect_flow(anon_client, monkeypatch):
    fake = FakeRequests([
        FakeResponse({"Secret": "the-secret", "Code": "ABCD12"}),
        FakeResponse({"Authenticated": False}),
        FakeResponse({"Authenticated": True}),
        FakeResponse({"AccessToken": "qc-token", "User": {"Id": "user-2", "Name": "quickuser"}}),
    ])
    monkeypatch.setattr(client_mod, "requests", fake)

    initiated = auth.initiate_quick_connect(anon_client)
    assert initiated["Code"] == "ABCD12"

    assert auth.poll_quick_connect(anon_client, "the-secret") is False
    assert auth.poll_quick_connect(anon_client, "the-secret") is True

    user = auth.authenticate_with_quick_connect(anon_client, "the-secret")
    assert anon_client.access_token == "qc-token"
    assert anon_client.user_id == "user-2"
    assert user["Name"] == "quickuser"

    poll_call = fake.calls[2]
    assert poll_call["params"] == {"secret": "the-secret"}


def test_get_views(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": [{"Name": "Movies", "Id": "lib-1"}]})])
    monkeypatch.setattr(client_mod, "requests", fake)

    views = library.get_views(client)

    assert views == [{"Name": "Movies", "Id": "lib-1"}]
    assert fake.calls[0]["url"].endswith(f"/Users/{client.user_id}/Views")


# -- get_views caching -------------------------------------------------------

def test_get_views_is_cached_within_ttl(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": [{"Name": "Movies", "Id": "lib-1"}]})])
    monkeypatch.setattr(client_mod, "requests", fake)
    library._views_cache.clear()

    first = library.get_views(client)
    second = library.get_views(client)

    assert first == second == [{"Name": "Movies", "Id": "lib-1"}]
    assert len(fake.calls) == 1  # second call served from cache, no new request


def test_get_views_refetches_after_ttl_expires(client, monkeypatch):
    fake = FakeRequests([
        FakeResponse({"Items": [{"Name": "Movies", "Id": "lib-1"}]}),
        FakeResponse({"Items": [{"Name": "Movies", "Id": "lib-1"}, {"Name": "TV", "Id": "lib-2"}]}),
    ])
    monkeypatch.setattr(client_mod, "requests", fake)
    library._views_cache.clear()

    times = iter([1000.0, 1000.0 + library.VIEWS_CACHE_TTL_SECONDS + 1])
    monkeypatch.setattr(library.time, "time", lambda: next(times))

    first = library.get_views(client)
    second = library.get_views(client)

    assert len(first) == 1
    assert len(second) == 2
    assert len(fake.calls) == 2


def test_get_views_cache_is_per_client(monkeypatch):
    from lib.jellyfin.client import JellyfinClient

    client_a = JellyfinClient("http://a.example:8096", device_id="dev-a")
    client_a.access_token, client_a.user_id = "tok-a", "user-a"
    client_b = JellyfinClient("http://b.example:8096", device_id="dev-b")
    client_b.access_token, client_b.user_id = "tok-b", "user-b"

    fake = FakeRequests([
        FakeResponse({"Items": [{"Name": "A-Movies", "Id": "a1"}]}),
        FakeResponse({"Items": [{"Name": "B-Movies", "Id": "b1"}]}),
    ])
    monkeypatch.setattr(client_mod, "requests", fake)
    library._views_cache.clear()

    views_a = library.get_views(client_a)
    views_b = library.get_views(client_b)

    assert views_a == [{"Name": "A-Movies", "Id": "a1"}]
    assert views_b == [{"Name": "B-Movies", "Id": "b1"}]
    assert len(fake.calls) == 2


def test_get_items_builds_params(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": [], "TotalRecordCount": 0})])
    monkeypatch.setattr(client_mod, "requests", fake)

    library.get_items(client, parent_id="lib-1", start_index=20, limit=10)

    params = fake.calls[0]["params"]
    assert params["ParentId"] == "lib-1"
    assert params["StartIndex"] == 20
    assert params["Limit"] == 10
    assert params["Recursive"] == "true"


def test_get_items_does_not_request_people_by_default(client, monkeypatch):
    """People (cast) is expensive for Jellyfin to hydrate per item and is
    only ever shown on the single-item Detail page - a multi-item listing
    call (lib/windows/browse.py's paged fetch, or a hub row) requesting it
    too was pure overhead, plausibly a real contributor to real, large-library
    listings timing out."""
    fake = FakeRequests([FakeResponse({"Items": [], "TotalRecordCount": 0})])
    monkeypatch.setattr(client_mod, "requests", fake)

    library.get_items(client, parent_id="lib-1")

    assert "People" not in fake.calls[0]["params"]["Fields"]


def test_get_item_still_requests_people(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Id": "item-1"})])
    monkeypatch.setattr(client_mod, "requests", fake)

    library.get_item(client, "item-1")

    assert "People" in fake.calls[0]["params"]["Fields"]


def test_get_items_non_recursive(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": [], "TotalRecordCount": 0})])
    monkeypatch.setattr(client_mod, "requests", fake)

    library.get_items(client, parent_id="series-1", recursive=False)

    assert fake.calls[0]["params"]["Recursive"] == "false"


def test_get_items_search_term(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": [], "TotalRecordCount": 0})])
    monkeypatch.setattr(client_mod, "requests", fake)

    library.get_items(client, search_term="alien")

    assert fake.calls[0]["params"]["SearchTerm"] == "alien"


def test_search_items_builds_params(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": [{"Id": "s1"}]})])
    monkeypatch.setattr(client_mod, "requests", fake)

    result = library.search_items(client, "alien", limit=10)

    assert result == {"Items": [{"Id": "s1"}]}
    params = fake.calls[0]["params"]
    assert params["SearchTerm"] == "alien"
    assert params["Limit"] == 10
    assert params["Recursive"] == "true"
    assert params["IncludeItemTypes"] == library.SEARCH_ITEM_TYPES


def test_iter_items_paged_yields_each_page_and_stops_on_short_page(client, monkeypatch):
    fake = FakeRequests([
        FakeResponse({"Items": [{"Id": f"a{i}"} for i in range(50)]}),
        FakeResponse({"Items": [{"Id": f"b{i}"} for i in range(50)]}),
        FakeResponse({"Items": [{"Id": "c0"}]}),
    ])
    monkeypatch.setattr(client_mod, "requests", fake)

    pages = list(library.iter_items_paged(client, parent_id="music-1", fields="RunTimeTicks"))

    assert len(pages) == 3
    assert len(pages[0]) == 50
    assert len(pages[1]) == 50
    assert pages[2] == [{"Id": "c0"}]
    # A short (or empty) page ends the walk without an extra trailing request.
    assert len(fake.calls) == 3


def test_iter_items_paged_stops_immediately_on_empty_first_page(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": []})])
    monkeypatch.setattr(client_mod, "requests", fake)

    pages = list(library.iter_items_paged(client, parent_id="music-1"))

    assert pages == []
    assert len(fake.calls) == 1


def test_iter_items_paged_request_params(client, monkeypatch):
    fake = FakeRequests([
        FakeResponse({"Items": [{"Id": f"a{i}"} for i in range(50)]}),
        FakeResponse({"Items": [{"Id": "b0"}]}),
    ])
    monkeypatch.setattr(client_mod, "requests", fake)

    list(library.iter_items_paged(
        client, parent_id="music-1", include_item_types="Audio", fields="RunTimeTicks",
    ))

    first, second = fake.calls
    assert first["params"]["StartIndex"] == 0
    assert first["params"]["Limit"] == 50
    assert first["params"]["ParentId"] == "music-1"
    assert first["params"]["IncludeItemTypes"] == "Audio"
    assert first["params"]["Fields"] == "RunTimeTicks"
    assert first["params"]["EnableTotalRecordCount"] == "false"
    assert first["params"]["Recursive"] == "true"
    assert first["timeout"] == (5, 300)

    assert second["params"]["StartIndex"] == 50


def test_iter_items_paged_only_requests_default_fields_when_unset(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": []})])
    monkeypatch.setattr(client_mod, "requests", fake)

    list(library.iter_items_paged(client, parent_id="music-1"))

    assert fake.calls[0]["params"]["Fields"] == ""


def test_get_resume_and_next_up_and_latest(client, monkeypatch):
    fake = FakeRequests([
        FakeResponse({"Items": [{"Id": "r1"}]}),
        FakeResponse({"Items": [{"Id": "n1"}]}),
        FakeResponse([{"Id": "l1"}]),
    ])
    monkeypatch.setattr(client_mod, "requests", fake)

    assert library.get_resume(client) == [{"Id": "r1"}]
    assert library.get_next_up(client) == [{"Id": "n1"}]
    assert library.get_latest(client) == [{"Id": "l1"}]

    assert fake.calls[0]["url"].endswith("/Items/Resume")
    assert fake.calls[1]["url"].endswith("/Shows/NextUp")
    assert fake.calls[1]["params"]["UserId"] == client.user_id
    assert fake.calls[2]["url"].endswith("/Items/Latest")


def test_get_items_by_ids_builds_comma_separated_param(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": [{"Id": "s1"}, {"Id": "s2"}]})])
    monkeypatch.setattr(client_mod, "requests", fake)

    result = library.get_items_by_ids(client, ["s1", "s2"])

    assert result == [{"Id": "s1"}, {"Id": "s2"}]
    call = fake.calls[0]
    assert call["url"].endswith(f"/Users/{client.user_id}/Items")
    assert call["params"]["Ids"] == "s1,s2"


def test_get_items_by_ids_empty_list_short_circuits(client):
    assert library.get_items_by_ids(client, []) == []


def test_mark_played_posts_to_played_items(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Played": True})])
    monkeypatch.setattr(client_mod, "requests", fake)

    library.mark_played(client, "item-1")

    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(f"/Users/{client.user_id}/PlayedItems/item-1")


def test_mark_unplayed_deletes_played_items(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Played": False})])
    monkeypatch.setattr(client_mod, "requests", fake)

    library.mark_unplayed(client, "item-1")

    call = fake.calls[0]
    assert call["method"] == "DELETE"


def test_mark_played_clears_the_browse_cache(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Played": True})])
    monkeypatch.setattr(client_mod, "requests", fake)
    library.cache_children(client, "parent-1", "SortName", "Ascending", ["stale"])

    library.mark_played(client, "item-1")

    assert library.get_cached_children(client, "parent-1", "SortName", "Ascending") is None


def test_mark_unplayed_clears_the_browse_cache(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Played": False})])
    monkeypatch.setattr(client_mod, "requests", fake)
    library.cache_children(client, "parent-1", "SortName", "Ascending", ["stale"])

    library.mark_unplayed(client, "item-1")

    assert library.get_cached_children(client, "parent-1", "SortName", "Ascending") is None


# -- browse cache primitives -------------------------------------------------

def test_get_cached_children_returns_none_when_not_cached(client):
    library.clear_browse_cache()
    assert library.get_cached_children(client, "parent-1", "SortName", "Ascending") is None


def test_cache_children_then_get_cached_children_round_trips(client):
    library.clear_browse_cache()
    library.cache_children(client, "parent-1", "SortName", "Ascending", ["a", "b"])

    assert library.get_cached_children(client, "parent-1", "SortName", "Ascending") == ["a", "b"]


def test_cache_children_keyed_separately_per_sort_order(client):
    library.clear_browse_cache()
    library.cache_children(client, "parent-1", "SortName", "Ascending", ["by-name"])
    library.cache_children(client, "parent-1", "DateCreated", "Descending", ["by-date"])

    assert library.get_cached_children(client, "parent-1", "SortName", "Ascending") == ["by-name"]
    assert library.get_cached_children(client, "parent-1", "DateCreated", "Descending") == ["by-date"]


def test_series_poster_url_prefers_season_art(client):
    episode = {"SeriesId": "series-1", "SeriesPrimaryImageTag": "series-tag"}
    season = {"Id": "season-1", "ImageTags": {"Primary": "season-tag"}}
    url = images.series_poster_url(client, episode, season=season)
    assert url.startswith(client.build_url("/Items/season-1/Images/Primary"))
    assert "tag=season-tag" in url


def test_series_poster_url_falls_back_to_series_when_season_has_no_art(client):
    episode = {"SeriesId": "series-1", "SeriesPrimaryImageTag": "series-tag"}
    season = {"Id": "season-1", "ImageTags": {}}
    url = images.series_poster_url(client, episode, season=season)
    assert url.startswith(client.build_url("/Items/series-1/Images/Primary"))
    assert "tag=series-tag" in url


def test_series_poster_url_falls_back_when_no_season_given(client):
    episode = {"SeriesId": "series-1", "SeriesPrimaryImageTag": "series-tag"}
    url = images.series_poster_url(client, episode)
    assert url.startswith(client.build_url("/Items/series-1/Images/Primary"))


def test_series_poster_url_none_when_nothing_available(client):
    assert images.series_poster_url(client, {"Id": "ep-1"}) is None


def test_primary_image_url_uses_item_tag(client):
    item = {"Id": "item-1", "ImageTags": {"Primary": "tag123"}}
    url = images.primary_image_url(client, item, max_width=400)
    assert url.startswith(client.build_url("/Items/item-1/Images/Primary"))
    assert "tag=tag123" in url
    assert "maxWidth=400" in url
    assert f"api_key={client.access_token}" in url


def test_primary_image_url_falls_back_to_series(client):
    item = {"Id": "ep-1", "SeriesId": "series-1", "SeriesPrimaryImageTag": "stag"}
    url = images.primary_image_url(client, item)
    assert url.startswith(client.build_url("/Items/series-1/Images/Primary"))
    assert "tag=stag" in url


def test_primary_image_url_none_when_no_art(client):
    assert images.primary_image_url(client, {"Id": "x"}) is None


def test_primary_image_url_falls_back_to_album_for_a_track(client):
    item = {"Id": "track-1", "AlbumId": "album-1", "AlbumPrimaryImageTag": "atag"}
    url = images.primary_image_url(client, item)
    assert url.startswith(client.build_url("/Items/album-1/Images/Primary"))
    assert "tag=atag" in url


def test_backdrop_image_url_falls_back_to_parent(client):
    item = {"Id": "ep-1", "ParentBackdropItemId": "series-1", "ParentBackdropImageTags": ["ptag"]}
    url = images.backdrop_image_url(client, item)
    assert url.startswith(client.build_url("/Items/series-1/Images/Backdrop/0"))
    assert "tag=ptag" in url


def test_get_playback_info_posts_device_profile(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"MediaSources": [{"Id": "ms-1", "Container": "mkv"}]})])
    monkeypatch.setattr(client_mod, "requests", fake)

    result = playback.get_playback_info(client, "item-1")

    call = fake.calls[0]
    assert call["url"].endswith("/Items/item-1/PlaybackInfo")
    assert call["json"]["DeviceProfile"] == playback.DEFAULT_DEVICE_PROFILE
    assert call["params"] == {"UserId": client.user_id}
    assert result["MediaSources"][0]["Id"] == "ms-1"


def test_get_playback_info_overrides_max_streaming_bitrate(client, monkeypatch):
    """lib/player.py passes the addon's "Max streaming bitrate" setting in
    here - it must land in the profile without mutating the shared
    DEFAULT_DEVICE_PROFILE dict other calls also use."""
    fake = FakeRequests([FakeResponse({"MediaSources": []})])
    monkeypatch.setattr(client_mod, "requests", fake)

    playback.get_playback_info(client, "item-1", max_streaming_bitrate=8_000_000)

    call = fake.calls[0]
    assert call["json"]["DeviceProfile"]["MaxStreamingBitrate"] == 8_000_000
    assert playback.DEFAULT_DEVICE_PROFILE["MaxStreamingBitrate"] == 120_000_000


def test_get_playback_info_ignores_bitrate_override_when_device_profile_given(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"MediaSources": []})])
    monkeypatch.setattr(client_mod, "requests", fake)
    custom_profile = {"MaxStreamingBitrate": 1_000_000}

    playback.get_playback_info(client, "item-1", device_profile=custom_profile, max_streaming_bitrate=8_000_000)

    call = fake.calls[0]
    assert call["json"]["DeviceProfile"] == custom_profile


def test_stream_url_builds_expected_query(client):
    media_source = {"Id": "ms-1", "Container": "mkv"}
    url, play_session_id = playback.stream_url(client, "item-1", media_source)

    assert url.startswith(client.build_url("/Videos/item-1/stream.mkv"))
    assert "static=true" in url
    assert "mediaSourceId=ms-1" in url
    assert f"api_key={client.access_token}" in url
    assert play_session_id in url


def test_stream_url_uses_audio_endpoint_for_audio_items(client):
    media_source = {"Id": "ms-1", "Container": "mp3"}
    url, _ = playback.stream_url(client, "track-1", media_source, item_type="Audio")

    assert url.startswith(client.build_url("/Audio/track-1/stream.mp3"))


def test_stream_url_defaults_to_video_endpoint_when_item_type_unknown(client):
    media_source = {"Id": "ms-1", "Container": "mkv"}
    url, _ = playback.stream_url(client, "item-1", media_source)

    assert url.startswith(client.build_url("/Videos/item-1/stream.mkv"))


def test_report_playback_progress_posts_expected_body(client, monkeypatch):
    fake = FakeRequests([FakeResponse(None)])
    monkeypatch.setattr(client_mod, "requests", fake)

    playback.report_playback_progress(client, "item-1", "session-1", 12345, is_paused=True)

    call = fake.calls[0]
    assert call["url"].endswith("/Sessions/Playing/Progress")
    assert call["json"] == {
        "ItemId": "item-1",
        "PlaySessionId": "session-1",
        "PositionTicks": 12345,
        "IsPaused": True,
    }
