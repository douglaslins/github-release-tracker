# GitHub Release Tracker

A small, portable Windows app that tracks the latest release of the projects you care about on GitHub, GitLab, Gitea and Forgejo, and tells you when a new one appears. It can also check whether that release is already in your download folder. No account, no login, and no token needed for public projects.

🇮🇩 [Baca dalam Bahasa Indonesia](README.id.md)

<!-- Add a screenshot of your own here, e.g. save it as docs/screenshot.png and use:
![Screenshot](docs/screenshot.png)
-->

## Features

- Add a project by pasting its URL: a GitHub URL or `owner/repo`, a GitLab project (also self-hosted), or a Gitea or Forgejo project such as one on Codeberg
- Paste several addresses at once. Each one appears in the list immediately and fills in when its lookup finishes, so the window never waits
- See the project name, repository, current release, publish date and status at a glance
- **Check for updates** refreshes every project; a project with a newer release is highlighted as `Update available: v1.0 -> v1.1`
- **Mark as seen** clears the highlight once you have dealt with an update
- Double-click a project to open its release page in your browser
- **Download folder** (Settings): point the app at the folder where you keep your downloads. Each project then shows `Up to date 🟢 (latest)`, `Up to date 🟢 (Pre-release available)`, `Needs update 🟡` or `Not downloaded 🔴`, based on the files in that folder
- **SHA-256 check**: a file counts as a release file when its SHA-256 matches, so renamed files are found, and a damaged or modified file shows `(hash mismatch)`. Turn the check off in Settings to compare names only
- Right-click a project > **Change folder...** to scan a different folder for that project only. **Rescan files** re-reads the folders without using the network
- **Check for updates** looks at up to 6 projects at the same time
- **Rename a project** to something readable: hover a row and click the pencil (or press **F2**, or right-click > Rename). *Reset name* brings the GitHub name back. Your names are saved and included in Export
- Click the **Project**, **Repository**, **Published** or **Status** header to sort (click again to reverse; an arrow shows the direction)
- **Import / Export** your project list as a `.json` file (merge or replace on import)
- **Light / dark** mode: click the moon / sun button (starts with your Windows theme)
- Columns resize in proportion when you stretch or shrink the window (drag a column border to change the proportions)
- Small icons on the buttons, thin separator lines between rows and columns, and the app's own icon
- Version number in the window title; **Settings > About** shows it too
- Right-click menu in the text boxes (Cut / Copy / Paste / Select all), and right-click the status bar to copy its message
- Portable: one `.exe`, no installer, no registry entries

The app only reads release information. It never downloads or installs anything. The only thing it reads on your PC is the download folder you choose (file names, sizes and, for the SHA-256 check, file contents). Nothing from that folder is sent anywhere.

## What you need

Pick the row that matches what you want to do.

| I want to... | You need |
|---|---|
| **Just use the app** (`.exe` from [Releases](https://github.com/santosasarno-code/github-release-tracker/releases)) | Windows 10 or 11, an internet connection. **Nothing else**: Python is *not* required. |
| **Run from source** (`github_release_tracker.py`) | Windows 10/11, **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/windows/). No extra packages. |
| **Build the `.exe` yourself** (`build.bat`) | The same Python, with **"Add python.exe to PATH"** ticked in the installer, and an internet connection (the script downloads PyInstaller). |

### Python details (only for running from source or building)

- **Version:** the source is written for standard Python and its syntax works from Python 3.6, but only recent versions are recommended. Tested versions: **3.10 and 3.12** (automated GUI tests on Linux) and **3.8** (logic tests only; its GUI could not be tested). Use 3.10 or newer.
- **tkinter must be included.** The python.org installer includes it by default (the "tcl/tk and IDLE" option). Check with:
  ```
  python -c "import tkinter; print('tkinter OK')"
  ```
  If that fails with `No module named tkinter`, re-run the Python installer, choose *Modify*, and tick **tcl/tk and IDLE**.
- **No `pip install` is needed** to run from source: the app uses only Python's standard library. PyInstaller is needed only for building, and `build.bat` installs it for you.
- Python from other sources (for example the Microsoft Store) has not been tested; the python.org installer is the recommended one.

## Quick start

### Use the `.exe`

1. Download `GitHubReleaseTracker.exe` from the [Releases page](https://github.com/santosasarno-code/github-release-tracker/releases).
2. Put it in any folder you like (it can live on a USB stick) and run it.
3. Paste a project URL such as `https://github.com/owner/repo` (or one from GitLab, Codeberg and so on) and click **Add project**.
4. Later, click **Check for updates**.

> **Windows may warn you** ("Windows protected your PC") or antivirus may flag the file. This happens often with single-file executables made by PyInstaller and the app is not code-signed. If you do not want to trust a downloaded `.exe`, read the source (it is one Python file) and build it yourself with the steps below.

#### Verify your download

From v1.1.0 on, the `.exe` on the Releases page is built by the **GitHub Actions workflow** "Build Windows exe" on a GitHub-hosted Windows machine, from the source in this repository. The release notes link to the public build log of that exact run, so you can see how the file was made. (v1.0.0 and v1.0.1 were built by the author on their own PC with `build.bat`.) The author still downloads the result and attaches it to the Release by hand.

The SHA-256 hash of each release's `.exe` is listed in that release's notes. To check that your download is intact, open PowerShell in the folder with the file and run:

```
Get-FileHash .\GitHubReleaseTracker.exe -Algorithm SHA256
```

The hash must match the one in the release notes. This proves the file is the one that was published, not that it is safe; the source code is what you can actually inspect. If you build the `.exe` yourself the hash will differ: builds on different machines are not identical byte for byte.

### Run from source

```
python github_release_tracker.py
```
(or `py github_release_tracker.py`)

### Build the `.exe` yourself

1. Install Python (see above) and download this repository.
2. Double-click `build.bat`.
3. Your portable app appears at `dist\GitHubReleaseTracker.exe`.

Manual alternative:
```
pip install pyinstaller
pyinstaller --onefile --windowed --icon icon.ico --name GitHubReleaseTracker github_release_tracker.py
```

`build.bat` also checks Python and tkinter, adds the icon, and writes a ready-to-paste release notes file with the SHA-256 (`dist\release-notes-vX.Y.Z.md`). Maintainers: see [RELEASING.md](RELEASING.md) for the full release checklist and [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## How it works

- It reads each project's public release feed, `https://github.com/<owner>/<repo>/releases.atom`. This needs no login and does not use the GitHub API's request limit.
- If the feed fails or a project has no releases, it falls back to GitHub's API (which allows about 60 requests per hour without a token). If the project has no GitHub Releases at all, it shows the newest git tag instead.
- When you add a project, its current release counts as already seen. Only releases published afterwards are flagged as updates.
- Update detection compares the release identity (and tag), not version numbers, so unusual tags like `nightly` or `build-123` work. Side effect: a deleted and re-created release can show up as an update.
- GitLab, Gitea and Forgejo projects are read through the host's public API, one request per project. For a self-hosted address the app finds out which kind of server it is. A private project, or a server that limits anonymous requests, needs an access token: right-click a project > *Set access token for this host...*. A token is only sent to the host it belongs to.
- The app contacts only the hosts of the projects you add: `github.com` and `api.github.com` for GitHub projects, and the project's own host (for example `gitlab.com` or `codeberg.org`) for the others.

### How the download folder is compared

- The app scans the folder and its sub-folders (3 levels deep) and compares the files with each project's recent releases. The newest release found decides the status. File lists and SHA-256 values are kept for the 8 newest releases.
- A file belongs to a release in one of two ways. **SHA-256**: the file has the same hash as a release file, whatever its name. **Name**: the file name (or its folder's name) holds the project name and the release version, for example `ShareX-16.0.1-setup.exe` for release `v16.0.1`. The name check is used for releases that have no checksum to compare.
- GitHub's API lists a SHA-256 for release files. GitLab, Gitea and Forgejo do not, so the app reads a checksum file attached to the release (`SHA256SUMS`, `checksums.txt` or `file.zip.sha256`) or checksum lines in the release text.
- A file with the right name but a different SHA-256 does not count. It may be incomplete, damaged, modified, or a source archive. The status then ends with `(hash mismatch)`.
- Only files with the same size as a release file are read. The hash of each file is remembered in `hash_cache.json` until the file changes.
- Pre-releases: GitHub is asked through its API (one call per project, only when something may have changed). Gitea and Forgejo report the flag themselves. GitLab has no such flag, so tag names such as `-beta` or `-rc1` decide there.

## Your data

- Your list is saved in `projects.json` **next to the `.exe`**. If that folder is read-only (for example `Program Files`), it uses `%APPDATA%\GitHubReleaseTracker` instead.
- **Export** writes a separate `.json` file for backup or moving to another PC. **Import** reads it back (and also reads the `projects.json` of older builds).
- **Custom names travel with the file.** If you rename a project and share your Export, the other person's **Import** shows your names for projects they do not have yet. For a project they already have, **Merge** keeps their entry and name unchanged (your name is not applied); **Replace** swaps their whole list for the file, names included. Files exported by v1.1.0 still import in older versions, but the custom names are dropped.
- Settings has an optional GitHub token. It is **not needed** for normal use. If you add one, it is stored **in plain text** in `projects.json`, so do not share or upload that file. Exported files never contain the token. The same holds for access tokens you set for other hosts.
- **Do not open a list that holds GitLab, Gitea or Forgejo projects in an older version** (v1.1.1 or earlier). Older versions read every entry as a GitHub project, so those entries would point to the wrong host.
- `hash_cache.json` (next to `projects.json`) remembers the SHA-256 of your downloaded files, so a large file is read only once. It is safe to delete.
- `projects.lock` (also next to `projects.json`) stops a second copy of the app from opening the same data, because two copies would overwrite each other's changes.

## Known limitations

- Windows only (developed for Windows 10/11).
- The release feed does not say which releases are pre-releases, so the `(pre-release)` label is not shown for feed results. "Stable only" mode (right-click a project, untick *Include pre-releases*) uses the API and its rate limit.
- The feed is a public GitHub page, not an official API; GitHub could change or throttle it.
- Private repositories are not supported without a token.
- GitLab publishes no pre-release flag, file sizes or checksums, and Gitea and Forgejo publish no checksums. On those hosts the status relies on tag names, file names and any checksum file attached to the release. A release without a checksum file is matched by name only.
- Support for GitLab, Gitea and Forgejo has so far been tested against simulated servers only, not against live ones.
- Only one copy of the app can run per data folder.
- The "Published" date comes from the feed's updated time, so editing a release on GitHub can change it.
- A project's description (shown in the status bar when you select it) is read once, when the project is added, and is not refreshed later. If the GitHub API was unavailable at that moment, the project shows "No description, website, or topics provided." even if the repository has one.
- The row and column lines and the rename pencil are small widgets drawn over the list. A click exactly on a 1-pixel line is passed on to the row, but a *double*-click exactly on that line may not open the release page.
- Icons are 16 px (24 px on screens scaled to 150% or more). Not every Windows display setup has been tested.

## Files in this repository

| File | What it is |
|---|---|
| `github_release_tracker.py` | The whole app (one Python file, standard library only). |
| `build.bat` | Builds `dist\GitHubReleaseTracker.exe`. |
| `icon.ico` | The app icon used by the build. |
| `tools/` | Maintainer helpers: `release_info.py` (used by `build.bat`) and `make_icons.py` (regenerates the icons; needs Pillow, not needed to use or build the app). |
| `CHANGELOG.md`, `RELEASING.md` | What changed, and how to publish a release. |

## Troubleshooting

| Problem | What to do |
|---|---|
| `No module named tkinter` | Reinstall Python from python.org with **tcl/tk and IDLE** ticked. |
| `python` is not recognized | Reinstall Python and tick **Add python.exe to PATH**, or use `py` instead of `python`. |
| "GitHub API rate limit reached" | You hit the 60-per-hour limit of the API fallback. Wait until the time shown, or add a token in **Settings**. |
| "Not found" when adding a project | Check the spelling. Private repositories are not supported without a token. |
| Windows SmartScreen / antivirus warning | See the note under *Use the `.exe`*. |
| The status ends with `(hash mismatch)` | A file in your folder has the right name but a different SHA-256 than the release files. It may be incomplete, damaged or modified. Download it again. |
| A GitLab, Gitea or Forgejo project shows a rate-limit error | The host limits anonymous requests. Wait a few minutes, or right-click the project and add an access token for that host. |
| "... is already running with this data folder" | A copy of the app is already open. Look for it in the taskbar. For a second copy with its own list, keep it in a different folder. |
| A project shows "No releases published" | The repository has no GitHub Releases and no tags yet. |

## License

[MIT](LICENSE). This project is not affiliated with or endorsed by GitHub.
