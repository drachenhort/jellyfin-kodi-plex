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
den Hub-Zeilen „Weiterschauen" / „Als Nächstes" / „Kürzlich hinzugefügte Filme" / „Kürzlich hinzugefügte Serien" /
„Kürzlich hinzugefügte Musik" → Bibliotheks-Posterwand-Browsing, inklusive Drilldown durch die TV-
(Serie → Staffel → Episode) und Musik-Hierarchien (Interpret → Album → Titel), sowie ein Suchbildschirm →
Detailseite eines Titels → Wiedergabe (Video und Audio, mit Kodis eigenem nativen OSD/Steuerelementen) mit
an den Server zurückgemeldetem Fortschritt sowie einem Server-Bildschirm zum Speichern von Logins für
mehrere Jellyfin-Server und zum Wechseln zwischen ihnen. Die Detailseite eines Albums bietet zusätzlich
„Alle abspielen"/„Zufällig abspielen"-Schaltflächen, um dessen Titel nacheinander abzuspielen — zum
nächsten Titel wird nur gewechselt, wenn der aktuelle regulär zu Ende gespielt wurde, nicht bei
vorzeitigem Stopp.

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

Die Multi-Server-Unterstützung (`lib/servers.py`) speichert gesicherte Logins als Liste von
`{name, server_url, access_token, user_id}`-Dicts, serialisiert in eine einzelne versteckte
Addon-Einstellung statt einer Einstellung pro Feld — `lib/main.py` übernimmt das Lesen/Schreiben
dieser Einstellung und gleicht ein erneutes Login mit einer bereits gespeicherten Server-URL ab,
um den vorhandenen Eintrag zu aktualisieren, statt ihn zu duplizieren. Der Server-Button auf dem
Startbildschirm (`lib/windows/servers.py`) öffnet eine Auswahl, um den aktiven Server zu wechseln,
über denselben Login-Ablauf einen weiteren hinzuzufügen oder einen gespeicherten zu entfernen (der
aktuell aktive Server kann nicht entfernt werden — dazu muss man zuerst zu einem anderen wechseln).
Eine bestehende Einzelserver-Installation wird beim ersten Start nach dem Update automatisch in
diese Liste übernommen, damit sie nicht abgemeldet wird.

## Entwicklung

```bash
pip install -r requirements-dev.txt   # pytest
pytest
```

`lib/jellyfin/*` ist ein reiner Python-Client für die Jellyfin-API ohne `xbmc*`-Importe, daher lässt er sich
direkt mit pytest testen. `lib/windows/*` und `lib/player.py` sind die einzigen Module, die `xbmcgui`/`xbmc`
verwenden; `tests/kodi_stubs/` stellt minimale Ersatzmodule dafür bereit (von `tests/conftest.py` in
`sys.modules` registriert), sodass auch diese Schicht mit reinem pytest läuft — ohne echte
Kodi-Umgebung.

Um es in Kodi auszuprobieren: dieses Verzeichnis nach `~/.kodi/addons/script.jellyfin.plex/` kopieren oder
verlinken und über das Programme-Menü starten.
