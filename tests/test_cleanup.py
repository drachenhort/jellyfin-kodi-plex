"""Tests for CleanupWindow: watched movies on the left, the persisted
to-be-deleted list on the right, and deleting everything on that list.

onInit() runs _load() on a background thread, so these tests call _load()
directly; deletion threads are run inline via _run_threads_inline."""

import pytest
import xbmcaddon

import lib.windows.cleanup as cleanup_mod
from lib import delete_queue

MOVIES = [
    {"Id": "m1", "Name": "Alien", "Type": "Movie", "ProductionYear": 1979,
     "RunTimeTicks": 117 * 60 * 10_000_000,
     "UserData": {"Played": True, "LastPlayedDate": "2026-05-01T20:00:00Z"}},
    {"Id": "m2", "Name": "Brazil", "Type": "Movie", "UserData": {"Played": True}},
    {"Id": "m3", "Name": "Cube", "Type": "Movie", "UserData": {"Played": True}},
]


class _FakeDialog:
    def __init__(self, confirm=True):
        self.confirm = confirm
        self.asked = []
        self.notifications = []

    def __call__(self):
        return self

    def yesno(self, heading, message, *a, **k):
        self.asked.append(message)
        return self.confirm

    def notification(self, heading, message, *a, **k):
        self.notifications.append(message)


def _run_threads_inline(monkeypatch):
    class _InlineThread:
        def __init__(self, target, args=(), daemon=None):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(cleanup_mod.threading, "Thread", _InlineThread)


TV = [
    {"Id": "t1", "Name": "Lost", "Type": "Series", "ChildCount": 6, "UserData": {"Played": True}},
    {"Id": "s1", "Name": "Season 1", "Type": "Season", "SeriesName": "Dark", "ChildCount": 10,
     "UserData": {"Played": True}},
]


def _window(client, monkeypatch, movies=None, saved_queue=None, tv=None, tv_error=None):
    addon = xbmcaddon.Addon()
    key = delete_queue.queue_key(client.server_url, client.user_id)
    if saved_queue is not None:
        addon.setSetting(cleanup_mod.DELETE_QUEUE_SETTING, delete_queue.save("", key, saved_queue))
    monkeypatch.setattr(cleanup_mod, "ADDON", addon)
    monkeypatch.setattr(cleanup_mod.library, "get_watched_movies", lambda c: list(MOVIES if movies is None else movies))

    def watched_tv(c):
        if tv_error:
            raise tv_error
        return list(tv or [])

    monkeypatch.setattr(cleanup_mod.library, "get_watched_tv", watched_tv)
    monkeypatch.setattr(cleanup_mod.images, "primary_image_url", lambda *a, **k: None)
    window = cleanup_mod.CleanupWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client)
    window._load()
    return window


def _ids(window, control_id):
    return [li.getProperty("jellyfin_id") for li in window.getControl(control_id).items]


def _saved(window):
    return delete_queue.load(cleanup_mod.ADDON.getSetting(cleanup_mod.DELETE_QUEUE_SETTING), window.queue_key)


def test_meta_text_shows_year_runtime_and_last_watched():
    assert cleanup_mod._meta_text(MOVIES[0]) == "1979  •  1h 57min  •  watched 2026-05-01"


def test_load_lists_watched_movies_and_empty_queue(client, monkeypatch):
    window = _window(client, monkeypatch)
    assert _ids(window, cleanup_mod.CTRL_WATCHED_LIST) == ["m1", "m2", "m3"]
    assert _ids(window, cleanup_mod.CTRL_QUEUE_LIST) == []
    assert window.getControl(cleanup_mod.CTRL_DELETE_BUTTON).getLabel() == "Nothing to delete"


def test_load_restores_saved_queue_and_drops_stale_ids(client, monkeypatch):
    window = _window(client, monkeypatch, saved_queue=["m3", "gone"])
    assert _ids(window, cleanup_mod.CTRL_WATCHED_LIST) == ["m1", "m2"]
    assert _ids(window, cleanup_mod.CTRL_QUEUE_LIST) == ["m3"]
    assert _saved(window) == ["m3"]


def test_selecting_watched_movie_moves_it_to_queue_and_persists(client, monkeypatch):
    window = _window(client, monkeypatch)
    window.getControl(cleanup_mod.CTRL_WATCHED_LIST).selectItem(1)

    window.handle_click(cleanup_mod.CTRL_WATCHED_LIST)

    assert _ids(window, cleanup_mod.CTRL_WATCHED_LIST) == ["m1", "m3"]
    assert _ids(window, cleanup_mod.CTRL_QUEUE_LIST) == ["m2"]
    assert _saved(window) == ["m2"]
    assert window.getControl(cleanup_mod.CTRL_DELETE_BUTTON).getLabel() == "Delete 1 movie"
    assert window.getControl(cleanup_mod.CTRL_QUEUE_HEADER).getLabel() == "To Be Deleted (1)"


def test_selecting_queued_movie_moves_it_back(client, monkeypatch):
    window = _window(client, monkeypatch, saved_queue=["m1", "m2"])
    window.getControl(cleanup_mod.CTRL_QUEUE_LIST).selectItem(0)

    window.handle_click(cleanup_mod.CTRL_QUEUE_LIST)

    assert _ids(window, cleanup_mod.CTRL_QUEUE_LIST) == ["m2"]
    assert _ids(window, cleanup_mod.CTRL_WATCHED_LIST) == ["m1", "m3"]
    assert _saved(window) == ["m2"]


def test_moving_last_watched_movie_focuses_queue(client, monkeypatch):
    window = _window(client, monkeypatch, movies=[MOVIES[0]])

    window.handle_click(cleanup_mod.CTRL_WATCHED_LIST)

    assert window.getFocusId() == cleanup_mod.CTRL_QUEUE_LIST


def test_delete_with_empty_queue_only_notifies(client, monkeypatch):
    window = _window(client, monkeypatch)
    dialog = _FakeDialog()
    monkeypatch.setattr(cleanup_mod.xbmcgui, "Dialog", dialog)

    window.handle_click(cleanup_mod.CTRL_DELETE_BUTTON)

    assert dialog.asked == []
    assert dialog.notifications == ["The to-be-deleted list is empty"]


def test_delete_cancelled_keeps_everything(client, monkeypatch):
    window = _window(client, monkeypatch, saved_queue=["m1"])
    monkeypatch.setattr(cleanup_mod.xbmcgui, "Dialog", _FakeDialog(confirm=False))
    _run_threads_inline(monkeypatch)
    deleted = []
    monkeypatch.setattr(cleanup_mod.library, "delete_item", lambda c, i: deleted.append(i))

    window.handle_click(cleanup_mod.CTRL_DELETE_BUTTON)

    assert deleted == []
    assert _saved(window) == ["m1"]
    # Clicks are re-enabled and the status line restored after cancelling.
    assert window.deleting is False
    assert window.getControl(cleanup_mod.CTRL_STATUS).getLabel() == "Select an item to move it between the two lists"


def test_delete_removes_all_queued_movies(client, monkeypatch):
    window = _window(client, monkeypatch, saved_queue=["m1", "m3"])
    dialog = _FakeDialog()
    monkeypatch.setattr(cleanup_mod.xbmcgui, "Dialog", dialog)
    _run_threads_inline(monkeypatch)
    deleted = []
    monkeypatch.setattr(cleanup_mod.library, "delete_item", lambda c, i: deleted.append(i))

    window.handle_click(cleanup_mod.CTRL_DELETE_BUTTON)

    assert "2 movies" in dialog.asked[0]
    assert deleted == ["m1", "m3"]
    assert dialog.notifications == ["Deleted 2 movies"]
    assert _ids(window, cleanup_mod.CTRL_WATCHED_LIST) == ["m2"]
    assert _ids(window, cleanup_mod.CTRL_QUEUE_LIST) == []
    assert _saved(window) == []
    assert window.deleting is False


def test_failed_delete_stays_queued(client, monkeypatch):
    window = _window(client, monkeypatch, saved_queue=["m1", "m2"])
    dialog = _FakeDialog()
    monkeypatch.setattr(cleanup_mod.xbmcgui, "Dialog", dialog)
    _run_threads_inline(monkeypatch)

    def fake_delete(c, item_id):
        if item_id == "m1":
            raise RuntimeError("forbidden")

    monkeypatch.setattr(cleanup_mod.library, "delete_item", fake_delete)

    window.handle_click(cleanup_mod.CTRL_DELETE_BUTTON)

    assert dialog.notifications == ["Deleted 1 movie, 1 failed: Alien"]
    assert _ids(window, cleanup_mod.CTRL_QUEUE_LIST) == ["m1"]
    assert _saved(window) == ["m1"]


def test_load_failure_shows_status(client, monkeypatch):
    monkeypatch.setattr(cleanup_mod, "ADDON", xbmcaddon.Addon())

    def boom(c):
        raise RuntimeError("timeout")

    monkeypatch.setattr(cleanup_mod.library, "get_watched_movies", boom)
    monkeypatch.setattr(cleanup_mod.library, "get_watched_tv", lambda c: [])
    window = cleanup_mod.CleanupWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client)

    window._load()

    assert "timeout" in window.getControl(cleanup_mod.CTRL_STATUS).getLabel()


def test_no_watched_movies_shows_status(client, monkeypatch):
    window = _window(client, monkeypatch, movies=[])
    assert window.getControl(cleanup_mod.CTRL_STATUS).getLabel() == "No watched movies you can delete"


@pytest.fixture(autouse=True)
def _no_size_lookup(monkeypatch):
    """The delete confirmation looks up file sizes over the network - keep
    every test here offline with a fixed summary."""
    monkeypatch.setattr(cleanup_mod.library, "get_media_summary",
                        lambda c, ids: {"files": len(ids), "bytes": 0, "unknown_sizes": 0})


def test_meta_text_for_series_and_season():
    assert cleanup_mod._meta_text(TV[0]) == "Show  •  6 seasons"
    assert cleanup_mod._meta_text(TV[1]) == "Season  •  10 episodes"


def test_mode_button_switches_left_list_to_tv(client, monkeypatch):
    window = _window(client, monkeypatch, tv=TV)
    assert window.getControl(cleanup_mod.CTRL_MODE_BUTTON).getLabel() == "Show TV Shows"

    window.handle_click(cleanup_mod.CTRL_MODE_BUTTON)

    assert _ids(window, cleanup_mod.CTRL_WATCHED_LIST) == ["t1", "s1"]
    labels = [li.getLabel() for li in window.getControl(cleanup_mod.CTRL_WATCHED_LIST).items]
    assert labels == ["Lost", "Dark – Season 1"]
    assert window.getControl(cleanup_mod.CTRL_WATCHED_HEADER).getLabel() == "Watched TV Shows (2)"
    assert window.getControl(cleanup_mod.CTRL_MODE_BUTTON).getLabel() == "Show Movies"


def test_queue_is_shared_across_modes(client, monkeypatch):
    window = _window(client, monkeypatch, tv=TV, saved_queue=["m1"])
    window.handle_click(cleanup_mod.CTRL_MODE_BUTTON)

    window.handle_click(cleanup_mod.CTRL_WATCHED_LIST)  # queue "Lost"

    assert _ids(window, cleanup_mod.CTRL_QUEUE_LIST) == ["m1", "t1"]
    assert window.getControl(cleanup_mod.CTRL_DELETE_BUTTON).getLabel() == "Delete 1 movie and 1 show"


def test_delete_covers_movies_and_tv(client, monkeypatch):
    window = _window(client, monkeypatch, tv=TV, saved_queue=["m1", "t1", "s1"])
    dialog = _FakeDialog()
    monkeypatch.setattr(cleanup_mod.xbmcgui, "Dialog", dialog)
    _run_threads_inline(monkeypatch)
    deleted = []
    monkeypatch.setattr(cleanup_mod.library, "delete_item", lambda c, i: deleted.append(i))

    window.handle_click(cleanup_mod.CTRL_DELETE_BUTTON)

    assert "1 movie, 1 show and 1 season" in dialog.asked[0]
    assert deleted == ["m1", "t1", "s1"]
    assert dialog.notifications == ["Deleted 1 movie, 1 show and 1 season"]
    assert _saved(window) == []


def test_failed_tv_load_keeps_movies_and_preserves_queued_shows(client, monkeypatch):
    window = _window(client, monkeypatch, saved_queue=["m1", "t1"], tv_error=RuntimeError("timeout"))

    assert _ids(window, cleanup_mod.CTRL_QUEUE_LIST) == ["m1"]
    assert "Couldn't load TV shows: timeout" in window.getControl(cleanup_mod.CTRL_STATUS).getLabel()
    assert _saved(window) == ["m1", "t1"]

    window.getControl(cleanup_mod.CTRL_QUEUE_LIST).selectItem(0)
    window.handle_click(cleanup_mod.CTRL_QUEUE_LIST)  # un-queue m1

    assert _saved(window) == ["t1"]
