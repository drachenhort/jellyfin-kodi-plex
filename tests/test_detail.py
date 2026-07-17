"""Tests for lib.windows.detail's pure metadata-line helper, covering the
new music-track branch alongside its existing movie/episode behavior.
"""

from lib.windows.detail import _meta_line


def test_meta_line_movie_unchanged():
    item = {
        "ProductionYear": 1979,
        "RunTimeTicks": 72_000_000_000,
        "CommunityRating": 8.4,
        "Genres": ["Horror", "Sci-Fi"],
    }
    assert _meta_line(item) == "1979  •  120 min  •  8.4★  •  Horror, Sci-Fi"


def test_meta_line_track_shows_artist_and_album():
    item = {
        "Type": "Audio",
        "Artists": ["Radiohead"],
        "Album": "OK Computer",
        "ProductionYear": 1997,
        "RunTimeTicks": 4 * 60 * 10_000_000,
    }
    assert _meta_line(item) == "Radiohead  •  OK Computer  •  1997  •  4 min"


def test_meta_line_track_falls_back_to_album_artist():
    item = {"Type": "Audio", "AlbumArtist": "Various Artists", "Album": "Compilation"}
    assert _meta_line(item) == "Various Artists  •  Compilation"


def test_meta_line_track_with_no_artist_or_album_omits_them():
    item = {"Type": "Audio", "RunTimeTicks": 3 * 60 * 10_000_000}
    assert _meta_line(item) == "3 min"
