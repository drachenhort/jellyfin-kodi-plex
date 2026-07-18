import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_XML = REPO_ROOT / "repository.jellyfinplex" / "addon.xml"


def test_repository_addon_xml_is_well_formed():
    root = ET.parse(ADDON_XML).getroot()
    assert root.tag == "addon"
    assert root.attrib["id"] == "repository.jellyfinplex"
    assert root.attrib["version"] == "1.0.0"


def test_repository_addon_declares_repository_extension():
    root = ET.parse(ADDON_XML).getroot()
    ext = root.find("./extension[@point='xbmc.addon.repository']")
    assert ext is not None

    base_url = "https://drachenhort.github.io/jellyfin-kodi-plex/"
    info = ext.find("./dir/info")
    checksum = ext.find("./dir/checksum")
    datadir = ext.find("./dir/datadir")

    assert info.text == base_url + "addons.xml"
    assert checksum.text == base_url + "addons.xml.md5"
    assert datadir.text == base_url


def test_repository_addon_icon_exists():
    assert (REPO_ROOT / "repository.jellyfinplex" / "icon.png").is_file()
