import lib.windows.skip_intro_overlay as skip_intro_overlay_mod


def _window():
    window = skip_intro_overlay_mod.SkipIntroOverlay(None, "/fake/addon/path", "Main", "1080i")
    window.setup()
    return window


def test_skip_click_sets_skip_result_and_closes():
    window = _window()

    window.handle_click(skip_intro_overlay_mod.CTRL_SKIP)

    assert window.result == {"action": "skip"}
    assert window.closed


def test_other_click_does_not_set_result_or_close():
    window = _window()

    window.handle_click(999)

    assert window.result is None
    assert not window.closed
