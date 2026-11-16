# GitHub Release Tracker

A small, portable Windows app that tracks the latest release of the GitHub projects you care about and tells you when a new one appears. No account, no login, and no token needed.

🇮🇩 [Baca dalam Bahasa Indonesia](README.id.md)

<!-- Add a screenshot of your own here, e.g. save it as docs/screenshot.png and use:
![Screenshot](docs/screenshot.png)
-->

## Features

- Add a project by pasting a GitHub URL or `owner/repo`
- See the project name, repository, current release, publish date and status at a glance
- **Check for updates** refreshes every project; a project with a newer release is highlighted as `Update available: v1.0 -> v1.1`
- **Mark as seen** clears the highlight once you have dealt with an update
- Double-click a project to open its release page in your browser
- Click the **Project**, **Repository**, **Published** or **Status** header to sort (click again to reverse; an arrow shows the direction)
- **Import / Export** your project list as a `.json` file (merge or replace on import)
- **Light / dark** mode toggle (starts with your Windows theme)
- Portable: one `.exe`, no installer, no registry entries

The app only reads release information. It never downloads or installs anything.

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
3. Paste a GitHub URL such as `https://github.com/owner/repo` and click **Add project**.
4. Later, click **Check for updates**.

> **Windows may warn you** ("Windows protected your PC") or antivirus may flag the file. This happens often with single-file executables made by PyInstaller and the app is not code-signed. If you do not want to trust a downloaded `.exe`, read the source (it is one Python file) and build it yourself with the steps below.

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
pyinstaller --onefile --windowed --name GitHubReleaseTracker github_release_tracker.py
```

## How it works

- It reads each project's public release feed, `https://github.com/<owner>/<repo>/releases.atom`. This needs no login and does not use the GitHub API's request limit.
- If the feed fails or a project has no releases, it falls back to GitHub's API (which allows about 60 requests per hour without a token). If the project has no GitHub Releases at all, it shows the newest git tag instead.
- When you add a project, its current release counts as already seen. Only releases published afterwards are flagged as updates.
- Update detection compares the release identity (and tag), not version numbers, so unusual tags like `nightly` or `build-123` work. Side effect: a deleted and re-created release can show up as an update.
- The app contacts only `github.com` and `api.github.com`.

## Your data

- Your list is saved in `projects.json` **next to the `.exe`**. If that folder is read-only (for example `Program Files`), it uses `%APPDATA%\GitHubReleaseTracker` instead.
- **Export** writes a separate `.json` file for backup or moving to another PC. **Import** reads it back (and also reads the `projects.json` of older builds).
- Settings has an optional GitHub token. It is **not needed** for normal use. If you add one, it is stored **in plain text** in `projects.json`, so do not share or upload that file. Exported files never contain the token.

## Known limitations

- Windows only (developed for Windows 10/11).
- The release feed does not say which releases are pre-releases, so the `(pre-release)` label is not shown for feed results. "Stable only" mode (right-click a project, untick *Include pre-releases*) uses the API and its rate limit.
- The feed is a public GitHub page, not an official API; GitHub could change or throttle it.
- Private repositories are not supported without a token.
- The "Published" date comes from the feed's updated time, so editing a release on GitHub can change it.

## Troubleshooting

| Problem | What to do |
|---|---|
| `No module named tkinter` | Reinstall Python from python.org with **tcl/tk and IDLE** ticked. |
| `python` is not recognized | Reinstall Python and tick **Add python.exe to PATH**, or use `py` instead of `python`. |
| "GitHub API rate limit reached" | You hit the 60-per-hour limit of the API fallback. Wait until the time shown, or add a token in **Settings**. |
| "Not found" when adding a project | Check the spelling. Private repositories are not supported without a token. |
| Windows SmartScreen / antivirus warning | See the note under *Use the `.exe`*. |
| A project shows "No releases published" | The repository has no GitHub Releases and no tags yet. |

## License

[MIT](LICENSE). This project is not affiliated with or endorsed by GitHub.
