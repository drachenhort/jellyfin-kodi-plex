import lib.windows.next_episode_overlay as next_episode_overlay_mod


def _window(client=None, next_item=None, auto_dismiss_seconds=next_episode_overlay_mod.AUTO_DISMISS_SECONDS):
    window = next_episode_overlay_mod.NextEpisodeOverlay(None, "/fake/addon/path", "Main", "1080i")
    window.setup(client=client, next_item=next_item, auto_dismiss_seconds=auto_dismiss_seconds)
    return window


def test_onInit_populates_name_and_thumb(client):
    next_item = {"Id": "e2", "Name": "The Trial", "ImageTags": {"Primary": "tag123"}}
    window = _window(client=client, next_item=next_item)

    window.onInit()

    assert window.getControl(next_episode_overlay_mod.CTRL_EPISODE_NAME).getLabel() == "The Trial"
    assert "tag123" in window.getControl(next_episode_overlay_mod.CTRL_THUMB).image


def test_onInit_falls_back_to_placeholder_art_with_no_image_tags(client):
    next_item = {"Id": "e2", "Name": "The Trial"}
    window = _window(client=client, next_item=next_item)

    window.onInit()

    expected = next_episode_overlay_mod.placeholder_art(next_item)
    assert window.getControl(next_episode_overlay_mod.CTRL_THUMB).image == expected


def test_play_now_click_sets_play_result_and_closes():
    window = _window(next_item={"Id": "e2"})

    window.handle_click(next_episode_overlay_mod.CTRL_PLAY_NOW)

    assert window.result == {"action": "play"}
    assert window.closed


def test_dismiss_click_sets_no_result_and_closes():
    window = _window(next_item={"Id": "e2"})

    window.handle_click(next_episode_overlay_mod.CTRL_DISMISS)

    assert window.result is None
    assert window.closed


def test_auto_dismiss_none_returns_once_closed_without_touching_result():
    # AUTO_DISMISS_SECONDS=None means "stay up for the rest of playback" -
    # the caller (lib/player.py) closes it, not the timer.
    window = _window(next_item={"Id": "e2"}, auto_dismiss_seconds=None)
    window.result = {"action": "play"}  # simulate a click having already set this
    window.closed_event.set()

    window._auto_dismiss()

    assert window.result == {"action": "play"}


def test_auto_dismiss_finite_timeout_dismisses_with_no_interaction():
    window = _window(next_item={"Id": "e2"}, auto_dismiss_seconds=0)

    window._auto_dismiss()

    assert window.result is None
    assert window.closed


def test_auto_dismiss_finite_timeout_does_not_overwrite_existing_click():
    window = _window(next_item={"Id": "e2"}, auto_dismiss_seconds=30)
    window.result = {"action": "play"}  # simulate Play Now already clicked
    window.closed_event.set()

    window._auto_dismiss()

    assert window.result == {"action": "play"}
