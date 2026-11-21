<p align="center">
  <img src="icon.png" alt="App icon: a white release tag on a teal rounded square with an orange dot" width="160">
</p>

<h1 align="center">GitHub Release Tracker</h1>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/douglaslins/github-release-tracker?style=flat-square" alt="license"/></a>
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?style=flat-square&logo=windows&logoColor=white" alt="platform Windows"/>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10 or newer"/>
  <a href="https://github.com/douglaslins/github-release-tracker/commits/main"><img src="https://img.shields.io/github/last-commit/douglaslins/github-release-tracker?style=flat-square&logo=github&logoColor=white" alt="last commit"/></a>
</p>

Portable Windows app that tracks the latest release of projects on GitHub, GitLab, Gitea and Forgejo, and checks whether the matching files are in your download folder. It never downloads or installs a release.

> Unofficial fork of [santosasarno-code/github-release-tracker](https://github.com/santosasarno-code/github-release-tracker/tree/v1.1.1). The additions below were proposed upstream in [PR #2](https://github.com/santosasarno-code/github-release-tracker/pull/2), which was closed without merging.

🇮🇩 [Baca dalam Bahasa Indonesia](README.id.md)

## Features

Added by this fork:

- **More hosts.** Add projects from GitHub, GitLab (nested groups and self-hosted servers work), Gitea and Forgejo (for example Codeberg) by pasting the project URL. The app detects the server type of a self-hosted address.
- **Download folder check.** Set a folder in Settings. The app scans it and its sub-folders (3 levels deep) and shows one status per project (see [Usage](#usage)).
- **SHA-256 matching.** A file counts as a release file when its hash equals one of the release's files, so renamed files are found. A file with a matching name but a different hash shows `(hash mismatch)`. Turn the check off in Settings to compare names only.
- **Folder per project.** Right-click a project > **Change folder...** to scan another folder for that project only. **Rescan files** re-reads the folders without network access.
- **Access tokens per host.** Right-click a project > **Set access token for this host...** for private projects or servers that limit anonymous requests. A token is sent only to its own host.
- **Bulk add.** Paste up to 20 addresses at once. Each appears immediately as `Adding ...` and fills in when its lookup finishes.
- **Faster checks.** Up to 6 projects are checked at the same time, with at most 3 requests at once to one host (4 for github.com, api.github.com, gitlab.com and codeberg.org). A host that does not answer is skipped for 30 seconds.
- **One copy per data folder.** `projects.lock` stops a second copy from overwriting the first one's changes.

<details>
<summary>Inherited from upstream</summary>

- **Check for updates** highlights releases published since you last looked (`Update available: v1.0 -> v1.1`); **Mark as seen** clears the highlight
- Rename a project (hover a row and click the pencil, press **F2**, or right-click > Rename); names are saved and exported
- Sort by Project, Repository, Published or Status
- Import and export the project list as `.json` (merge or replace)
- Light and dark theme
- Portable: a single `.exe` that runs from any folder, including a USB stick

</details>

## Requirements

- Windows 10 or 11 and an internet connection
- Python 3.10 or newer with tkinter, to run from source or to build (no `pip install` needed to run)

## Install

The `.exe` on upstream's Releases page does not include the features above. Run the fork from source or build the `.exe` yourself.

Run from source:

```bat
python github_release_tracker.py
```

Build the portable `.exe` (installs PyInstaller, needs "Add python.exe to PATH"):

```bat
build.bat
```

The result is `dist\GitHubReleaseTracker.exe`.

## Usage

1. Paste a project address and click **Add project**. Accepted forms:

   ```text
   <owner>/<repo>
   https://github.com/<owner>/<repo>
   https://gitlab.com/<group>/<subgroup>/<project>
   https://codeberg.org/<owner>/<repo>
   https://git.example.org/<owner>/<repo>
   ```

2. Open **Settings** and choose the folder where you keep your downloads.
3. Click **Check for updates**. Each project shows one of these statuses:

| Status | Meaning |
|---|---|
| `Up to date 🟢 (latest)` | A file for the newest release is in the folder |
| `Up to date 🟢 (Pre-release available)` | A file for the newest stable release is present and a newer pre-release exists |
| `Needs update 🟡` | Only files for older releases are present |
| `Not downloaded 🔴` | No file for any recent release is present |
| `... (hash mismatch)` | A file name matches but its SHA-256 differs from every file of that release |

Double-click a project to open its release page in your browser.

## Known limitations

- Windows only.
- GitLab publishes no pre-release flag, file sizes or checksums, and Gitea and Forgejo publish no checksums. On those hosts the status relies on tag names, file names and checksum files attached to the release. A release without a checksum file is matched by name only.
- Older versions of the app read every entry in `projects.json` as a GitHub project, so a list that holds other hosts must not be opened with them.
- Limitations inherited from upstream are listed in [docs/troubleshooting.md](docs/troubleshooting.md).

## Docs

- [How it works](docs/how-it-works.md): data sources, request limits, folder comparison, data files, repository files
- [Troubleshooting](docs/troubleshooting.md): Python and tkinter, common errors, inherited limitations
- [CHANGELOG.md](CHANGELOG.md), [RELEASING.md](RELEASING.md)

## License and legal

- [MIT](LICENSE). Original work by santosasarno-code; additions in this fork by douglaslins.
- Not affiliated with or endorsed by GitHub, GitLab, Gitea, Forgejo or Codeberg. Product and service names belong to their owners.
