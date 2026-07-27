"""Tests for lib.jellyfin.intro_skipper - the optional server-side Intro
Skipper plugin client. A server without the plugin installed 404s on this
endpoint rather than erroring, which must be treated as "no segments", not
a failure.
"""

import lib.jellyfin.client as client_mod
import lib.jellyfin.intro_skipper as intro_skipper_mod
from tests.fakes import FakeRequests, FakeResponse


def test_get_segments_returns_the_plugin_response(client, monkeypatch):
    fake_requests = FakeRequests([
        FakeResponse({"Introduction": {"Start": 0.0, "End": 90.0}}),
    ])
    monkeypatch.setattr(client_mod, "requests", fake_requests)

    segments = intro_skipper_mod.get_segments(client, "item-1")

    assert segments == {"Introduction": {"Start": 0.0, "End": 90.0}}
    assert fake_requests.calls[0]["url"].endswith("/Episode/item-1/IntroSkipperSegments")


def test_get_segments_returns_empty_when_plugin_not_installed(client, monkeypatch):
    fake_requests = FakeRequests([FakeResponse(None, status_code=404, text="Not Found")])
    monkeypatch.setattr(client_mod, "requests", fake_requests)

    assert intro_skipper_mod.get_segments(client, "item-1") == {}


def test_get_segments_reraises_other_errors(client, monkeypatch):
    fake_requests = FakeRequests([FakeResponse(None, status_code=500, text="boom")])
    monkeypatch.setattr(client_mod, "requests", fake_requests)

    try:
        intro_skipper_mod.get_segments(client, "item-1")
        assert False, "expected JellyfinApiError"
    except client_mod.JellyfinApiError as exc:
        assert exc.status_code == 500


def test_segment_bounds_reads_start_end_keys():
    segments = {"Introduction": {"Start": 5.0, "End": 65.0}}
    assert intro_skipper_mod.segment_bounds(segments, "Introduction") == (5.0, 65.0)


def test_segment_bounds_reads_introstart_introend_keys():
    segments = {"Introduction": {"IntroStart": 5.0, "IntroEnd": 65.0}}
    assert intro_skipper_mod.segment_bounds(segments, "Introduction") == (5.0, 65.0)


def test_segment_bounds_returns_none_when_segment_missing():
    assert intro_skipper_mod.segment_bounds({}, "Introduction") is None
    assert intro_skipper_mod.segment_bounds({"Credits": {"Start": 0, "End": 10}}, "Introduction") is None


def test_segment_bounds_returns_none_for_malformed_segment():
    assert intro_skipper_mod.segment_bounds({"Introduction": {"Start": 10.0, "End": 5.0}}, "Introduction") is None
    assert intro_skipper_mod.segment_bounds({"Introduction": {"Start": 10.0}}, "Introduction") is None
