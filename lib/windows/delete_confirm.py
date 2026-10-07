"""Shared "are you sure?" step for every delete entry point (Detail's Delete
button, the Movies/TV wall and season-list context menus, the Clean Up
screen): looks up how many files and bytes the deletion covers and shows
that summary in the confirmation dialog. Also the shared naming helpers
(item_name, describe_count) so every screen words items the same way.

confirm_delete() does a network lookup, so call it off the GUI thread."""

import xbmc
import xbmcgui

from lib.jellyfin import library
from lib.emoji import replace_shortcodes
from lib.windows.kodigui import LOG_PREFIX

_UNITS = ("bytes", "KB", "MB", "GB", "TB")

# (singular, plural) per deletable item type, in display order.
_NOUNS = {"Movie": ("movie", "movies"), "Series": ("show", "shows"), "Season": ("season", "seasons")}


def item_name(item: dict) -> str:
    """"Alien", "Breaking Bad", or "Breaking Bad – Season 2" - a Season's
    own Name alone ("Season 2") doesn't say which show it belongs to."""
    name = replace_shortcodes(item.get("Name", ""))
    if item.get("Type") == "Season" and item.get("SeriesName"):
        return f"{replace_shortcodes(item['SeriesName'])} – {name}"
    return name


def describe_count(items: list) -> str:
    """"3 movies", "1 show and 2 seasons", "2 movies, 1 show and 1 season"."""
    parts = []
    for item_type, (one, many) in _NOUNS.items():
        count = sum(1 for i in items if i.get("Type") == item_type)
        if count:
            parts.append(f"{count} {one if count == 1 else many}")
    other = sum(1 for i in items if i.get("Type") not in _NOUNS)
    if other:
        parts.append(f"{other} item{'s' if other != 1 else ''}")
    if len(parts) <= 1:
        return parts[0] if parts else "0 items"
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def format_bytes(size: int) -> str:
    """1536 -> "1.5 KB", 25_000_000_000 -> "23.3 GB" (1024-based)."""
    value = float(size)
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            return f"{int(value)} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"  # unreachable, keeps type checkers happy


def _size_line(summary) -> str:
    if summary is None:
        return "File count and size couldn't be determined."
    files = summary["files"]
    if not files:
        return "No media files found on the server for this."
    size = format_bytes(summary["bytes"])
    line = f"{files} file{'s' if files != 1 else ''}, "
    if summary["unknown_sizes"]:
        return line + f"at least {size} (size unknown for {summary['unknown_sizes']})."
    return line + f"{size} total."


def build_message(items: list, summary) -> str:
    what = f"'{item_name(items[0])}'" if len(items) == 1 else describe_count(items)
    return (
        f"Permanently delete {what} from the server?[CR]"
        f"{_size_line(summary)}[CR]"
        "This cannot be undone."
    )


def result_message(deleted: list, failed: list) -> str:
    """"Deleted 2 movies" / "Deleted 1 show, 1 failed: Alien"."""
    message = f"Deleted {describe_count(deleted)}"
    if failed:
        message += f", {len(failed)} failed: {', '.join(item_name(i) for i in failed)}"
    return message


def confirm_delete(client, items: list) -> bool:
    """Look up the deletion's file count/size and ask for confirmation.
    A failed lookup still lets the user confirm, just without the numbers."""
    try:
        summary = library.get_media_summary(client, items)
    except Exception as exc:  # noqa: BLE001 - summary is informational, never block the dialog
        xbmc.log(f"{LOG_PREFIX} Delete: size lookup failed: {exc}", xbmc.LOGWARNING)
        summary = None
    return bool(xbmcgui.Dialog().yesno(
        "Confirm Delete", build_message(items, summary), nolabel="Cancel", yeslabel="Delete",
    ))
