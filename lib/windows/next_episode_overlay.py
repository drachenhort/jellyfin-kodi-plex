"""Non-modal, corner-positioned "Play Next Episode" overlay, shown during
the closing ~2-3 minutes of an Episode's playback so the last minute or two
of end credits/outro can be skipped straight into the next episode.

Deliberately much simpler than a full seek/scrub UI - just two buttons,
auto-dismisses on its own without forcing any action - because an earlier,
more ambitious custom overlay shown *during* active video playback left
Kodi's own video OSD unresponsive to remote input on a real device and had
to be removed (see lib/player.py's module docstring). This one is shown via
show() (non-blocking, non-modal), not doModal() - lib/player.py's playback
wait loop polls `.result` itself rather than blocking on this window the
way lib/main.py's window stack blocks on every other screen.

Built on ControlledDialog (WindowXMLDialog), not ControlledWindow
(WindowXML): real Kodi only routes remote input to a plain WindowXML shown
non-modally if it's the "current" window, and the native Fullscreen Video
window keeps that status for itself during playback - a WindowXML overlay
would render on top but its buttons would be unreachable. WindowXMLDialog
is Kodi's own mechanism for a screen that's supposed to receive input while
layered above whatever's currently active, which is exactly this case
(confirmed on a real device: a first WindowXML-based attempt at this
overlay rendered fine but never received a single click).

self.result once closed_event is set is one of:
  {"action": "play"}  — "Play Next Episode" was clicked
  None                — "Dismiss" was clicked, or the auto-dismiss timer
                         elapsed with no interaction
"""

import threading

from lib.jellyfin import images
from lib.windows.kodigui import ControlledDialog, placeholder_art

AUTO_DISMISS_SECONDS = 15

CTRL_THUMB = 600
CTRL_EPISODE_NAME = 601
CTRL_PLAY_NOW = 602
CTRL_DISMISS = 603


class NextEpisodeOverlay(ControlledDialog):
    xmlFile = "script-jellyfin-nextepisode-overlay.xml"

    def setup(self, client=None, next_item=None, auto_dismiss_seconds=AUTO_DISMISS_SECONDS, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.next_item = next_item or {}
        self.auto_dismiss_seconds = auto_dismiss_seconds

    @classmethod
    def show_overlay(cls, addon_path, **kwargs):
        """Non-blocking: shows the overlay and returns the window instance
        immediately, instead of WindowMixin.open()'s doModal()-blocking
        behaviour - lib/player.py's playback wait loop needs to keep
        ticking (progress reporting, abort checks) while this is up, not
        block on it. Caller polls `.closed_event`/`.result` and is
        responsible for calling `.close()` itself if it needs to tear this
        down early (e.g. playback ends before the user reacts)."""
        window = cls(cls.xmlFile, addon_path, cls.theme, cls.res)
        window.setup(**kwargs)
        window.show()
        threading.Thread(target=window._auto_dismiss, daemon=True).start()
        return window

    def onInit(self):
        self.getControl(CTRL_EPISODE_NAME).setLabel(self.next_item.get("Name", ""))
        thumb = images.primary_image_url(self.client, self.next_item) if self.client else None
        self.getControl(CTRL_THUMB).setImage(thumb or placeholder_art(self.next_item))

    def _auto_dismiss(self):
        # Non-intrusive by design: unlike NextEpisodeWindow's post-playback
        # countdown, timing out here does *not* trigger playback - it just
        # quietly goes away so it never forces an unwanted skip on someone
        # who simply didn't notice it.
        if self.closed_event.wait(self.auto_dismiss_seconds):
            return
        self.result = None
        self.close()

    def handle_click(self, control_id):
        if control_id == CTRL_PLAY_NOW:
            self.result = {"action": "play"}
            self.close()
        elif control_id == CTRL_DISMISS:
            self.result = None
            self.close()
