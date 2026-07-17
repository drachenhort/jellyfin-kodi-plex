import lib.jellyfin.client as client_mod
from lib.jellyfin import system
from tests.fakes import FakeRequests, FakeResponse


def test_get_public_info(anon_client, monkeypatch):
    fake = FakeRequests([FakeResponse({"ServerName": "Tower", "Version": "10.11.11"})])
    monkeypatch.setattr(client_mod, "requests", fake)

    info = system.get_public_info(anon_client)

    assert info["ServerName"] == "Tower"
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith("/System/Info/Public")
