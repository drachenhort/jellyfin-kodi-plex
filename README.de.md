# jellyfin-kodi-plex

*[English version](README.md)*

Ein Kodi-Programm-Addon (`script.jellyfin.plex`), das eine Verbindung zu einem Jellyfin-Medienserver herstellt und
eine benutzerdefinierte, Hub-basierte Oberfläche im Stil der Plex Web/App-Erfahrung bietet — anstelle von
Kodis Standard-Skin-Listenansichten.

Die Architektur orientiert sich am Open-Source-Addon [Plex for Kodi](https://github.com/plexinc/plex-for-kodi):
ein Kodi-*Skript*-Addon (kein `plugin.video.*`), das eigene `WindowXML`/`WindowXMLDialog`-Fenster öffnet,
um die Oberfläche vollständig selbst zu steuern, unabhängig vom aktiven Kodi-Skin.

## Status

Meilenstein 1 (in Arbeit): Login (LAN-Autoerkennung, Quick Connect mit Passwort-Fallback) → Startbildschirm mit
den Hub-Zeilen „Weiterschauen" / „Als Nächstes" / „Kürzlich hinzugefügt" → Bibliotheks-Posterwand-Browsing, inklusive
Drilldown durch die TV- (Serie → Staffel → Episode) und Musik-Hierarchien (Interpret → Album → Titel),
sowie ein Suchbildschirm → Detailseite eines Titels → Wiedergabe mit an den Server zurückgemeldetem Fortschritt und
einem benutzerdefinierten Plex-artigen Sucher-/OSD-Dialog anstelle von Kodis eingebauten Videosteuerelementen.
Multi-Server-Unterstützung ist eine Folgearbeit.

Der TV-/Musik-Drilldown funktioniert, indem die direkten Kindelemente jedes Objekts nicht-rekursiv abgerufen werden
(`lib/windows/browse.py` wird auf jeder Ebene wiederverwendet: die Top-Level-Elemente einer Bibliothek, die Staffeln
einer Serie, die Episoden einer Staffel, die Alben eines Interpreten, die Titel eines Albums) und anhand des
Typs des angeklickten Elements verzweigt (`lib/main.py`s `CONTAINER_TYPES`), um zu entscheiden, ob tiefer
navigiert oder der Detail-/Wiedergabebildschirm geöffnet wird. Die Gruppierung nach Musik-Interpret setzt voraus,
dass die Bibliothek mit einem Ordner pro Interpret organisiert ist — Jellyfins virtuelle,
ordnerübergreifende Interpreten-Aggregation (`/Artists`) wird nicht verwendet.

Der Login-Bildschirm erkennt Jellyfin-Server im lokalen Netzwerk automatisch (`lib/jellyfin/discovery.py`)
über das von Emby/MediaBrowser übernommene UDP-Broadcast-Protokoll — gefundene Server werden als Auswahlliste
angeboten, die das Server-URL-Feld ausfüllt; die manuelle Eingabe bleibt weiterhin als Fallback verfügbar.

Das benutzerdefinierte OSD funktioniert, indem ausgenutzt wird, dass Kodi keine API besitzt, um sein eigenes
Standard-Video-OSD beim Drücken einer Fernbedienungs-/Tastaturtaste zu unterdrücken: `lib/player.py` fragt in
einem Hintergrund-Thread `Window.IsActive(videoosd)` ab und zeigt in dem Moment, in dem das OSD erscheint,
den Dialog aus `lib/windows/seekdialog.py` darüber an — derselbe Trick, den das echte Plex-for-Kodi-Addon verwendet.

## Entwicklung

```bash
pip install -r requirements-dev.txt   # pytest
pytest
```

`lib/jellyfin/*` ist ein reiner Python-Client für die Jellyfin-API ohne `xbmc*`-Importe, daher lässt er sich
direkt mit pytest testen. `lib/windows/*` und `lib/player.py` sind die einzigen Module, die `xbmcgui`/`xbmc`
verwenden, und benötigen eine echte Kodi-Umgebung (oder die Stubs in `tests/conftest.py`), um zu laufen.

Um es in Kodi auszuprobieren: dieses Verzeichnis nach `~/.kodi/addons/script.jellyfin.plex/` kopieren oder
verlinken und über das Programme-Menü starten.
