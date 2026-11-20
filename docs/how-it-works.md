# How it works

## Reading release data

- GitHub projects: the app reads the public release feed `https://github.com/<owner>/<repo>/releases.atom`. This needs no login and does not use the GitHub API request limit.
- If the feed fails or a project has no releases, it falls back to the GitHub API (about 60 requests per hour without a token). A project with no GitHub Releases shows its newest git tag.
- GitLab, Gitea and Forgejo projects are read through the host's public API, one request per project. For a self-hosted address the app tries Gitea/Forgejo first, then GitLab, to find the server type.
- A private project, or a server that limits anonymous requests, needs an access token: right-click a project > **Set access token for this host...**. A token is sent only to its own host, including after a redirect.
- When you add a project, its current release counts as already seen. Only releases published afterwards are flagged as updates.
- Update detection compares the release identity and tag, not version numbers, so tags such as `nightly` or `build-123` work. A deleted and re-created release can show up as an update.
- The app contacts only the hosts of the projects you add: `github.com` and `api.github.com` for GitHub projects, and the project's own host (for example `gitlab.com` or `codeberg.org`) for the others. Nothing from your download folder is sent anywhere.

## Request limits

- Up to 6 projects are checked at the same time, with at most 3 requests at once to one host (4 for `github.com`, `api.github.com`, `gitlab.com` and `codeberg.org`).
- A host that does not answer is skipped for 30 seconds, and the status line reports how many projects were skipped. A host that asks for a slower pace is not queried again in the same run.
- Requests ask for gzip. Unpacked answers larger than 8 MB are not read.
- Up to 20 addresses are taken from one paste. The rest stay in the input box.

## How the download folder is compared

- The app scans the folder and its sub-folders (3 levels deep) and compares the files with each project's recent releases. The newest release found decides the status. File names, sizes and SHA-256 values are kept for the 8 newest releases.
- A file belongs to a release in one of two ways.
  - **SHA-256:** the file has the same hash as a release file, whatever its name.
  - **Name:** the file name (or its folder's name) holds the project name and the release version, for example `ShareX-16.0.1-setup.exe` for release `v16.0.1`. For a project name with several words, the leading words (4 letters or more) are enough at the start of a file name. The name check is used for releases that have no checksum to compare.
- A project-specific folder (right-click > **Change folder...**) is treated as dedicated to that project, so the project name does not have to appear in the file names there.
- GitHub's API lists a SHA-256 for release files. GitLab, Gitea and Forgejo do not, so the app reads a checksum file attached to the release (`SHA256SUMS`, `checksums.txt` or `file.zip.sha256`) or checksum lines in the release text. GitLab also gives no file sizes, so only files with the same name as a release file are compared there.
- A file with the right name but a different SHA-256 does not count. It may be incomplete, damaged, modified, or a source archive. The status then ends with `(hash mismatch)`.
- Only files with the same size as a release file are read. The hash of each file is kept in `hash_cache.json` until the file changes.
- Pre-releases: GitHub is asked through its API (one call per project, only when something may have changed). If the API limit is used up, tag names such as `-beta` or `-rc1` serve as a guess until the next check. Gitea and Forgejo report the flag themselves. GitLab has no such flag, so tag names decide there.

## Your data

- The list is saved in `projects.json` **next to the `.exe`** (or next to `github_release_tracker.py`). If that folder is read-only (for example `Program Files`), `%APPDATA%\GitHubReleaseTracker` is used instead.
- **Export** writes a separate `.json` file for backup or moving to another PC. **Import** reads it back (and also reads the `projects.json` of older builds).
- Custom names travel with an exported file. On import, **Merge** keeps the importer's existing entry and name for a project they already have; **Replace** swaps the whole list for the file, names included.
- A GitHub token (optional, in Settings) and access tokens for other hosts are stored **in plain text** in `projects.json`. Do not share or upload that file. Exported files never contain tokens.
- `hash_cache.json` (next to `projects.json`) remembers the SHA-256 of downloaded files so a large file is read once. It is safe to delete.
- `projects.lock` (next to `projects.json`) stops a second copy of the app from opening the same data, because two copies would overwrite each other's changes.
- Do not open a list that holds GitLab, Gitea or Forgejo projects in an older version of the app (upstream v1.1.1 or earlier). Older versions read every entry as a GitHub project.

## Files in this repository

| File | What it is |
|---|---|
| `github_release_tracker.py` | The whole app (one Python file, standard library only). |
| `build.bat` | Builds `dist\GitHubReleaseTracker.exe`. |
| `icon.ico`, `icon.png` | The app icon used by the build, and a 256 px PNG of it for the README. |
| `tools/` | Maintainer helpers: `release_info.py` (used by `build.bat`) and `make_icons.py` (regenerates the icons; needs Pillow). |
| `.github/workflows/build.yml` | Optional manual build on a GitHub-hosted Windows runner. |
| `CHANGELOG.md`, `RELEASING.md` | What changed, and how to publish a release. |
