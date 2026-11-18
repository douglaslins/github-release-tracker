# Changelog

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

## [1.0.1]
- Right-click menus in text boxes (Cut / Copy / Paste / Select all) and on the status bar (Copy).

## [1.0.0]
- First release: add GitHub projects, check for new releases (feed first, API as fallback), sortable list, import / export, light and dark theme, portable `.exe`.
