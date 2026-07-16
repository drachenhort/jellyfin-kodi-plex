"""Item detail / preplay window: fanart background, poster, metadata, cast,
and a Play (or Resume) button.

self.result on close: {"action": "play", "item_id": ..., "resume_ticks": N}
or None (back).
"""

from lib.jellyfin import images, library
from lib.windows.kodigui import ControlledWindow

CTRL_BACKDROP = 400
CTRL_POSTER = 401
CTRL_TITLE = 402
CTRL_META = 403
CTRL_OVERVIEW = 404
CTRL_CAST = 405
CTRL_PLAY_BUTTON = 406

RESUME_THRESHOLD_TICKS = 10 * 10_000_000  # ignore resume points under 10s


def _meta_line(item):
    parts = []
    if item.get("ProductionYear"):
        parts.append(str(item["ProductionYear"]))
    if item.get("RunTimeTicks"):
        minutes = int(item["RunTimeTicks"] / 10_000_000 / 60)
        parts.append(f"{minutes} min")
    if item.get("CommunityRating"):
        parts.append(f"{item['CommunityRating']:.1f}★")
    if item.get("Genres"):
        parts.append(", ".join(item["Genres"]))
    return "  •  ".join(parts)


def _cast_line(item):
    people = [p["Name"] for p in (item.get("People") or []) if p.get("Type") == "Actor"]
    return ", ".join(people[:6])


class DetailWindow(ControlledWindow):
    xmlFile = "script-jellyfin-detail.xml"

    def setup(self, client=None, item_id=None, **kwargs):
        super().setup(**kwargs)
        self.client = client
        self.item_id = item_id
        self.item = None

    def onInit(self):
        self.item = library.get_item(self.client, self.item_id)

        backdrop = images.backdrop_image_url(self.client, self.item)
        if backdrop:
            self.getControl(CTRL_BACKDROP).setImage(backdrop)
        poster = images.primary_image_url(self.client, self.item)
        if poster:
            self.getControl(CTRL_POSTER).setImage(poster)

        self.getControl(CTRL_TITLE).setLabel(self.item.get("Name", ""))
        self.getControl(CTRL_META).setLabel(_meta_line(self.item))
        self.getControl(CTRL_OVERVIEW).setText(self.item.get("Overview", ""))
        self.getControl(CTRL_CAST).setLabel(_cast_line(self.item))

        resume_ticks = (self.item.get("UserData") or {}).get("PlaybackPositionTicks", 0)
        if resume_ticks and resume_ticks > RESUME_THRESHOLD_TICKS:
            self.getControl(CTRL_PLAY_BUTTON).setLabel("Resume")
        else:
            self.getControl(CTRL_PLAY_BUTTON).setLabel("Play")

        self.setFocusId(CTRL_PLAY_BUTTON)

    def handle_click(self, control_id):
        if control_id != CTRL_PLAY_BUTTON:
            return
        resume_ticks = (self.item.get("UserData") or {}).get("PlaybackPositionTicks", 0)
        if resume_ticks <= RESUME_THRESHOLD_TICKS:
            resume_ticks = 0
        self.result = {
            "action": "play",
            "item_id": self.item_id,
            "resume_ticks": resume_ticks,
            "title": self.item.get("Name", ""),
        }
        self.close()
