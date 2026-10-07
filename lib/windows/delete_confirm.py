"""Shared "are you sure?" step for every movie-delete entry point (Detail's
Delete button, the Movies wall context menu, the Clean Up screen): looks up
how many files and bytes the deletion covers and shows that summary in the
confirmation dialog.

confirm_delete() does a network lookup, so call it off the GUI thread."""

import xbmc
import xbmcgui

from lib.jellyfin import library
from lib.windows.kodigui import LOG_PREFIX

_UNITS = ("bytes", "KB", "MB", "GB", "TB")


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


def build_message(movies: list, summary) -> str:
    if len(movies) == 1:
        what = f"'{movies[0].get('Name', '')}'"
    else:
        what = f"{len(movies)} movies"
    return (
        f"Permanently delete {what} from the server?[CR]"
        f"{_size_line(summary)}[CR]"
        "This cannot be undone."
    )


def confirm_delete(client, movies: list) -> bool:
    """Look up the deletion's file count/size and ask for confirmation.
    A failed lookup still lets the user confirm, just without the numbers."""
    try:
        summary = library.get_media_summary(client, [m["Id"] for m in movies])
    except Exception as exc:  # noqa: BLE001 - summary is informational, never block the dialog
        xbmc.log(f"{LOG_PREFIX} Delete: size lookup failed: {exc}", xbmc.LOGWARNING)
        summary = None
    return bool(xbmcgui.Dialog().yesno(
        "Delete Movies", build_message(movies, summary), nolabel="Cancel", yeslabel="Delete",
    ))
