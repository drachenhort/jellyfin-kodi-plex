import lib.windows.next_episode as next_episode_mod


def _window(client=None, next_item=None, countdown_seconds=0):
    window = next_episode_mod.NextEpisodeWindow(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client, next_item=next_item, countdown_seconds=countdown_seconds)
    return window


def test_onInit_populates_title_episode_code_and_thumb(client):
    next_item = {
        "Id": "e2", "Name": "The Trial", "ParentIndexNumber": 1, "IndexNumber": 2,
        "ImageTags": {"Primary": "tag123"},
    }
    window = _window(client=client, next_item=next_item)

    window.onInit()

    assert window.getControl(next_episode_mod.CTRL_TITLE).getLabel() == "The Trial"
    assert window.getControl(next_episode_mod.CTRL_EPISODE_CODE).getLabel() == "1x02"
    assert "tag123" in window.getControl(next_episode_mod.CTRL_THUMB).image


def test_onInit_falls_back_to_placeholder_art_with_no_image_tags(client):
    next_item = {"Id": "e2", "Name": "The Trial", "IndexNumber": 2}
    window = _window(client=client, next_item=next_item)

    window.onInit()

    assert window.getControl(next_episode_mod.CTRL_THUMB).image == next_episode_mod.placeholder_art(next_item)


def test_play_now_click_sets_play_result_and_closes():
    window = _window(next_item={"Id": "e2"})

    window.handle_click(next_episode_mod.CTRL_PLAY_NOW)

    assert window.result == {"action": "play"}
    assert window.closed


def test_cancel_click_sets_no_result_and_closes():
    window = _window(next_item={"Id": "e2"})

    window.handle_click(next_episode_mod.CTRL_CANCEL)

    assert window.result is None
    assert window.closed


def test_countdown_reaching_zero_auto_plays():
    window = _window(next_item={"Id": "e2"}, countdown_seconds=0)

    window._run_countdown()

    assert window.result == {"action": "play"}
    assert window.closed


def test_countdown_stops_early_if_window_already_closed():
    window = _window(next_item={"Id": "e2"}, countdown_seconds=30)
    window.closed_event.set()  # simulate Cancel/Back already having closed it

    window._run_countdown()

    # Must not overwrite a result the click handler already set.
    assert window.result is None
