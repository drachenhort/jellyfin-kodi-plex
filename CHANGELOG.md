# Changelog

All notable changes to this addon, one entry per released version (newest first).

## 0.3.54 - 2026-07-30
- Extend the poster-zoom clipping fix (0.3.52/0.3.53) to the Search screen's Movies/TV Shows/Music result rows: switched from the container-level Focus/UnFocus animation to the same bigger-focusedlayout-box technique as the library grid, with matching margins on all four edges and a mirrored top/bottom selection marker (every item in these single-row lists is effectively a top/bottom edge case). Zoom is 110% here (vs 112% in the grid) since the gap above these rows is a few px tighter

## 0.3.53 - 2026-07-30
- Same fix as 0.3.52, applied to the library grid's left/right edges: the leftmost and rightmost columns' zoom overflow (13px each side) was getting clipped by the panel's own horizontal viewport bounds, cutting off part of the title (e.g. a leading digit) or the selection border. Grew the panel's width by a matching 13px margin on both sides and shifted all grid content right to compensate

## 0.3.52 - 2026-07-30
- Fix two clipping issues in the library grid's poster zoom (0.3.51): the selection marker and, on further testing, the ratings/title text could get cut off for posters in the grid's top or bottom row, since the enlarged poster overflows past the panel's own viewport there with no row above/below to bleed into. Grew the grid's viewport by a 20px margin on both edges (shifting all grid content down to compensate) so the overflow always has room, and added a second selection marker below the poster (mirrored via `flipy`) so it's visible even when the top one would be clipped

## 0.3.51 - 2026-07-30
- Fix the library browsing poster grid's zoom-on-focus (added in 0.3.50): it was scaling the entire grid, not just the selected poster, because a Panel control's Focus/UnFocus animation applies to the whole container rather than the individual focused cell (unlike the single-row Home/Search lists, where that pattern works correctly). Replaced with a bigger, centered `focusedlayout` box, which grows only the one focused poster

## 0.3.50 - 2026-07-30
- Poster grids (library browsing, search results) now zoom the focused item to 112% on selection, matching the Home screen's hub rows - makes the selected poster clearly stand out and read at a larger, sharper size, addressing posters looking low-res when small and unfocused

## 0.3.49 - 2026-07-29
- Internal cleanup of the Recently Added TV code (no user-facing change): the "hide watched" check is now a shared `library.is_played()` helper instead of three copies of the same inline lookup, and the raw-episode over-fetch heuristic behind season-block grouping is derived from an explained worst-case bound instead of an unexplained x10 multiplier, reducing the default request size

## 0.3.48 - 2026-07-29
- Credit [Intro Skipper](https://intro-skipper.org) in the README: the "Skip Intro" support added in 0.3.42 relies entirely on that Jellyfin server plugin's intro-segment detection

## 0.3.47 - 2026-07-29
- Fix "Hide watched Recently Added TV" not working correctly against the new season-block tiles: it now filters watched episodes before grouping into a block instead of after, so a fully-watched batch is hidden entirely and a partially-watched block's episode count only reflects its still-unwatched episodes

## 0.3.46 - 2026-07-29
- Fix Recently Added TV silently dropping other shows' episodes after a large batch-added season: it only fetched "item limit" raw episodes before grouping, so one season alone reaching that many episodes crowded out every other show even though it collapses to a single tile. Now fetches a wider raw batch and caps the result at the item limit only after grouping.

## 0.3.45 - 2026-07-29
- The Recently Added TV season-block threshold (added in 0.3.44) is now a Home setting ("Group new episodes into a season block after", default 3, range 2-20) instead of a fixed value

## 0.3.44 - 2026-07-29
- A season that gets 3 or more episodes added at once now shows as a single "Show - Season N" block tile in Recently Added TV, instead of flooding the row with each individual episode; opening it goes straight to that season's episode list. A season with only 1-2 new episodes still lists them individually.

## 0.3.43 - 2026-07-29
- Fix a newly-scanned show/season sometimes not appearing in its library listing until an unrelated watched/unwatched change happened: returning to Home now drops the stale browse-level cache instead of only clearing it on a watched-state change
- Fix Recently Added TV episodes sometimes listing out of order (e.g. S9E2, then E9, then E7, before finally E1) when a whole season was scanned in at once: episodes are now grouped by series (most-recently-added series first) and ordered ascending by season/episode within each series

## 0.3.42 - 2026-07-27
- Add "Skip Intro" support: during an episode's opening credits, shows a Skip Intro overlay using intro segments detected by the server's optional Intro Skipper plugin (no effect on a server without that plugin); can be disabled via the new "Enable skip intro" Playback setting

## 0.3.41 - 2026-07-26
- Fix the preferred audio language setting sometimes being ignored: a Play click landing right after item metadata loaded but before track info finished loading could start playback before the language preference was applied, falling back to the file's own default audio track

## 0.3.40 - 2026-07-26
- The "Play Next Episode" overlay shown during end credits no longer auto-dismisses after 15s; it now stays up for the rest of the episode's playback so a slower viewer still has time to use it

## 0.3.39 - 2026-07-25
- Launching the addon while a previous instance is stuck no longer just shows "Already running" forever: it now asks the stuck instance to stop and, if it doesn't within 5s, reclaims the slot and starts fresh anyway

## 0.3.38 - 2026-07-25
- Stop a wedged Kodi player engine (e.g. a stuck network reconnect) from freezing the whole addon: Player.stop() now runs with a bounded timeout instead of blocking the wait loop forever, and playback start/stop/error events are now logged for diagnosis

## 0.3.37 - 2026-07-23
- Only fall back to an explicit resume seekTime() when StartOffset actually failed, instead of on every resume

## 0.3.36 - 2026-07-23
- Fix resume playback being killed within ~0.1s by a false-positive "Kodi home became active" check, and add a resume seekTime() fallback

## 0.3.35 - 2026-07-22
- Add a Playback setting for the "Play Next Episode" overlay's lead time (default 150s)

## 0.3.34 - 2026-07-22
- Fix the "Play Next Episode" overlay's buttons being unclickable on a real device (WindowXML -> WindowXMLDialog, shown from the main playback thread)

## 0.3.33 - 2026-07-22
- Add a non-intrusive "Play Next Episode" overlay in an episode's closing ~2.5 minutes, to skip the outro

## 0.3.32 - 2026-07-22
- Offer to auto-play the next episode in the season, with a 30s countdown, after an episode finishes

## 0.3.31 - 2026-07-22
- Fall back to another saved server when the active one is unreachable

## 0.3.30 - 2026-07-21
- Show remaining time and add a "Play from Start" option to Detail

## 0.3.29 - 2026-07-21
- Fix resume position resetting to 0 when stopping playback

## 0.3.28 - 2026-07-20
- Add Preferred audio/subtitle language settings under Playback

## 0.3.27 - 2026-07-20
- Fix Audio/Subtitle buttons never becoming visible on a real device

## 0.3.26 - 2026-07-20
- Add audio/subtitle track pickers, content rating, and h/min runtime to Detail

## 0.3.25 - 2026-07-20
- Cache get_similar() per (client, item_id) for the rest of the session

## 0.3.24 - 2026-07-20
- Add a "More Like This" row to item detail pages

## 0.3.23 - 2026-07-20
- Cache Browse's fully-loaded children for the rest of the session

## 0.3.22 - 2026-07-20
- Cache get_views() per client for 60s

## 0.3.21 - 2026-07-20
- Revert v0.3.20's window-limit catch: it caused an infinite retry loop

## 0.3.20 - 2026-07-20
- Absorb Kodi's "maximum number of windows reached" during shutdown

## 0.3.19 - 2026-07-20
- Fix a crash race in the v0.3.18 shutdown fix: recheck abort after the confirm dialog

## 0.3.18 - 2026-07-20
- Fix the actual shutdown hang: doModal() never returned on Kodi abort

## 0.3.17 - 2026-07-20
- Fix shutdown hang: skip the quit-confirmation dialog when Kodi is aborting

## 0.3.16 - 2026-07-20
- Add a Recently Added item limit setting for the Home hub rows

## 0.3.15 - 2026-07-20
- Add setting to hide watched items from Recently Added Music on Home

## 0.3.14 - 2026-07-20
- Add settings to hide watched items from Recently Added Movies/TV on Home

## 0.3.13 - 2026-07-19
- Add a singleton guard so a second launch can't leave "quit" looking broken

## 0.3.12 - 2026-07-19
- Group Search results into Movies/TV Shows/Music rows

## 0.3.11 - 2026-07-19
- Add Movies/TV Shows/Music filter toggles to Search

## 0.3.10 - 2026-07-19
- Show a season's own synopsis before an episode is picked, fix a broken skin condition

## 0.3.8 - 2026-07-19
- Add search-as-you-type to the Search screen

## 0.3.7 - 2026-07-19
- Move the search hint to the top-left title and drop the redundant "Search" heading

## 0.3.6 - 2026-07-19
- Give the search query field a visible entry box

## 0.3.5 - 2026-07-19
- Rename the Search screen's Back button to "Home"

## 0.3.4 - 2026-07-19
- Add an explicit Back button to Search and fix the input/hint text collision

## 0.3.3 - 2026-07-19
- Show a series' own synopsis before a season is picked

## 0.3.2 - 2026-07-19
- Expand the movie detail synopsis textbox to show the full plot

## 0.3.1 - 2026-07-19
- Add a Settings button to the Home screen's main hub menu

## 0.3.0 - 2026-07-19
- Milestone 2: expose configurable options via Kodi's addon Settings

## 0.2.68 - 2026-07-19
- Add Jellyfin fish logo to the Home screen header

## 0.2.67 - 2026-07-19
- Always show library names on Home, not just when focused

## 0.2.66 - 2026-07-19
- Fix selectItem() being silently undone by later pages in Browse

## 0.2.65 - 2026-07-19
- Restore selection when Back returns to Browse or Home

## 0.2.64 - 2026-07-19
- Use show posters instead of logos in Recently Added TV

## 0.2.63 - 2026-07-19
- Cache track IDs to avoid redundant computation

## 0.2.62 - 2026-07-18
- Show the item/step count in the loading label from the very first frame

## 0.2.61 - 2026-07-18
- Show a 0-95% simulated progress percentage on the loading overlay

## 0.2.60 - 2026-07-18
- Move the loading indicator to a centered transient overlay

## 0.2.59 - 2026-07-18
- Show a running item count on Browse while paging loads

## 0.2.58 - 2026-07-18
- Wire iter_items_paged into BrowseWindow's loading for all libraries

## 0.2.57 - 2026-07-18
- Fix Home's loading label overlapping the Libraries heading

## 0.2.56 - 2026-07-18
- Show a loading indicator on Home and Browse while data is fetching

## 0.2.55 - 2026-07-18
- Add a paginated full-library item iterator for large collections

## 0.2.54 - 2026-07-18
- Fix install instructions: addon lists under Video add-ons, not Program

## 0.2.53 - 2026-07-18
- Fix hide_playlists setting type for Kodi's new settings schema

## 0.2.52 - 2026-07-18
- Replace the music library placeholder icon

## 0.2.51 - 2026-07-18
- Add a Playlists show/hide toggle to the Home screen

## 0.2.50 - 2026-07-18
- Add a Mark as Watched/Unwatched toggle to the detail screen

## 0.2.49 - 2026-07-17
- Show an episode's rating after its duration in the episode list

## 0.2.48 - 2026-07-17
- List a season's episodes ls -l style instead of the poster grid

## 0.2.47 - 2026-07-17
- Show a synopsis pane for the focused item in Browse

## 0.2.46 - 2026-07-17
- Add an unwatched-episode-count badge for TV shows

## 0.2.45 - 2026-07-17
- Add a watched-status badge for movies and episodes

## 0.2.44 - 2026-07-17
- Fix GUI freeze/timeout when browsing a large real library, add music placeholder art

## 0.2.43 - 2026-07-17
- Add music library support: audio playback, Recently Added Music, album queue/shuffle

## 0.2.42 - 2026-07-17
- Report the addon's real version to Jellyfin instead of a hardcoded 0.1.0

## 0.2.41 - 2026-07-17
- Add automated test coverage for lib/windows/* and lib/player.py

## 0.2.40 - 2026-07-17
- Handle server/network failures in Home, Browse, Detail, and Search

## 0.2.39 - 2026-07-17
- Re-add Kodi-home exit detection with logging, add a startup timeout

## 0.2.38 - 2026-07-17
- Fix play_item() returning immediately on a slow-starting stream

## 0.2.37 - 2026-07-17
- Revert the Window.IsActive(home) exit-detection - likely backfiring

## 0.2.36 - 2026-07-17
- Stop playback when the script exits instead of leaving it running

## 0.2.35 - 2026-07-17
- Remove the custom OSD, use Kodi's native video controls instead

## 0.2.34 - 2026-07-17
- Fix play/pause button using two controls sharing id=100

## 0.2.33 - 2026-07-17
- Revert the keep-window-open OSD refactor - it broke all input

## 0.2.32 - 2026-07-17
- Show a language list for audio/subtitle tracks instead of blind cycling

## 0.2.31 - 2026-07-17
- Add audio/subtitle track buttons to the OSD, make Back stop playback

## 0.2.30 - 2026-07-17
- Actually close Kodi's native video OSD instead of assuming it's moot

## 0.2.29 - 2026-07-17
- Redesign the seek/OSD dialog to look like Plex's

## 0.2.28 - 2026-07-17
- Split episode number and title onto separate lines on Recently Added TV

## 0.2.27 - 2026-07-17
- Show series name and episode title on Recently Added TV

## 0.2.26 - 2026-07-17
- Hide empty Home rows instead of letting focus silently cascade past them

## 0.2.25 - 2026-07-17
- Generalize the missing-art placeholder to every screen, fix its aspect ratio

## 0.2.24 - 2026-07-17
- Show a placeholder image for libraries with no folder art

## 0.2.23 - 2026-07-17
- Always show series name and episode title on Next Up, not just when selected

## 0.2.22 - 2026-07-17
- Turquoise background behind text on selected items

## 0.2.21 - 2026-07-17
- Overlay ratings on posters when browsing libraries too

## 0.2.20 - 2026-07-17
- Overlay ratings on every Recently Added Movies poster, not just the focused one

## 0.2.19 - 2026-07-17
- Show TMDb and Rotten Tomatoes ratings on Recently Added Movies

## 0.2.18 - 2026-07-17
- Add addon icon

## 0.2.17 - 2026-07-17
- Apply the Next Up poster treatment to Continue Watching

## 0.2.16 - 2026-07-17
- Show season/series posters on Next Up instead of episode screengrabs

## 0.2.15 - 2026-07-17
- Show series name on Next Up cards

## 0.2.14 - 2026-07-17
- Add multi-server support

## 0.2.13 - 2026-07-17
- Give Recently Added TV the same size as Recently Added Movies

## 0.2.12 - 2026-07-17
- Fix poster/thumb aspect ratios across the UI

## 0.2.11 - 2026-07-17
- Split Recently Added into separate Movies and TV rows

## 0.2.10 - 2026-07-17
- Fix Home row navigation broken by the grouplist restructure

## 0.2.9 - 2026-07-17
- Make Home rows scroll instead of squeezing to fit the screen

## 0.2.8 - 2026-07-17
- Double Recently Added thumbnails, add zoom-on-focus to Continue Watching/Recently Added

## 0.2.7 - 2026-07-16
- Make poster/thumb artwork bigger within the focus highlight

## 0.2.6 - 2026-07-16
- Move Recently Added above Next Up on Home

## 0.2.5 - 2026-07-16
- Use orange highlight box for Home's Search button focus state

## 0.2.4 - 2026-07-16
- Add pointer arrow to focused item

## 0.2.3 - 2026-07-16
- Fix cropped focus highlight, make it bigger

## 0.2.2 - 2026-07-16
- Add orange focus highlight to poster grids

## 0.2.1 - 2026-07-16
- Fix login screen remote-control navigation

## 0.2.0 - 2026-07-16
- Add LAN autodiscovery to login

## 0.1.0 - 2026-07-16
- Initial M1 vertical slice: login, home hubs, browse, detail, playback with custom OSD
