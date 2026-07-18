# Kodi Repository for Auto-Updates

## Goal

Let Kodi auto-update `script.jellyfin.plex` the way it does for any addon installed from a
repository, instead of requiring manual zip reinstalls after every release.

## Components

### 1. `repository.jellyfinplex/` addon

A second, minimal addon at the repo root, alongside `script.jellyfin.plex`'s existing files:

```
repository.jellyfinplex/
  addon.xml
  icon.png
```

Its `addon.xml` declares an `xbmc.addon.repository` extension point:

```xml
<extension point="xbmc.addon.repository" name="Jellyfin (Plex-style) Repository">
  <dir>
    <info compressed="false">https://drachenhort.github.io/jellyfin-kodi-plex/addons.xml</info>
    <checksum>https://drachenhort.github.io/jellyfin-kodi-plex/addons.xml.md5</checksum>
    <datadir zip="true">https://drachenhort.github.io/jellyfin-kodi-plex/</datadir>
  </dir>
</extension>
```

This is the one-time-install addon: users install it once (via a zip linked from the README, or a
GitHub Release), after which Kodi checks `addons.xml` on its own update schedule and offers
upgrades for `script.jellyfin.plex` automatically — and for `repository.jellyfinplex` itself, if its
own version is ever bumped.

Versioned independently from `script.jellyfin.plex`, starting at `1.0.0`. It changes rarely (only if
the Pages URL or repo structure itself changes).

### 2. `docs/` folder on `master`, served by GitHub Pages

GitHub Pages is configured to serve from `master` branch, `/docs` folder. Contents are **generated,
not hand-edited**:

```
docs/
  addons.xml            # <addons> root listing both addon.xml files below, concatenated
  addons.xml.md5        # md5 checksum of addons.xml, for Kodi's integrity check
  script.jellyfin.plex/
    script.jellyfin.plex-<version>.zip
    icon.png
  repository.jellyfinplex/
    repository.jellyfinplex-<version>.zip
    icon.png
```

`docs/superpowers/specs/` (this spec and future ones) also lives under `docs/`, per this project's
default spec location — it does not interfere with `addons.xml` generation, which only touches the
two addon-id subfolders and the two root files.

### 3. `tools/build_repo.py`

A pure-Python build script (no `xbmc*` imports, consistent with this codebase's layering
conventions) that, given the repo root:

1. For each of `script.jellyfin.plex/` and `repository.jellyfinplex/`: read `<version>` out of
   `addon.xml`, and if `docs/<id>/<id>-<version>.zip` doesn't already exist, zip up that addon's
   source files (respecting `.gitignore`-style excludes — no `__pycache__`, `.pyc`, tests, `.git`)
   into it, and copy/update `docs/<id>/icon.png`.
2. Concatenate both addons' `addon.xml` contents into a single `<addons>...</addons>` document at
   `docs/addons.xml`.
3. Compute and write the md5 of `docs/addons.xml` to `docs/addons.xml.md5`.

Idempotent: re-running when nothing changed is a no-op (no new zip, `addons.xml`/`.md5` rewritten
but with identical content).

### 4. `.github/workflows/build-repo.yml`

GitHub Actions workflow:

- **Trigger:** `push` to `master` where `script.jellyfin.plex`'s or `repository.jellyfinplex`'s
  `addon.xml` changed (path filter), plus `workflow_dispatch` for manual re-runs.
- **Steps:** checkout, run `python tools/build_repo.py`, commit any resulting changes under `docs/`
  back to `master` as a bot commit (skip the commit step if `git diff` is empty), push.
- A commit made by the bot itself (touching only `docs/`, not `addon.xml`) does not retrigger the
  workflow, since the path filter only matches `addon.xml` changes.

This slots into the existing release workflow documented in `CLAUDE.md` (bump version in
`addon.xml`, commit, push) with no new manual step — the version bump commit itself is what fires
the build.

## Data Flow

1. Developer bumps `version` in `script.jellyfin.plex/addon.xml`, commits, pushes to `master` (per
   existing `CLAUDE.md` release workflow).
2. GitHub Actions runs `tools/build_repo.py`, producing a new zip under `docs/script.jellyfin.plex/`
   and an updated `docs/addons.xml` + `.md5`.
3. The workflow commits and pushes that `docs/` change to `master`.
4. GitHub Pages republishes `docs/` (typically within a minute or two).
5. Kodi installs, on its own periodic update check, see the new `addons.xml` version, download the
   new zip from `datadir`, and upgrade the installed addon.

## Error Handling

- If `tools/build_repo.py` fails (e.g. malformed `addon.xml`), the workflow fails visibly in the
  Actions tab and `docs/` is left unchanged — no partial/corrupt `addons.xml` is ever published,
  since the script only overwrites `docs/addons.xml` after successfully building both addons' zips.
- If GitHub Pages isn't enabled yet, the workflow still succeeds (it only touches `docs/` in git);
  Pages is a separate one-time repo-settings step, called out below.

## Testing

- `tools/build_repo.py` gets a `tests/test_build_repo.py` covering: version-based zip naming,
  skip-if-exists idempotency, `addons.xml` concatenation of two addons, and md5 checksum
  correctness — run under the existing `pytest` setup, no `xbmc*` dependency.
- End-to-end verification (Kodi actually offers/accepts the update) happens once Pages is live and
  a version bump has gone through the pipeline once — this is a real-Kodi-box check per this
  project's existing verification conventions, not something pytest can cover.

## One-time manual setup (outside this change)

- Enable GitHub Pages on this repo: Settings → Pages → source = `master` / `/docs`. Confirmed with
  the user before being flipped, since it makes `docs/` publicly served (repo is already public, so
  this doesn't change visibility, just adds a served URL).
- Build and publish an initial `repository.jellyfinplex` zip somewhere reachable (e.g. a GitHub
  Release or linked from the README) so users have something to install the first time.

## Out of Scope (YAGNI)

- No support for addons beyond these two.
- No dedicated `gh-pages` branch — `docs/` on `master` was the chosen source.
- No repo addon signing / password-protected repository.
- No multi-arch or multi-Kodi-version addon variants.
