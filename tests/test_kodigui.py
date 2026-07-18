"""Tests for the pure helpers in lib.windows.kodigui: the caption/rating
text builders used across Home/Browse/Detail, list_item()'s property
setting, and WindowMixin's Back-action handling.
"""

import time

from lib.windows.kodigui import (
    PLACEHOLDER_ART,
    PLACEHOLDER_ART_MUSIC,
    ControlledWindow,
    _display_label,
    _episode_code,
    _progress_text,
    _ratings_text,
    _unwatched_count_text,
    list_item,
    placeholder_art,
    progress_percent,
)


class FakeAction:
    def __init__(self, action_id):
        self._id = action_id

    def getId(self):
        return self._id


# -- _display_label -----------------------------------------------------

def test_display_label_plain_item():
    assert _display_label({"Name": "Alien"}) == "Alien"


def test_display_label_episode_gets_season_episode_prefix():
    item = {"Name": "Redemption", "Type": "Episode", "ParentIndexNumber": 4, "IndexNumber": 12}
    assert _display_label(item) == "4x12. Redemption"


def test_display_label_episode_missing_numbers_falls_back_to_plain_name():
    item = {"Name": "Redemption", "Type": "Episode", "ParentIndexNumber": None, "IndexNumber": 12}
    assert _display_label(item) == "Redemption"


def test_display_label_audio_track_gets_index_prefix():
    item = {"Name": "Track One", "Type": "Audio", "IndexNumber": 3}
    assert _display_label(item) == "3. Track One"


# -- _episode_code --------------------------------------------------------

def test_episode_code_for_episode():
    item = {"Type": "Episode", "ParentIndexNumber": 4, "IndexNumber": 12}
    assert _episode_code(item) == "4x12"


def test_episode_code_empty_for_non_episode():
    assert _episode_code({"Type": "Movie"}) == ""


def test_episode_code_empty_when_numbers_missing():
    assert _episode_code({"Type": "Episode", "ParentIndexNumber": None, "IndexNumber": 3}) == ""


# -- _progress_text --------------------------------------------------------

def test_progress_text_partially_watched():
    item = {
        "UserData": {"PlaybackPositionTicks": 18_000_000_000},
        "RunTimeTicks": 72_000_000_000,
    }
    assert _progress_text(item) == "25% watched · 90 min left"


def test_progress_text_empty_when_not_started():
    item = {"UserData": {"PlaybackPositionTicks": 0}, "RunTimeTicks": 72_000_000_000}
    assert _progress_text(item) == ""


def test_progress_text_empty_when_no_runtime():
    item = {"UserData": {"PlaybackPositionTicks": 1000}, "RunTimeTicks": 0}
    assert _progress_text(item) == ""


def test_progress_text_minutes_left_floors_to_at_least_one():
    item = {
        "UserData": {"PlaybackPositionTicks": 71_999_999_999},
        "RunTimeTicks": 72_000_000_000,
    }
    assert _progress_text(item) == "100% watched · 1 min left"


# -- _ratings_text --------------------------------------------------------

def test_ratings_text_both_present():
    item = {"CommunityRating": 6.734, "CriticRating": 80}
    assert _ratings_text(item) == "TMDb 6.7 · RT 80%"


def test_ratings_text_community_only():
    assert _ratings_text({"CommunityRating": 7.0}) == "TMDb 7.0"


def test_ratings_text_critic_only():
    assert _ratings_text({"CriticRating": 55}) == "RT 55%"


def test_ratings_text_empty_when_neither_present():
    assert _ratings_text({}) == ""


def test_ratings_text_critic_zero_is_not_treated_as_missing():
    assert _ratings_text({"CriticRating": 0}) == "RT 0%"


# -- _unwatched_count_text -------------------------------------------------

def test_unwatched_count_text_for_series_with_remaining_episodes():
    item = {"Type": "Series", "UserData": {"UnplayedItemCount": 7}}
    assert _unwatched_count_text(item) == "7"


def test_unwatched_count_text_empty_when_fully_watched():
    item = {"Type": "Series", "UserData": {"UnplayedItemCount": 0}}
    assert _unwatched_count_text(item) == ""


def test_unwatched_count_text_empty_when_field_absent():
    assert _unwatched_count_text({"Type": "Movie"}) == ""


def test_unwatched_count_text_caps_at_99_plus():
    item = {"Type": "Series", "UserData": {"UnplayedItemCount": 143}}
    assert _unwatched_count_text(item) == "99+"


def test_unwatched_count_text_not_capped_at_exactly_99():
    item = {"Type": "Series", "UserData": {"UnplayedItemCount": 99}}
    assert _unwatched_count_text(item) == "99"


# -- list_item --------------------------------------------------------

def test_list_item_sets_placeholder_art_when_none_given():
    li = list_item({"Id": "1", "Name": "Alien", "Type": "Movie"})
    assert li.art["thumb"] == PLACEHOLDER_ART
    assert li.art["poster"] == PLACEHOLDER_ART
    assert "fanart" not in li.art


def test_list_item_sets_music_placeholder_for_a_track():
    li = list_item({"Id": "1", "Name": "One", "Type": "Audio"})
    assert li.art["thumb"] == PLACEHOLDER_ART_MUSIC
    assert li.art["poster"] == PLACEHOLDER_ART_MUSIC


def test_placeholder_art_for_music_item_types():
    for item_type in ("Audio", "MusicAlbum", "MusicArtist"):
        assert placeholder_art({"Type": item_type}) == PLACEHOLDER_ART_MUSIC


def test_placeholder_art_for_music_collection_view():
    assert placeholder_art({"CollectionType": "music"}) == PLACEHOLDER_ART_MUSIC


def test_placeholder_art_defaults_to_generic():
    assert placeholder_art({"Type": "Movie"}) == PLACEHOLDER_ART
    assert placeholder_art({"CollectionType": "movies"}) == PLACEHOLDER_ART
    assert placeholder_art({}) == PLACEHOLDER_ART


def test_list_item_uses_given_art():
    li = list_item({"Id": "1", "Name": "Alien"}, primary_art="poster.jpg", backdrop_art="fanart.jpg")
    assert li.art["thumb"] == "poster.jpg"
    assert li.art["poster"] == "poster.jpg"
    assert li.art["fanart"] == "fanart.jpg"


def test_list_item_sets_properties():
    item = {
        "Id": "abc",
        "Name": "Redemption",
        "Type": "Episode",
        "SeriesName": "The Wire",
        "ParentIndexNumber": 1,
        "IndexNumber": 1,
        "UserData": {"PlaybackPositionTicks": 18_000_000_000},
        "RunTimeTicks": 72_000_000_000,
        "CommunityRating": 9.1,
    }
    li = list_item(item)
    assert li.getProperty("jellyfin_id") == "abc"
    assert li.getProperty("jellyfin_type") == "Episode"
    assert li.getProperty("series_name") == "The Wire"
    assert li.getProperty("episode_code") == "1x01"
    assert li.getProperty("progress_text") == "25% watched · 90 min left"
    assert li.getProperty("ratings_text") == "TMDb 9.1"


def test_list_item_video_info_tag_fields():
    item = {
        "Id": "1",
        "Name": "Alien",
        "Overview": "A crew investigates a distress signal.",
        "ProductionYear": 1979,
        "Genres": ["Horror", "Sci-Fi"],
        "RunTimeTicks": 72_000_000_000,
    }
    li = list_item(item)
    info = li.getVideoInfoTag()
    assert info.title == "Alien"
    assert info.plot == "A crew investigates a distress signal."
    assert info.year == 1979
    assert info.genres == ["Horror", "Sci-Fi"]
    assert info.duration == 7200


def test_list_item_sets_resume_point_when_partially_watched():
    item = {"Id": "1", "Name": "Alien", "UserData": {"PlaybackPositionTicks": 18_000_000_000}}
    li = list_item(item)
    assert li.getVideoInfoTag().resume_point == 1800.0


def test_list_item_no_resume_point_when_unwatched():
    li = list_item({"Id": "1", "Name": "Alien"})
    assert li.getVideoInfoTag().resume_point is None


def test_list_item_watched_property_set_when_played():
    li = list_item({"Id": "1", "Name": "Alien", "UserData": {"Played": True}})
    assert li.getProperty("watched") == "true"


def test_list_item_watched_property_empty_when_not_played():
    li = list_item({"Id": "1", "Name": "Alien", "UserData": {"Played": False}})
    assert li.getProperty("watched") == ""


def test_list_item_watched_property_empty_when_no_user_data():
    li = list_item({"Id": "1", "Name": "Alien"})
    assert li.getProperty("watched") == ""


def test_list_item_unwatched_count_property():
    item = {"Id": "1", "Name": "The Wire", "Type": "Series", "UserData": {"UnplayedItemCount": 12}}
    li = list_item(item)
    assert li.getProperty("unwatched_count") == "12"


def test_list_item_unwatched_count_property_empty_when_fully_watched():
    item = {"Id": "1", "Name": "The Wire", "Type": "Series", "UserData": {"UnplayedItemCount": 0}}
    li = list_item(item)
    assert li.getProperty("unwatched_count") == ""


# -- progress_percent ------------------------------------------------------

def test_progress_percent_starts_at_zero():
    assert progress_percent(time.time()) == 0


def test_progress_percent_climbs_toward_but_never_exceeds_the_ceiling():
    # A "started" far enough in the past that the curve has essentially
    # flattened out - at the ceiling, never over it.
    percent = progress_percent(time.time() - 600, ceiling=95, tau=8.0)
    assert 90 <= percent <= 95


def test_progress_percent_never_exceeds_the_ceiling_even_given_bad_input():
    # A "started" in the future (elapsed < 0) shouldn't wrap into a huge or
    # negative percentage.
    assert progress_percent(time.time() + 1000) == 0


def test_progress_percent_is_monotonically_non_decreasing_over_time():
    now = time.time()
    percent_at_5s = progress_percent(now - 5, tau=8.0)
    percent_at_20s = progress_percent(now - 20, tau=8.0)
    assert percent_at_20s >= percent_at_5s


# -- WindowMixin Back-action handling --------------------------------------

def test_back_action_clears_result_and_closes():
    window = ControlledWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup()
    window.result = {"action": "something"}

    window.onAction(FakeAction(10))  # ACTION_PREVIOUS_MENU

    assert window.result is None
    assert window.closed
    assert window.closed_event.is_set()


def test_nav_back_action_also_closes():
    window = ControlledWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup()

    window.onAction(FakeAction(92))  # ACTION_NAV_BACK

    assert window.result is None
    assert window.closed


def test_non_back_action_delegates_to_handle_action():
    seen = []

    class Recording(ControlledWindow):
        def handle_action(self, action):
            seen.append(action.getId())

    window = Recording(None, "/fake/addon/path", "Main", "1080i")
    window.setup()

    window.onAction(FakeAction(999))

    assert seen == [999]
    assert not window.closed


def test_on_click_delegates_to_handle_click():
    seen = []

    class Recording(ControlledWindow):
        def handle_click(self, control_id):
            seen.append(control_id)

    window = Recording(None, "/fake/addon/path", "Main", "1080i")
    window.setup()

    window.onClick(204)

    assert seen == [204]
