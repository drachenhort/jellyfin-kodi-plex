"""Tests for HomeWindow's hub-row population, in particular the Recently
Added Music row added alongside the existing Movies/TV rows.
"""

import lib.windows.home as home_mod


def _make_window(client):
    window = home_mod.HomeWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client)
    return window


def test_recently_added_music_populated_from_music_library(client, monkeypatch):
    views = [
        {"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"},
        {"Id": "lib-music", "Name": "Music", "CollectionType": "music"},
    ]
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: views)
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])

    def fake_get_latest(c, parent_id=None, limit=10):
        if parent_id == "lib-music":
            return [{"Id": "album-1", "Name": "OK Computer", "Type": "MusicAlbum"}]
        return []

    monkeypatch.setattr(home_mod.library, "get_latest", fake_get_latest)

    window = _make_window(client)
    window.onInit()

    music_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC)
    assert [li.getLabel() for li in music_row.items] == ["OK Computer"]
    assert music_row.items[0].getProperty("jellyfin_id") == "album-1"
    assert music_row.items[0].getProperty("jellyfin_type") == "MusicAlbum"

    # Movies row still only pulls from the movies-CollectionType view.
    movies_row = window.getControl(home_mod.CTRL_RECENTLY_ADDED_MOVIES)
    assert movies_row.items == []


def test_recently_added_music_empty_when_no_music_library(client, monkeypatch):
    monkeypatch.setattr(home_mod.library, "get_views", lambda c: [
        {"Id": "lib-movies", "Name": "Movies", "CollectionType": "movies"},
    ])
    monkeypatch.setattr(home_mod.library, "get_resume", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_next_up", lambda c: [])
    monkeypatch.setattr(home_mod.library, "get_latest", lambda c, parent_id=None, limit=10: [])

    window = _make_window(client)
    window.onInit()

    assert window.getControl(home_mod.CTRL_RECENTLY_ADDED_MUSIC).items == []
