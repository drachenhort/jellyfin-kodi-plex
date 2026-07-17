import lib.jellyfin.client as client_mod
from lib.jellyfin import system


class FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json_data = json_data
        self.status_code = status_code
        self.text = text
        self.content = b"1" if json_data is not None else b""

    def json(self):
        return self._json_data


class FakeRequests:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, json=None, params=None, timeout=None):
        self.calls.append({"method": method, "url": url})
        return self.responses.pop(0)


def test_get_public_info(anon_client, monkeypatch):
    fake = FakeRequests([FakeResponse({"ServerName": "Tower", "Version": "10.11.11"})])
    monkeypatch.setattr(client_mod, "requests", fake)

    info = system.get_public_info(anon_client)

    assert info["ServerName"] == "Tower"
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith("/System/Info/Public")
