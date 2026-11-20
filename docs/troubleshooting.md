# Troubleshooting

## Python and tkinter

- Use Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/). Python from other sources, such as the Microsoft Store, has not been tested.
- tkinter must be included. The python.org installer includes it by default (the **tcl/tk and IDLE** option). Check with:
  ```bat
  python -c "import tkinter; print('tkinter OK')"
  ```
  If that fails with `No module named tkinter`, re-run the Python installer, choose **Modify**, and tick **tcl/tk and IDLE**.
- Running from source needs no `pip install`. PyInstaller is needed only to build, and `build.bat` installs it.

## Common problems

| Problem | What to do |
|---|---|
| `No module named tkinter` | Reinstall Python from python.org with **tcl/tk and IDLE** ticked. |
| `python` is not recognized | Reinstall Python and tick **Add python.exe to PATH**, or use `py` instead of `python`. |
| "GitHub API rate limit reached" | The API fallback allows about 60 requests per hour. Wait until the time shown, or add a token in **Settings**. |
| "Not found" when adding a project | Check the spelling. Private projects need an access token. |
| The status ends with `(hash mismatch)` | A file in your folder has the right name but a different SHA-256 than the release files. It may be incomplete, damaged or modified. Download it again. |
| A GitLab, Gitea or Forgejo project shows a rate-limit error | The host limits anonymous requests. Wait a few minutes, or right-click the project and set an access token for that host. |
| "... is already running with this data folder" | A copy of the app is already open. Look for it in the taskbar. For a second copy with its own list, keep it in a different folder. |
| A project shows "No releases published" | The repository has no releases and no tags yet. |
| SmartScreen or antivirus warns about a built `.exe` | Single-file executables made by PyInstaller are often flagged, and the app is not code-signed. Read the source (one Python file) and build it yourself with `build.bat`. |

## Known limitations inherited from upstream

- The GitHub release feed does not say which releases are pre-releases, so the `(pre-release)` label is not shown for feed results. "Stable only" mode (right-click a project, untick *Include pre-releases*) uses the API and its rate limit.
- The feed is a public GitHub page, not an official API; GitHub could change or throttle it.
- The "Published" date comes from the feed's updated time, so editing a release on GitHub can change it.
- A project's description (shown in the status bar when you select it) is read once, when the project is added. If the API was unavailable at that moment, the project shows "No description, website, or topics provided." even if the repository has one.
- The row and column lines and the rename pencil are small widgets drawn over the list. A *double*-click exactly on a 1-pixel line may not open the release page.
- Icons are 16 px (24 px on screens scaled to 150% or more). Not every Windows display setup has been tested.
