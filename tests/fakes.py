"""Shared fakes for testing lib.jellyfin.client's HTTP layer, and anything
built on top of it, without a real network call.
"""


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
