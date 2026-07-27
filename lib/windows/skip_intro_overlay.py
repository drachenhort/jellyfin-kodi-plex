"""Non-modal, corner-positioned "Skip Intro" overlay, shown while playback
position is within an Episode's Jellyfin Intro Skipper-detected intro
segment. Built the same way as
lib.windows.next_episode_overlay.NextEpisodeOverlay (see that module's
docstring for why a WindowXMLDialog shown via show()/non-modal is required
here rather than a plain WindowXML or a doModal() dialog) - one button,
no scrubbing.

self.result once closed_event is set is one of:
  {"action": "skip"}  — "Skip Intro" was clicked
  None                — dismissed, or playback moved past the segment/ended
                        before any interaction
"""

from lib.windows.kodigui import ControlledDialog

CTRL_SKIP = 601


class SkipIntroOverlay(ControlledDialog):
    xmlFile = "script-jellyfin-skipintro-overlay.xml"

    @classmethod
    def show_overlay(cls, addon_path, **kwargs):
        """Non-blocking, mirrors NextEpisodeOverlay.show_overlay() - the
        caller (lib/player.py's wait loop) polls `.closed_event`/`.result`
        and is responsible for calling `.close()` itself once the segment
        has been passed or playback ends."""
        window = cls(cls.xmlFile, addon_path, cls.theme, cls.res)
        window.setup(**kwargs)
        window.show()
        return window

    def handle_click(self, control_id):
        if control_id == CTRL_SKIP:
            self.result = {"action": "skip"}
            self.close()
