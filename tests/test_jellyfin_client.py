import lib.jellyfin.client as client_mod
from lib.jellyfin import auth, images, library, playback


class FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json_data = json_data
        self.status_code = status_code
        self.text = text
        self.content = b"1" if json_data is not None else b""

    def json(self):
        return self._json_data


class FakeRequests:
    """Records every call and returns queued responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json, "params": params}
        )
        return self.responses.pop(0)


def test_auth_header_without_token(anon_client):
    header = anon_client.auth_header()
    assert header.startswith("MediaBrowser ")
    assert 'Client="Jellyfin Plex-style Kodi Client"' in header
    assert 'DeviceId="test-device-id"' in header
    assert "Token=" not in header


def test_auth_header_with_token(client):
    header = client.auth_header()
    assert 'Token="test-token"' in header


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


def test_get_items_builds_params(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": [], "TotalRecordCount": 0})])
    monkeypatch.setattr(client_mod, "requests", fake)

    library.get_items(client, parent_id="lib-1", start_index=20, limit=10)

    params = fake.calls[0]["params"]
    assert params["ParentId"] == "lib-1"
    assert params["StartIndex"] == 20
    assert params["Limit"] == 10
    assert params["Recursive"] == "true"


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


def test_stream_url_builds_expected_query(client):
    media_source = {"Id": "ms-1", "Container": "mkv"}
    url, play_session_id = playback.stream_url(client, "item-1", media_source)

    assert url.startswith(client.build_url("/Videos/item-1/stream.mkv"))
    assert "static=true" in url
    assert "mediaSourceId=ms-1" in url
    assert f"api_key={client.access_token}" in url
    assert play_session_id in url


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
