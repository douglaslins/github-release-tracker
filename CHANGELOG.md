# Changelog

## [Unreleased]
- Download folder: in Settings, point the app at the folder where you keep your downloads. Each project then shows `Up to date 🟢 (latest)`, `Up to date 🟢 (Pre-release available)`, `Needs update 🟡` or `Not downloaded 🔴`.
- Right-click > **Change folder...** scans a different folder for one project only. The new **Rescan files** button re-reads the folders without using the network.
- SHA-256 check: a file counts as a release file when its SHA-256 matches, so renamed files are found. A file with the right name but a different hash shows `(hash mismatch)`. Turn it off in Settings. Hashes are remembered in `hash_cache.json`.
- Projects on GitLab (also self-hosted), Gitea and Forgejo can be added next to GitHub projects. Right-click > **Set access token for this host...** stores a token for private projects or for hosts that limit anonymous requests. A token is only sent to its own host.
- Several addresses can be pasted at once. Each one shows up in the list immediately as "Adding ..." and fills in when its lookup finishes. Adding, checking and scanning no longer wait for each other.
- Faster checks: up to 6 projects are checked at the same time, with at most 3 requests at once to one host. A host that did not answer is skipped for 30 seconds, and a host that asks you to slow down is not asked again in the same run.
- Only one copy of the app can run per data folder (`projects.lock`), because two copies would overwrite each other's changes.
- `tools/make_icons.py` has a new `folder` icon. `hash_cache.json` and `projects.lock` are listed in `.gitignore`.

## [1.1.1]
- Thin separator lines between columns, in the same colour as the row lines.
- Column headers are left-aligned and bold.
- The horizontal scrollbar only appears when the columns do not fit; the vertical one stays visible.
- Fix: making a column narrower no longer leaves an empty strip on the right; the last column takes the freed space.

## [1.1.0]
- Release-tag app icon (window, taskbar and the `.exe` file).
- Version number in the window title, and an About box (Settings > About) with a Copy version button.
- Small icons next to the toolbar buttons; the theme button is now a moon / sun icon with a tooltip.
- Thin separator lines between rows.
- Rename a project: hover a row and click the pencil, press F2, or right-click > Rename. Reset name restores the GitHub name. Custom names are saved and exported.
- Fix: when the window is stretched sideways, all columns now grow in proportion (before, only Status grew). Shrinking works the same way, and a column you drag keeps your width until the window is resized.
- Fix: a project with an empty About box on GitHub no longer shows another project's description; it shows "No description, website, or topics provided."
- Fix: status messages such as "Renamed to ..." or "Marked 1 project(s) as seen." are no longer replaced right away by the project description.
- `build.bat` now checks Python and tkinter, reads the version, adds the icon and writes ready-to-paste release notes with the SHA-256.
- The GitHub Actions workflow (manual run) now also writes the release notes, with the SHA-256 and a link to the public build log. It never touches a Release by itself.

## [1.0.1]
- Right-click menus in text boxes (Cut / Copy / Paste / Select all) and on the status bar (Copy).

## [1.0.0]
- First release: add GitHub projects, check for new releases (feed first, API as fallback), sortable list, import / export, light and dark theme, portable `.exe`.
