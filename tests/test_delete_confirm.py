"""Tests for the shared delete confirmation: file count/size summary
lookup and the dialog message built from it."""

import lib.windows.delete_confirm as confirm_mod
from lib.jellyfin import library
import lib.jellyfin.client as client_mod
from tests.fakes import FakeRequests, FakeResponse


def test_format_bytes():
    assert confirm_mod.format_bytes(0) == "0 bytes"
    assert confirm_mod.format_bytes(1536) == "1.5 KB"
    assert confirm_mod.format_bytes(5 * 1024 ** 3) == "5.0 GB"
    assert confirm_mod.format_bytes(3 * 1024 ** 5) == "3072.0 TB"


def test_message_for_several_movies_shows_files_and_size():
    movies = [{"Name": "A", "Type": "Movie"}, {"Name": "B", "Type": "Movie"}]
    summary = {"files": 3, "bytes": 6 * 1024 ** 3, "unknown_sizes": 0}
    assert confirm_mod.build_message(movies, summary) == (
        "Permanently delete 2 movies from the server?[CR]"
        "3 files, 6.0 GB total.[CR]This cannot be undone."
    )


def test_message_for_single_movie_names_it():
    summary = {"files": 1, "bytes": 1024 ** 3, "unknown_sizes": 0}
    message = confirm_mod.build_message([{"Name": "Alien"}], summary)
    assert message.startswith("Permanently delete 'Alien' from the server?[CR]1 file, 1.0 GB total.")


def test_message_marks_size_as_lower_bound_when_some_unknown():
    summary = {"files": 2, "bytes": 1024 ** 3, "unknown_sizes": 1}
    assert "2 files, at least 1.0 GB (size unknown for 1)." in confirm_mod.build_message([{}, {}], summary)


def test_message_when_lookup_failed():
    assert "couldn't be determined" in confirm_mod.build_message([{}], None)


def test_confirm_still_asks_when_lookup_fails(monkeypatch):
    def boom(c, ids):
        raise RuntimeError("timeout")

    monkeypatch.setattr(confirm_mod.library, "get_media_summary", boom)
    asked = []

    class _Dialog:
        def yesno(self, heading, message, **k):
            asked.append(message)
            return True

    monkeypatch.setattr(confirm_mod.xbmcgui, "Dialog", _Dialog)

    assert confirm_mod.confirm_delete(object(), [{"Id": "m1", "Name": "Alien"}]) is True
    assert "couldn't be determined" in asked[0]


def test_get_media_summary_counts_sources_and_bytes(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": [
        {"Id": "m1", "MediaSources": [{"Size": 100}, {"Size": 50}]},
        {"Id": "m2", "MediaSources": [{}]},
        {"Id": "m3"},
    ]})])
    monkeypatch.setattr(client_mod, "requests", fake)

    summary = library.get_media_summary(
        client, [{"Id": "m1", "Type": "Movie"}, {"Id": "m2", "Type": "Movie"}, {"Id": "m3", "Type": "Movie"}]
    )

    assert summary == {"files": 3, "bytes": 150, "unknown_sizes": 1}
    assert fake.calls[0]["params"] == {"Ids": "m1,m2,m3", "Fields": "MediaSources"}


def test_get_media_summary_chunks_long_id_lists(client, monkeypatch):
    fake = FakeRequests([FakeResponse({"Items": []}), FakeResponse({"Items": []})])
    monkeypatch.setattr(client_mod, "requests", fake)

    library.get_media_summary(
        client, [{"Id": f"m{i}", "Type": "Movie"} for i in range(library.MEDIA_SUMMARY_CHUNK + 1)]
    )

    assert len(fake.calls) == 2
    assert fake.calls[1]["params"]["Ids"] == f"m{library.MEDIA_SUMMARY_CHUNK}"


def test_get_media_summary_walks_episodes_of_series_and_seasons(client, monkeypatch):
    fake = FakeRequests([
        FakeResponse({"Items": [{"MediaSources": [{"Size": 10}]}, {"MediaSources": [{"Size": 20}]}]}),
        FakeResponse({"Items": [{"MediaSources": [{"Size": 5}]}]}),
    ])
    monkeypatch.setattr(client_mod, "requests", fake)

    summary = library.get_media_summary(client, [{"Id": "t1", "Type": "Series"}, {"Id": "s1", "Type": "Season"}])

    assert summary == {"files": 3, "bytes": 35, "unknown_sizes": 0}
    assert fake.calls[0]["params"]["ParentId"] == "t1"
    assert fake.calls[0]["params"]["IncludeItemTypes"] == "Episode"
    assert fake.calls[1]["params"]["ParentId"] == "s1"


def test_item_name_prefixes_season_with_show():
    assert confirm_mod.item_name({"Name": "Season 2", "Type": "Season", "SeriesName": "Lost"}) == "Lost – Season 2"
    assert confirm_mod.item_name({"Name": "Lost", "Type": "Series"}) == "Lost"


def test_describe_count():
    assert confirm_mod.describe_count([{"Type": "Movie"}] * 3) == "3 movies"
    assert confirm_mod.describe_count([{"Type": "Series"}, {"Type": "Season"}, {"Type": "Season"}]) == (
        "1 show and 2 seasons"
    )
    assert confirm_mod.describe_count([{"Type": "Movie"}, {"Type": "Series"}, {"Type": "Season"}]) == (
        "1 movie, 1 show and 1 season"
    )
    assert confirm_mod.describe_count([]) == "0 items"


def test_result_message():
    assert confirm_mod.result_message([{"Type": "Series"}], []) == "Deleted 1 show"
    failed = [{"Type": "Season", "Name": "Season 1", "SeriesName": "Dark"}]
    assert confirm_mod.result_message([], failed) == "Deleted 0 items, 1 failed: Dark – Season 1"
