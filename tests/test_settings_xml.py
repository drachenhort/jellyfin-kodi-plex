"""Validates the new visible Configure-dialog settings are wired correctly.
XML structure only - this doesn't (and can't, without real Kodi) verify the
settings dialog actually renders as expected; see CLAUDE.md's Verification
section for the real-Kodi check this still needs.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_XML = REPO_ROOT / "resources" / "settings.xml"


def _get_setting(root, setting_id):
    return root.find(".//setting[@id='{}']".format(setting_id))


def test_active_server_info_is_visible_and_readonly():
    root = ET.parse(SETTINGS_XML).getroot()
    setting = _get_setting(root, "active_server_info")
    assert setting is not None
    assert setting.find("level").text == "0"

    constraints = setting.find("constraints")
    assert constraints is not None
    options = constraints.find("options")
    assert options is not None
    assert options.text == "readonly"


def test_manage_servers_action_runs_configure_script():
    root = ET.parse(SETTINGS_XML).getroot()
    setting = _get_setting(root, "manage_servers")
    assert setting is not None
    assert setting.attrib["type"] == "action"
    assert setting.find("level").text == "0"

    data = setting.find("control/data")
    assert data is not None
    assert data.text == "RunScript(script.jellyfin.plex,configure)"
