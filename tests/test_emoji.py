from lib.emoji import replace_shortcodes
from lib.windows.kodigui import list_item


def test_known_shortcode_replaced() -> None:
    assert replace_shortcodes("Fun :smile: night :fire:") == "Fun 😄 night 🔥"


def test_unknown_shortcode_and_times_untouched() -> None:
    assert replace_shortcodes(":nope: at 12:30:45") == ":nope: at 12:30:45"


def test_empty_and_plain() -> None:
    assert replace_shortcodes("") == ""
    assert replace_shortcodes("plain") == "plain"


def test_list_item_title_converted() -> None:
    li = list_item({"Name": "Love :heart:", "Overview": "so :joy:", "Type": "Movie"})
    assert li.getLabel() == "Love ❤️"
    assert li.getProperty("overview") == "so 😂"
