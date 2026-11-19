"""
GitHub Release Tracker (portable)
=================================
A small portable Windows desktop app (Python + tkinter, standard library only)
that tracks the latest release of projects on GitHub, GitLab, Gitea and Forgejo,
and tells you when a new one has been published since you last acknowledged it.

How it works
- Add a project by pasting its URL, for example
      https://github.com/owner/repo
      https://gitlab.com/group/project         (nested groups work too)
      https://codeberg.org/owner/repo          (any Gitea or Forgejo server)
      https://git.example.org/owner/repo       (a self-hosted server: the app
                                                finds out which kind it is)
  or just "owner/repo" for a GitHub project.
- The list shows project name, repository, latest release, publish date, status.
- "Check for updates" reads each GitHub project's public release feed
  (github.com/owner/repo/releases.atom): no login or token needed and it does not
  use the GitHub API rate limit. The API is only a fallback. GitLab, Gitea and
  Forgejo projects are read through their public API (one call per project).
  A private project, or a server that limits anonymous calls, needs an access
  token: right-click a project and choose "Set access token for this host...".
  A token is only ever sent to the host it belongs to.
- A project whose latest release differs from the one you last acknowledged is
  highlighted as "Update available: old -> new".
- "Mark as seen" acknowledges the current release (clears the highlight).
  It only matters while no download folder is set (see below).
- Download folder: in Settings, point the app at the folder where you keep your
  downloaded releases. It scans that folder (and its sub-folders, 3 levels deep)
  and compares the files with each project's recent releases:
      Up to date (latest)                    the file is the newest release
      Up to date (Pre-release available)     the file is the newest stable release,
                                             and a newer pre-release exists
      Needs update (yellow)                  only a file for an older release is present
      Not downloaded (red)                   no file for any recent release is present
  Pre-releases are told apart from normal releases with the GitHub API (one call
  per project, only when something may have changed). If the API limit is used
  up, tag names such as -beta or -rc1 are used as a guess until the next check.
  Gitea and Forgejo report the pre-release flag themselves. GitLab has no such
  flag, so tag names such as -beta or -rc1 decide there.
  A file belongs to a release in one of two ways:
      SHA-256   the file has the same SHA-256 as a file of that release. GitHub
                publishes this checksum for each release file, and the same API
                call reads it. GitLab, Gitea and Forgejo do not, so the app reads
                the checksum file attached to a release instead (SHA256SUMS,
                checksums.txt, or "file.zip.sha256"), and checksum lines in the
                release text. File names do not matter, so a renamed file is
                still found. GitLab does not publish file sizes: there, only a
                file with the same name as a release file is compared by SHA-256.
      Name      the file name (or its folder's name) holds the project name and
                the release version, for example "ShareX-16.0.1-setup.exe" for
                the "ShareX" project and release "v16.0.1". For a name with
                several words, the leading words are enough at the start of a
                file name (4 letters or more): "TotK-Setup-0.4.1-windows.zip"
                counts for the repository "totk-pc-recomp". This is used for
                releases that GitHub has no checksum for.
  A file whose name matches a release, but whose SHA-256 differs from every file
  of that release, does not count: it may be incomplete, corrupt, modified, or a
  source archive. The status then ends with "(hash mismatch)".
  Only files with the same size as a release file are read. Each hash is kept in
  hash_cache.json (next to projects.json) until the file changes. Turn the check
  off in Settings to compare names only.
  Right-click a project and choose "Change folder..." to scan a different folder
  for just that project. A project-specific folder is treated as dedicated to
  that project, so the project name does not have to appear in the file names
  there.
- "Rescan files" re-reads the folders without touching the network.
- The app never downloads or installs anything; it opens the release page.
- "Import" / "Export" read and write a .json file (merge or replace on import).
- The moon / sun button toggles the dark / light theme; the choice is remembered.
- Hover a row and click the pencil (or press F2, or right-click > Rename) to give a
  project your own display name. Reset name brings the GitHub name back.

Portable: no installer, no registry writes. Data lives in projects.json next to
the .exe (or this script). Only if that folder is read-only does the app fall
back to %APPDATA%\\GitHubReleaseTracker.

Build the single-file portable .exe on Windows: double-click build.bat, or run
    pip install pyinstaller
    pyinstaller --onefile --windowed --icon icon.ico --name GitHubReleaseTracker github_release_tracker.py
The exe appears in the dist folder.
"""

import base64
import bisect
import concurrent.futures
import hashlib
import http.client
import json
import os
import queue
import re
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import webbrowser
import zlib
from datetime import datetime, timezone

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_NAME = "GitHub Release Tracker"
# Keep in step with the release tag: tag v1.1.1 <-> APP_VERSION "1.1.1" (build.bat checks the format).
APP_VERSION = "1.1.1"
APP_ID = "santosasarno-code.GitHubReleaseTracker"  # Windows taskbar identity (so the taskbar shows our icon)
REPO_URL = "https://github.com/santosasarno-code/github-release-tracker"
NO_DESCRIPTION = "No description, website, or topics provided."  # same wording GitHub shows for an empty About box
API = "https://api.github.com"
GITHUB_BASE = "https://github.com"
KINDS = ("github", "gitlab", "gitea")     # Gitea and Forgejo share one API
KIND_LABEL = {"github": "GitHub", "gitlab": "GitLab", "gitea": "Gitea/Forgejo"}
USER_AGENT = "GitHubReleaseTracker"
MAX_JSON_BYTES = 8 * 1024 * 1024    # largest API answer read (after unpacking)
CHECK_WORKERS = 6                   # projects checked at the same time
HOST_PARALLEL = 3                   # requests at the same time to one host: small servers are easily overloaded
HOST_PARALLEL_BIG = {"github.com": 4, "api.github.com": 4, "gitlab.com": 4, "codeberg.org": 4}
HOST_DOWN_SECONDS = 30              # a host that did not answer is not tried again for this long
MAX_CHECKSUM_FILES = 3              # checksum files read per release (GitLab, Gitea, Forgejo)
MAX_CHECKSUM_BYTES = 512 * 1024     # a larger checksum file is skipped
MAX_PROJECTS = 500
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_HISTORY = 100          # release tags kept per project for the folder comparison
SCAN_MAX_DEPTH = 3         # sub-folder levels scanned below a download folder
SCAN_MAX_ENTRIES = 20000   # safety cap on files and folders read per scan
PARTIAL_EXT = (".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload")
MAX_ASSET_RELEASES = 8     # newest releases whose file names, sizes and SHA-256 digests are kept
MAX_ASSETS_PER_RELEASE = 50
ASSET_REFRESH_HOURS = 24   # a release this young is re-read from the API: files may still be uploading
MAX_MATCHES = 50           # files per release version considered by the name check
HASH_CACHE_MAX = 5000      # local file hashes remembered between runs
MAX_CUSTOM_NAME = 80

# --- BEGIN GENERATED ICON DATA (tools/make_icons.py) ---
# Toolbar icons: zlib-compressed 8-bit alpha masks, base64. Window icon: 64 px PNG, base64.
ICON_MASKS = {
    "refresh": {
        16: (
            "eNpjYAADRkYGRgY4YGZiYGBhNBSBigF5PLwMDA/CGJkh3MDd7z9um/1/MQMzmNvy///Tp/+BQBbIYWbw+//Uk4194eEZeZJA"
            "Y5kYDvx3AxrEBbWIgefTUyaQBczsrIwIPiML1G6YegaHdCGgdrh5ni//e6Da1wByGMw973cHwn0Aci8PA1QW5h8mZgYkwAhT"
            "CwBdBy28"
        ),
        24: (
            "eNpjYEADTAxYASOGOhYgYGRiyJdDlmNkhsoq/YtkZEE2VC68ujpcnmHt/7UMzAhhiTmf/gPBp21//32RgNnNxKD/8D8U/P7x"
            "P5sBYhATk9iT//+/LUxPn/cNJLWLEaKemWHe/7+3dIEs3osHp2TayjBCTZH5/u+rJgMbC4uAAJLDWRgi//9fyMAK8wUzI0y8"
            "5t//FIijGZH8hCwOFGZhxGIOE0oAwu1lY9A+VyjJCNWBcCeD7s3//ydBvYXkr4VAfz2QZGRiwAyHh/pIliDCbY4Emt2QcJZD"
            "j0dYvDBjj0cckU4EAAARF2gZ"
        ),
    },
    "eye": {
        16: (
            "eNpjYCAIGJlZWJhBmBHMZUbIgJhMDAwm+TPXrp2ZbwLiMDEEXPwPBRcDgNz0/x973Xf9/r3Lvffj/3QGga9X+Bk0/wGBJgP/"
            "la8C6Hx09RjmodmH4R4M9+IHADTyQCU="
        ),
        24: (
            "eNpjYKALYGRmAQNmRmRBFiYEh4kFJsUMxBIOaQ39/Q1pDhJQARDJmbz9zX8oeLM9mRMswczgdx0k8PPH798/foJY1/2AgswM"
            "mUDm1amRTT///v3ZFDn1KpCbCRTW/f//URgbA+uT/3///n/CysAW9uj/f10GhpZ/v8wZWFmi///+D0TRLKwM5r/+teAWx2EO"
            "TntxuBOnv3CGA85wwxnOtAQAc0yQHQ=="
        ),
    },
    "ext": {
        16: (
            "eNpjYAADZhYWFmZmJgbsgJEppX/SwtU7pzMwgvlMjBZf/wPBSQaoDiYG+Us/vv7ZyMAM5TNyHPr//99KKJ+Jge/w/yPX/s9k"
            "YIFyD/4/xC73Zh6YD+Ye5GNgMM0CqYdxmSB2MTLwQLgMYBFGJu5T/w/wMcCdysQ2/TgvA4rLWVG5jFBXIwkgAAAhdSkw"
        ),
        24: (
            "eNql0TEOAUEUBuD/zUyiQSIKewKNS6gUGqVCp1GJYnUaCRGJSusMTqGgoNdLHEHYzK5nsLtmrWQLf/lN3p83eUBWSEqpXhHI"
            "DqFSr7c6PXe8WPXxmSDh7DnMGsoeyG/Y01pf9dJ2M1vccsCseZ5wSOROd9/4KOGkMPF8DjQPEv0KM1Nz5ht3LX/xlSflHQdt"
            "U5nkGVDccCP2mKVE4dCMPGZFZt2SYz7zzQjtvbjF5oGij05tjqIw5EuaIah25GmKnz1VF5LSNxHA79MJiX/zALwVXIU="
        ),
    },
    "trash": {
        16: (
            "eNpjYEAHjIyMLEl5eUksQAZM7MP//x+gsgzrb9++/x8I7t++vR6omGHq9lVrFi1cuGjNqu1TgdJAPUYGpsbGpgZGINUMTMxa"
            "/6FAi5kJJMT7q3dnXNzO3l+8IHmgjg8t+1xc9rV8AGsG4mur9gQF7Vl1DcxlYGbYfXBHVNSOg7uBTCBgYZh783Bc3OGbc4FM"
            "ML/q5cr4+JUvq2D8uP+//wNRHITPyCCXW1hUVJgrx8CI4VkGAJoYSfs="
        ),
        24: (
            "eNpjYIACFjBgIAIwMTOzMHP0L5g/f0E/B5DJzIQs+/E/EHxE8BkZdBwdHB3dn/36+fPXM3dHIEcHKMjAzLDjPxrYARQEooWv"
            "X71///7jJyD4CGS8er0QJM7AwCPIi2wRryAPjCkSHR0ZGRkRASSio0XgPmI0QTbdhJEF5iKJj78PHT21a+fJY4d+f5QAuQYi"
            "zv7wv+Kk2wwM5xep/H/IDhMH0qf+O83+z8P0d63r/1NwYaCrNvyPnvCPm+HHotj/GyCOBFvMMPV/WfN/IbZ/U8r/T2VgQYhX"
            "/p/Y9F+Y/f/kSf8rkcXj/q+p+i/N979nzf84hDgzg8v/Iy3/FYX/Tzvy3wVhPjOD7v9bFd9FWb933fyvixBnYpD4/HXZvvbm"
            "fau/fJZgYEJEAfsHWCh8QHgLBJoXzJk/B4gWNDMQBZhZoABmKQBjiKEO"
        ),
    },
    "gear": {
        16: (
            "eNpdj8sJgEAMRCeuaBFahj14sAjtYM+LrYg1iDVoP4Kfi58x6C2BQB5MkhlAxCErywxOBMDXNVn/ICJDgH8ejzAoRPFIztt5"
            "bjM5xpFL2uPiV9fRJk6XJt5r3683J4W88TuXAigW7r7JK9WxQ5qi04GVZau39+w/68f6tXlg8r4tR3Hh"
        ),
        24: (
            "eNp1UrsKg0AQnDstUmhrEQIhTT4toJWFH5LCT5H0YqH5H0Xk9Ca3JoQU2WHv2JuBfR4QYPAD8+MZi6zt+zaDNV/BhhPbCwMu"
            "Nv4QciddBSTjuo4JUHXJLhiTdmR+vTvv3f2ak11qJPLhyYVigt17HkIWG1X0nnSrC0bxqygEMhHyZfMiCem3JUf0Luk4Cd0U"
            "RSPCdNzJ7Hyq6TaW8ii5Odancwa080iufCAOwCO4HOcWGChJeZOOYnujpOag81ocLa9Wp9aXMgd1bsqc1b2oe1T3/vefvAAF"
            "YP29"
        ),
    },
    "plus": {
        16: (
            "eNpjYAADRkYG3ICJweHMGQcgBQXMDCH//4cAKQiPmY056M+fICDFDFPh+v+/K4ztEBAU0P7/fzuQcgBaxHD1PxxcBdmLykdX"
            "j2kepn2o7sF0LxYA9y8AO7M2PQ=="
        ),
        24: (
            "eNqlkUEKgDAMBFNFSW/+v38Q/JGSfsB7YV09qaQqOPSwTGnTJiJvtES+EqRL45g6hpvXFVjV8XMps+cNsIsPpAlx95GBnE/0"
            "u+8vRlWjDhnIA4PqsdtKssXMcgFKZlgsUXJNuDE9e/+eWt36O5/+5fXhpW+VPvtz+T33Dd1rdsE="
        ),
    },
    "moon": {
        16: (
            "eNpjYGBgYGZAAUwMrK4ejIwwLjND6PU/lkBRGLf4//9OuB5mBuv/v/+aMyL42////SEDV84g+PH//9/KCL4GkPs/mJEFxpf5"
            "CeTvZ2CFKmBkvvL3z5//JQwMLCwgIRaGnP8///3538YHlWdi2fP/9+/f/+9Na3QEmcrIyLf6PxjslWcCORqIPeYeOzbbBcwE"
            "CUC9guQlFkZGFoiLAS5dOMs="
        ),
        24: (
            "eNqFkrFKA0EQhmdm14iCiFdGtBFB0lr5AAm+gLG3t1fwAQQlha02FjbmBbSzMIV1tFKwUvEFEi97N797dxizq5Cfbfab5Z/h"
            "nyWqxMYy/ZWh/8RMc63jbZIQ++v+M56WJHRiSm6AwXpkxjL/gIFexz0MnSPNsMs2wpvIFNqIulq6gFMMl0POZF+QK9xayIVW"
            "hlDkaLIJeQOeO5ySDfnqV/n+Y0Ek8J959RQZzqjGwZyX6lAU9kgmMjW0hYJrjoMybx4XrjAqCor7naSKscpnsY+Rllb4vLs9"
            "mZWfkeo9D51zaQo8brCMZ60dvaPU26EQTy4maXe63U47oSCO3wxMtH3/H4w/TFP0DVsLfUc="
        ),
    },
    "sun": {
        16: (
            "eNpNTzEOgzAMvIRkgbBQlX6ACirRBb4VvsMaJiTGDmVh6gP4CywMCEQdQFVPsnWWzvYdAAdAGFDjOMAdtCXEOXoZKfoGArG0"
            "4nwruEwjyYs5oRUOXQOuAuu0vSAE4JtxMOrgBGY2QrXza/16eNOyrsuk7qa8/M3u8/O+7aJq1zNmub2hzDAan5471qTuGJQL"
            "1Hp/n8zkJ0rJz5bbLDImq01PNPPOPAJlC+cXjyoIcQT/AgrjNeA="
        ),
        24: (
            "eNp9UTGOwkAMHHsTiERQqICGz6RPBa+JRHEVh3gAz0h/VYAEJN5ARQkPQEoEvt0suRyncN6VbI1mvWMP8E+Qud4yflYNbM5A"
            "rnVZhwsmBI+zxhuQO+uDD4afJzBpM1dsmnDvKNsJswIU8ySVvcdUdfdzCclwoGgmu/6zGWMU6hQtFpFO0yHYqjFUHqeiIx0T"
            "fili18mkKMtCMse1bDjdrqsQSWH4hURQFv+4XL6A1b00eHlfgZLTKW7Bkd1un219/CDw3v9rdVKt02gmOxhjOG3mCkc/c/V3"
            "MqNKHlMouV/NReztJW32tpVjr9obq/nG7BlJXq37sO5wY5lmnB+Bfq1NevURVxn88dG6HS+9V9/b4hviZXUK"
        ),
    },
    "import": {
        16: (
            "eNpjYMAKotKZkXiMDI/+swFJBP/8ayQ+IyvL5fdcLExIOs6/gzOZGDyWz3n3c94yTwaQCiZWJuFL/////X9VBMiEmCZ099/f"
            "R6JgaQarHEZmBuPf/60ZmBlzrBgYev+zMrIxpOQxsDGy/u9lYGj6DLeH6XMTA0PLZw4WVhY2NiDB8bmFgaH2/5fvUPDlfy0D"
            "g1RFcwsUNFdIYXgUACRUN3w="
        ),
        24: (
            "eNqNkrFKA0EQhv+dHTBNCgvjM1ikExtt9NA3sJLjJAGLBM5AQF/A3sr6UkkgdRKx9iHESnwKyR75ndN4xotIvmZ3P2aW+ZcF"
            "vnGqgrUR7AwGB/BV73FCXkBX/WEIyV/+iDxf1zvd0GOyrTV11Y5d8rQ6Y/M67d2R973LqybKdE4az1zw0hC31LD1GmbkLLxt"
            "l+XensVj7z2fz/Owb1vRn9SKM4bAdjmooJtFVqS4IW9t8YiyLsRjyr4dneLhCTa9os8pvMcwdIpu5+qbcMWNnTAs/IipxTSs"
            "1qhpytGXb/2O2Vr4PIuTuCSJs/zTj7nCGF4QTR4rTCL88wPESwW7BB+g8XgE"
        ),
    },
    "export": {
        16: (
            "eNpdjjEOglAMhv+W94QzMHkOFkcXvQm7LCxA4sRNTDyEgyYOxncDZ2MYHtEFUx/4wMQvaZumf/8W6CGA8SPAYunSCCN+tPNJ"
            "QRQcRM663xrGaifvTvaa6bu8MsdndzLr0UID12Yog9oFmSZ0YuUtCZf7zNslKbtLN3E9pwlQiyamzVYRaamBwk6fsi2AykZK"
            "q7BPka2AXNqXp5UciLOy8pRZjH8+ijE3KA=="
        ),
        24: (
            "eNptkTFuwkAQRb93Vg4XSJFbpIK0ibkAUqRUjiPTgUTDKbgArVsiLDqDFClSpNTp6dLkCikAWz8DJmB7ebJm7b/r8fMucMLz"
            "cAlzuBwsJlMtbvxIPjsTgtvfPN909KbW27v+ZlHw56b2DTV554bc8sNDxUr8Vx5JfVMxbGfp4pP8WqRZu2nbIZ8cTfGlS8Zy"
            "JY7oA/lS9Rdr6rmxUl1/XxTReb3BMAm0CrR/X3ODIBnCCFYc66Pgbr3u6WAx5goimO0G5evl/lsMdrN9PufItqwisq8tO+K8"
            "zOO6cnzM8ySMwhNRmOSHPKNDBlGt5VuDZXDxpP//TEwDbYI/efZ3zg=="
        ),
    },
    "pencil": {
        16: (
            "eNpjYIABRmYGZMDIwMCExGViEDBnYEbicuz94wJXAeTu/P/nWxAjE4L76/f/fIgOCPfP/2yIehg3h4EFzGVihXJZwfYyMh/9"
            "/xPOZWDk1p3w/xecy8xo89qg7X8mlAu0YMn/b1p2CLeqvp5rw4PkUgVFsCokwIzMAwDpjCz2"
        ),
        24: (
            "eNpjYCAOMOISxirBxMDOwIQpw8wgfKGRgYURQ1j0/P//NUBdmMK//vxvQZUAC//+///H/wwgG0P49//DMkhWMzHwnYYIH+Vj"
            "QBE+ChdmIluY+wgWYUYGwfNYhBkY2ZlX/f+FIczM0NXOsOT/d3TVjFxP/pczzP9/GEWYgYUh4u/X/50M1cKowcLEcOD//9sd"
            "XGhRxcxg+39HGFAULdSZGBwtwNLYYo+ZEasoNrUAaF9jPw=="
        ),
    },
    "folder": {
        16: (
            "eNpjYEADzCxAwIwuygRnxTa2trT6M7CyQNWd/P/566//PnD5o7tZOLgP3e6aOWPG9EkZQPk9QM0CmldevXz1/P8pIH8vIwsj"
            "VO3OYyA+AzMDIyPYjr0ngfx9zGzMYEews+wD8k/tQLhiB1D/0UsBwYFgEBxw6SjQjP9IYCcDg6y6ChyoyzJgACYUwAAAnSg6"
            "JA=="
        ),
        24: (
            "eNpjYKAWYIIAZkbilMvu3btz584dOxexMTIxMEIBUFzzPxQsZkAxSe3Px/TY+NjC7/97mKF2gNWr/X8L5iX/X3vwKgTcuKEI"
            "En8nysLKwsJgz/sXZuR/DbC4IMhkJgZWGwcgcHTw+fBXDSHOwAyzkeXtf2RxoAwIsDCLvEMThziGQZCQONg9MMDKIgoVf4se"
            "NBB7/3wqzcnNgYPcnNJPf9SQwgcZaDIwSK9btwoNrFsnjScCmLEA0mMdAOcse6M="
        ),
    },
}
APP_ICON_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAJxUlEQVR42u2bf4xcVRXHP+fe++bNzM52d7vSUBsqLViNLQYo"
    "WpMGi0sN0UYiYGsb0fojKjHYooKQaLL2HyMVtBY1aKJSUSlsAiKKvwulggHkh1IR22orWIFtt93tdmd25r17j3/M7ILQ3e52"
    "Z3RaPMnL/PHmze75nu/93nPuO0c4knV3G9Z9QUEUoO3qb3aphgsVv1gCc0DbAUtzmQfpV8Nuwd4vYn4ycO0ntlRvqdD9BWHd"
    "uvDSh+RlP7P8NkvPCg/QevXGSwW5HGWRuAgNHrwHDTSliQFrEWPRNAHhQUW/Pnjtmh+81LcjA9Dd7Vi3Lm1dc+1rJdtyo2Qy"
    "XfgUTcpVhFUEQY4IXHOYoiiiCliJYrAOrVS26PDQZYMbr9454uPLAajdaPv0dedrlLtVnOvU4VIKGATD8WhKAIJkc07TtE+S"
    "0nsHvnLlb18MQhWA5cstPT2+7Yovd2k2fzeqMWmSIuI4EUw1xUUOkbIMF985sOGqLSM+S1Xw1mnbZzaeqlYeRaSdNPGIWE4k"
    "U/W4yKLaL17PHrh+zR66u8XUbqL4TRJl2muRP7GcBxCxpEkqUaZd8ZtQfUEDpn1mw0rJt9yixcNNT3uLIqKoCgqIKAIEFcJE"
    "tFk1lXzBaXFo1aHrr9gsLL/Nts7e+7CJ4zO1UglNuL8DYFAUOByyeLUY8VgCiVrAEJsKeVMhqKDjA+ElkzGhXH588OlZb3Jt"
    "s/eeq9adpZWyQnNS30pgKMSIQlfhryxt/Suvi58nJwkHfAuPl2Zx9+B8nijNomCHcYTx2GC1Ulax7qy22XvPdQEuNi5CK2lT"
    "Rt9KoN/nODO7l/WvvoOuwg6MpKCmuoJFWdnxIJ/3v+SmA4vofn4ZxRCRlXQ8EIK4yAafXuxAFmvw1JKcpnN+wOe4oPAUt7zm"
    "u7TbIodDnqA18RJAQQEngctn/JY35f/BJXs+ygGfJx4LBBXR4AFZbIA5eE+zJTsGpRgyLMg+y49e8z1aTIVDvgVDwEnASsBS"
    "/XQSUKA/aWNRyy42zb65KoxjRVQweA8wxwi0NWtuH9Rw7cw76XBDFEOMEz/2LgdkJGUgncb507bzsc77OeRzOBnDNw0ItDVl"
    "mmtQDoeYt7TsZmnhKYZ8jmgc51+6bFIf85HpD9BmS6Q6jnuCacoc34iSqqOrsANnKniVSYFX1oh5cS8Lsv+iGDIYdJzvN2UN"
    "A0LgtZleYPLaHFTImIS5mf2kajBynAFQpaeSM+kUKm8lZ5KjPt+UAAigatmXFmoF/rH4b9iXtiLoSNp/nDEA5ZHSKccU/0g8"
    "B30LT5ZPJjbJuDVCUwLgVcibMr8afD29STuxSY+W349aqoasLXPf4dPZWT6JnEnGfbZJRVDImpR/VDq5Yf8SYluqFT1HET8E"
    "J4FyiFi/bymWgOpxqAEjkZxmS1y373zu6j+L9miAVC3+CP+y1r5vUPJuiGuefTcPDM2lYMtHLZHd5PZnwYg0mP5hVLQExRJ4"
    "/9Or+YbP8r7pD4JaSiGDR1AVRJRIPC22RCnErH1mFTf0LaHdFvF69Pi6iR+oCEOVhCRJGwpASzYm4ww+KIoQiSfFsPqZD3D3"
    "4Hw+3vk7zszuZZodrp56qqHXF7h34I18dV8XDxVPpd0WJ3Y4Asi0KzfoRCI/nKQsPm0W58yeiaoidWVCtaRLQ2DzI0/x3OAQ"
    "bbmY1IdRJgjQ73PEJmVe3MucTB85qXDAt7CzPIM9lelE4inY8oQiPykGGBGGyxXeteB01p63sKEMWL1oAatuuos//2s/nYUc"
    "iQ8o1eOvDlckqLCjPIPtwzNRFYwoWUnpcEVUZVLOT04Ea0sgDYHhNCUNoe5X4gNnvPoktq5dxTvmz6XvUBFnzCiZvRoUIScJ"
    "7bZEhyvSZoaJJMWrmTDtj3kXMCI4Yxp2Rba69jtbcvz0sku4/G0LOXC4CMJ/iG+gGmmvpiqGUzjJabpt0BohaNWlG5Yv5Wsr"
    "llIsp1S8xzageG3SclhABB8Ca5Ys5I6PXUQ+ijhcruCsOfEBGCmIrDGkIbBs/lzuWbuSeTM6OHC4RFRHEJr+paergbBg5qvG"
    "FMemACCo1pIX8CEQVOsKwkTE8X8GgKpiRLBGRqlrRNA6gtAocXT1cF5E+Mvzfaz/9UPs2X+QeSd3cvXbFzG3s72uWaMRGWXY"
    "miULOe1VHXzw5rsZGC7Tms2MZo7/NQYEVRBhR+9Bur62mZse+CMP7HmWb299lPM33soz/YPV0706MmE8cTyW5TBlAATYuPUR"
    "nusfZEZ7K/lMxIyOaezpPcCN2x5HhLoCcCRxvGfNSi4843QS7yfNNjPl/Rr42/5+XMaReE9QJfEBm3Hs2n+wFjVp2A5RTj0n"
    "FfJ8a9UFTMvGpGFyCfHUlwBwziknkw5XiKzFGkNkDH444c2zZ452LjXk0CQEYmd57J+9dG3cTH+pjDNmUn/NTe3lZVXp15x3"
    "Nr948u/84e97kcihScJb3zCHjy5+I6qKFVPnbhcIGnDGcOefdvHhH/6cwXKFlkw06eXmptZ1UgXgpEKe36x5L9/9/RPseK6P"
    "BbNm8KG3LCCfiajpJPXMN0QEK4brtzzMNXduJXaOQhzhg/73t8EqCNCWjfnU2855+RueOjrvg2KNkIbAJ3t+w433PUZbSw6p"
    "3fuf5AG1owJUFf8i+lkxdXU+DVXK9w4WufT7P+XXT+5meiFfzTqnIqT1a8ISXIMOTEec/+PeXlZ+7y6eer6PztY8iZ/6a33X"
    "3K19Rxa76S25ujjf1NVgNcusZn3Xb3mY93znx5RTTyGOjinlPa4Y0AixO24AaJTY1QWA6prU0av+a14bJnZjA6CEifYJZVy1"
    "zs9Y26h+3oaJ3Vjt9E5hQMR0jNcp5lXJxxk2Pbide3c+04A3Qy/Qf9uufxJU6y52R5ouUQ0DDtiNtR0kYUwmqCqRM+zsPcj2"
    "Z/c39CC0Nc4gYuoudi8bpHDWEMJuB3q/GHu2SkXH66dRhThy5DKu4TuAqtLg/iMVY1Eq9zsDt2uafHIiOUE13eVEMKNpgoHb"
    "zcDTs7apTx+TTFwbPTvhzUsmRn362MDTs7YZelZ4QdZjI2k895oiv1ZsJIKsp2eFt3R3m/IXr9ke/+y+Lsnm59RGZswJ6nwq"
    "2bzT0tC2Q9ddcSWMtMqKINjVmlT6cZFD1Z+Azntc5DSp9At29Uit/oofm6syoKfH093tBjZctUUqpWUgfZLNO5S0NnzIcTs4"
    "qaSSzTuQPqmUlg1suGoL3d2Onh7Pf4zIbN0a6O525S997m+ZhUvuwNj5ks2eJkaEkI6Mzo5wptlHZwNgJBOLZGKjSbJFh4cu"
    "OrThs38Ye3SW/w9P80ocn/835VdnC4YtbSsAAAAASUVORK5CYII="
)
# --- END GENERATED ICON DATA ---


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """Prefer the folder next to the exe (portable); fall back if read-only."""
    base = app_dir()
    probe = os.path.join(base, ".write_test_%d" % os.getpid())
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return base
    except OSError:
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(root, "GitHubReleaseTracker")
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError:
            return base


_DATA_DIR = data_dir()
DATA_FILE = os.path.join(_DATA_DIR, "projects.json")
HASH_CACHE_FILE = os.path.join(_DATA_DIR, "hash_cache.json")


# --------------------------------------------------------------------------
# GitHub API helpers
# --------------------------------------------------------------------------
class HostError(Exception):
    """A request to a code host failed. The message is meant for the user."""


GitHubError = HostError   # the name used before other hosts were supported


class NotFoundError(HostError):
    pass


class RateLimitError(HostError):
    pass


class NetworkError(HostError):
    """The host could not be reached: no connection, name lookup failed, timeout, TLS."""


# Remaining API calls reported by the last response (None = unknown).
last_rate_remaining = None
# Epoch seconds until which API calls fail fast, after GitHub said the limit is used up.
api_blocked_until = 0


def clear_api_block():
    global api_blocked_until
    api_blocked_until = 0


# ---- limits for requests that run at the same time ---------------------------------------------
_gates, _gates_lock = {}, threading.Lock()
host_down_until = {}      # host -> epoch seconds until which calls fail fast: it did not answer


def host_gate(host):
    """A semaphore that lets only a few requests to one host run at the same time."""
    with _gates_lock:
        gate = _gates.get(host)
        if gate is None:
            gate = _gates[host] = threading.BoundedSemaphore(HOST_PARALLEL_BIG.get(host, HOST_PARALLEL))
    return gate


def check_host_up(host):
    """Fail at once while a host is marked down, instead of waiting for another timeout."""
    until = host_down_until.get(host, 0)
    if time.time() < until:
        raise NetworkError("%s did not answer a moment ago. Try again in %d seconds."
                           % (host, int(until - time.time()) + 1))


def mark_host_down(host):
    host_down_until[host] = time.time() + HOST_DOWN_SECONDS


def mark_host_up(host):
    host_down_until.pop(host, None)


def clear_host_down(*hosts):
    """Forget "did not answer" marks (all, or those hosts): a click by the user earns a new try."""
    for host in (hosts or list(host_down_until)):
        host_down_until.pop(host, None)


def spawn(fn, *args):
    """Run fn(*args) in a daemon thread and return a Future for the result.

    A daemon thread never delays closing the app, unlike a ThreadPoolExecutor worker,
    which Python waits for at exit.
    """
    fut = concurrent.futures.Future()

    def target():
        try:
            fut.set_result(fn(*args))
        except BaseException as e:  # noqa: BLE001 - handed to whoever calls fut.result()
            fut.set_exception(e)
    threading.Thread(target=target, daemon=True).start()
    return fut


def _read_body(resp, limit=MAX_JSON_BYTES, host="The server"):
    """The body of a response, unpacked when the server sent it gzip-compressed.

    Raises HostError if the body (before or after unpacking) is larger than limit.
    """
    raw = resp.read(limit + 1)
    if len(raw) > limit:
        raise HostError("%s sent more data than expected." % host)
    headers = getattr(resp, "headers", None)
    if headers is not None and (headers.get("Content-Encoding") or "").strip().lower() in ("gzip", "x-gzip"):
        unpacker = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            raw = unpacker.decompress(raw, limit + 1)
        except zlib.error:
            raise HostError("%s sent damaged data." % host)
        if len(raw) > limit or unpacker.unconsumed_tail:
            raise HostError("%s sent more data than expected." % host)
    return raw


def api_get(path, token=""):
    global last_rate_remaining, api_blocked_until
    if time.time() < api_blocked_until:
        raise RateLimitError("GitHub API rate limit reached. Resets at " +
                             datetime.fromtimestamp(api_blocked_until).strftime("%H:%M") +
                             ". Add a token in Settings for a higher limit.")
    check_host_up("api.github.com")
    headers = {
        "Accept": "application/vnd.github+json",
        "Accept-Encoding": "gzip",
        "User-Agent": "GitHubReleaseTracker",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + path, headers=headers)
    try:
        with host_gate("api.github.com"):
            with urllib.request.urlopen(req, timeout=15) as resp:
                remaining = resp.headers.get("X-RateLimit-Remaining")
                if remaining is not None and remaining.isdigit():
                    last_rate_remaining = int(remaining)
                body = _read_body(resp, MAX_JSON_BYTES, "api.github.com")
        mark_host_up("api.github.com")
        return json.loads(body.decode("utf-8-sig"))
    except urllib.error.HTTPError as e:
        remaining = e.headers.get("X-RateLimit-Remaining") if e.headers else None
        if e.code in (403, 429) and remaining == "0":
            reset = e.headers.get("X-RateLimit-Reset", "")
            when = ""
            if reset.isdigit():
                when = " Resets at " + datetime.fromtimestamp(int(reset)).strftime("%H:%M") + "."
                # Cap at one hour, so a wrong PC clock cannot block the API for long.
                api_blocked_until = min(int(reset), time.time() + 3600)
            last_rate_remaining = 0
            raise RateLimitError("GitHub API rate limit reached." + when +
                                 " Add a token in Settings for a higher limit.")
        if e.code == 404:
            raise NotFoundError("Not found (wrong name, or a private repository).")
        if e.code == 401:
            raise GitHubError("GitHub rejected the token (401). Check it in Settings.")
        raise GitHubError("GitHub returned HTTP %d." % e.code)
    except urllib.error.URLError as e:
        mark_host_down("api.github.com")
        raise NetworkError("Network error: %s" % e.reason)
    except (TimeoutError, OSError, http.client.HTTPException) as e:
        mark_host_down("api.github.com")
        raise NetworkError("Network error: %s" % e)
    except ValueError:
        raise GitHubError("Unexpected response from GitHub.")


def parse_repo(text):
    """Accept https://github.com/owner/repo[/...] or owner/repo."""
    text = (text or "").strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", text)
    if not m:
        m = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$", text)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not repo:
        return None
    return owner, repo


def fetch_repo_info(owner, repo, token=""):
    d = api_get("/repos/%s/%s" % (owner, repo), token)
    full = d.get("full_name") or "%s/%s" % (owner, repo)
    real_owner, real_repo = full.split("/", 1)
    return {
        "owner": real_owner,
        "repo": real_repo,
        "title": d.get("name") or real_repo,
        "description": d.get("description") or "",
        "html_url": d.get("html_url") or "https://github.com/" + full,
    }


def _release_dict(r):
    return {
        "id": r.get("id"),
        "tag": r.get("tag_name") or "",
        "name": r.get("name") or "",
        "published_at": r.get("published_at") or r.get("created_at") or "",
        "url": r.get("html_url") or "",
        "prerelease": bool(r.get("prerelease")),
        "source": "release",
    }


def _unique_tags(tags):
    """Tag names in the given order, without blanks or repeats, capped at MAX_HISTORY."""
    seen, out = set(), []
    for t in tags:
        if isinstance(t, str) and t.strip() and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:MAX_HISTORY]


def _digest_hex(value):
    """"sha256:<64 hex digits>" -> the lowercase hex digits; "" for anything else.

    GitHub lists a digest for each release file it stores. It can be missing
    (null) for older files, and only SHA-256 is accepted here.
    """
    if isinstance(value, str):
        algo, _, digits = value.partition(":")
        digits = digits.strip().lower()
        if algo.strip().lower() == "sha256" and re.fullmatch(r"[0-9a-f]{64}", digits):
            return digits
    return ""


def _assets_of(r):
    """[[file name, size in bytes, SHA-256 hex or ""], ...] for the files of one API release."""
    assets = r.get("assets")
    if not isinstance(assets, list):
        return []
    out = []
    for a in assets[:MAX_ASSETS_PER_RELEASE]:
        if not isinstance(a, dict) or a.get("state", "uploaded") != "uploaded":
            continue   # skip anything that is not a finished upload
        name, size = a.get("name"), a.get("size")
        if isinstance(name, str) and name and isinstance(size, int) and not isinstance(size, bool) and size >= 0:
            out.append([name[:200], size, _digest_hex(a.get("digest"))])
    return out


def _release_pool(owner, repo, token):
    """Recent non-draft releases, newest first, pre-releases included. [] if none.

    Each release dict also has "_assets": its files (see _assets_of). Remove it
    with _strip() before a release is stored.
    """
    try:
        data = api_get("/repos/%s/%s/releases?per_page=30" % (owner, repo), token)
    except NotFoundError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for r in data:
        if isinstance(r, dict) and not r.get("draft"):
            d = _release_dict(r)
            d["_assets"] = _assets_of(r)
            out.append(d)
    return out


def _strip(rel):
    """A copy of a pool release without its "_assets" field."""
    return {k: v for k, v in rel.items() if k != "_assets"}


def _pool_assets(pool):
    return {r["tag"]: r["_assets"] for r in pool if r["tag"]}


def _newest_tag(owner, repo, token):
    """First tag GitHub returns. Used only when no GitHub Release exists at all.

    Caveat: the tags endpoint does not guarantee newest-first ordering, and
    tags carry no publish date.
    """
    try:
        data = api_get("/repos/%s/%s/tags?per_page=30" % (owner, repo), token)
    except NotFoundError:
        return None
    if not data:
        return None
    t = data[0]
    name = t.get("name") or ""
    sha = (t.get("commit") or {}).get("sha") or name
    return {
        "id": sha,
        "tag": name,
        "name": "",
        "published_at": "",
        "url": "https://github.com/%s/%s/releases/tag/%s" % (owner, repo, urllib.parse.quote(name, safe="")),
        "prerelease": False,
        "source": "tag",
        "history": _unique_tags([name] + [x.get("name") for x in data if isinstance(x, dict)]),
    }


def fetch_latest_release(owner, repo, token="", include_prereleases=False, pool_future=None):
    """Return the latest version info dict, or None if the project has nothing.

    The dict also carries a "history" list (recent release tags, newest first),
    "pre_tags", "pre_exact" and "assets" (the files of each recent release with
    their SHA-256 digests), used to compare releases with the download folder.

    Order of preference:
      1. newest stable GitHub Release (or newest incl. pre-releases if enabled)
      2. newest pre-release, when no stable release exists
      3. newest git tag, when no GitHub Release exists at all
    """
    latest, latest_assets = None, []
    if not include_prereleases:
        try:
            raw = api_get("/repos/%s/%s/releases/latest" % (owner, repo), token)
            latest, latest_assets = _release_dict(raw), _assets_of(raw)
        except NotFoundError:
            pass  # no stable release; fall through to pre-releases / tags
    try:
        pool = pool_future.result() if pool_future is not None else _release_pool(owner, repo, token)
    except GitHubError:
        if latest is None:
            raise
        pool = []  # the history is a bonus here: keep the latest release we already have
    if latest is None and pool:
        latest = _strip(pool[0])
    if latest is None:
        return _newest_tag(owner, repo, token)
    shown = [r for r in pool if include_prereleases or not r["prerelease"]]
    latest["history"] = _unique_tags([latest["tag"]] + [r["tag"] for r in shown])
    latest["pre_tags"] = _unique_tags([r["tag"] for r in [latest] + shown if r["prerelease"]])
    latest["pre_exact"] = True   # the API reports the pre-release flag itself
    assets = _pool_assets(pool)
    if latest["tag"]:
        assets.setdefault(latest["tag"], latest_assets)
    latest["assets"] = assets
    return latest


FEED_NS = "{http://www.w3.org/2005/Atom}"


def _parse_feed_entry(entry, owner, repo):
    """One <entry> of releases.atom as a release dict, or None if it is unusable."""
    entry_id = (entry.findtext(FEED_NS + "id") or "").strip()
    title = (entry.findtext(FEED_NS + "title") or "").strip()
    updated = (entry.findtext(FEED_NS + "updated") or "").strip()
    href = ""
    for link in entry.findall(FEED_NS + "link"):
        if link.get("rel", "alternate") == "alternate":
            href = link.get("href") or ""
            break
    marker = "/releases/tag/"
    if marker in href:
        tag = urllib.parse.unquote(href.split(marker, 1)[1])
    else:
        m = re.search(r"Repository/\d+/(.+)$", entry_id)
        tag = m.group(1) if m else ""
    if not (entry_id or tag):
        return None
    return {
        "id": entry_id or tag,
        "tag": tag,
        "name": title,
        "published_at": updated,
        "url": href or "https://github.com/%s/%s/releases" % (owner, repo),
        "prerelease": False,  # not reported by the feed
        "source": "feed",
    }


def fetch_latest_from_feed(owner, repo):
    """Newest release from the public releases.atom feed (no token, no API quota).

    The feed lists the most recent published releases (about 10), pre-releases
    included, newest first. It does not say which entries are pre-releases.
    The returned dict also has a "history" list with every tag in the feed.
    Returns None if the feed is empty.
    """
    check_host_up("github.com")
    url = "https://github.com/%s/%s/releases.atom" % (owner, repo)
    req = urllib.request.Request(url, headers={
        "User-Agent": "GitHubReleaseTracker",
        "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        "Accept-Encoding": "gzip",
    })
    try:
        with host_gate("github.com"):
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = _read_body(resp, 4 * 1024 * 1024, "github.com")
        mark_host_up("github.com")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFoundError("Not found (wrong name, or a private repository).")
        if e.code == 429:
            raise GitHubError("GitHub is rate-limiting the release feed (429). Try again later.")
        raise GitHubError("Release feed returned HTTP %d." % e.code)
    except urllib.error.URLError as e:
        mark_host_down("github.com")
        raise NetworkError("Network error: %s" % e.reason)
    except (TimeoutError, OSError, http.client.HTTPException) as e:
        mark_host_down("github.com")
        raise NetworkError("Network error: %s" % e)
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise GitHubError("Release feed was not valid XML.")
    entries = root.findall(FEED_NS + "entry")
    if not entries:
        return None
    first = _parse_feed_entry(entries[0], owner, repo)
    if first is None:
        return None
    rest = [_parse_feed_entry(e, owner, repo) for e in entries[1:]]
    first["history"] = _unique_tags([first["tag"]] + [r["tag"] for r in rest if r])
    return first


def _release_is_young(published_at):
    """True if a release was published less than ASSET_REFRESH_HOURS ago (UTC timestamp)."""
    try:
        t = datetime.strptime((published_at or "")[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    age = datetime.now(timezone.utc).replace(tzinfo=None) - t
    return age.total_seconds() < ASSET_REFRESH_HOURS * 3600


def _flag_prereleases(rel, owner, repo, token, known, pool_future=None):
    """Add "pre_tags", "pre_exact" and "assets" to a feed result, using the GitHub API.

    The feed marks neither pre-releases nor release files, so the GitHub API is
    asked (one call for the recent releases, including each file's SHA-256).
    The call is skipped when nothing could have changed: no new release tag, no
    known pre-release that might have been promoted, the flags came from the API
    last time, the files of the newest releases are already stored, and the newest
    release is older than ASSET_REFRESH_HOURS (a young release may still be getting
    files uploaded). If the API is unavailable (rate limit, network), tag names such
    as "-beta" or "-rc1" are used as a guess, and "pre_exact" is False so the next
    check tries the API again.
    known = {"history", "pre_tags", "pre_exact", "assets"} from the last check.
    pool_future = the release list when the caller already started reading it.
    """
    tags = rel["history"]
    known = known or {}
    k_hist, k_pre = set(known.get("history") or []), set(known.get("pre_tags") or [])
    k_assets = known.get("assets") or {}
    nothing_new = (bool(known.get("pre_exact"))
                   and all(t in k_hist for t in tags)
                   and not any(t in k_pre for t in tags)
                   and all(t in k_assets for t in tags[:MAX_ASSET_RELEASES])
                   and not _release_is_young(rel.get("published_at")))
    if nothing_new:
        rel["pre_tags"], rel["pre_exact"], rel["assets"] = [], True, {}
        return
    try:
        pool = pool_future.result() if pool_future is not None else _release_pool(owner, repo, token)
    except GitHubError:
        pool = []
    flags = {r["tag"]: r["prerelease"] for r in pool}
    rel["pre_tags"] = [t for t in tags if flags.get(t, looks_prerelease(t))]
    rel["pre_exact"] = all(t in flags for t in tags)
    rel["assets"] = _pool_assets(pool)


def get_latest(owner, repo, token="", include_prereleases=True, known=None, kind="github", base=GITHUB_BASE):
    """Feed first (free, no quota); GitHub API as fallback.

    Stable-only mode needs the API, because the feed does not mark pre-releases.
    The result carries "history", "pre_tags", "pre_exact" and "assets" (see apply_result).
    known = what the previous check stored (see _flag_prereleases), to save API calls.
    kind and base name the host: GitLab, Gitea and Forgejo are read through their API.
    """
    if kind != "github":
        return fetch_latest_forge(kind, base, owner, repo, token, include_prereleases, known)
    pool_future = None
    if include_prereleases:
        if not (known or {}).get("pre_exact"):
            # The API call below cannot be skipped (nothing is known yet), so it starts
            # now and runs while the feed is being read: one wait instead of two.
            pool_future = spawn(_release_pool, owner, repo, token)
        rel = None
        try:
            rel = fetch_latest_from_feed(owner, repo)
        except GitHubError:
            pass  # feed unavailable or repo has no releases: try the API
        if rel:
            _flag_prereleases(rel, owner, repo, token, known, pool_future)
            return rel
    return fetch_latest_release(owner, repo, token, include_prereleases, pool_future)


# --------------------------------------------------------------------------
# Other hosts: GitLab, Gitea and Forgejo (public API)
# --------------------------------------------------------------------------
# Hosts whose kind is known from the name. Any other host is probed (see resolve_project).
KNOWN_HOSTS = {
    "github.com": "github", "www.github.com": "github",
    "gitlab.com": "gitlab", "framagit.org": "gitlab", "salsa.debian.org": "gitlab",
    "invent.kde.org": "gitlab", "gitlab.gnome.org": "gitlab", "gitlab.freedesktop.org": "gitlab",
    "codeberg.org": "gitea", "gitea.com": "gitea",
}
# Words that start the part of an address after the project path: /owner/repo/releases/...
_URL_STOP = frozenset(("releases", "tags", "blob", "tree", "src", "raw", "issues", "pulls",
                       "merge_requests", "wiki", "wikis", "commit", "commits", "compare",
                       "actions", "activity", "branches", "pipelines", "packages"))


def host_of(base):
    """"https://Git.Example.org:3000" -> "git.example.org:3000"."""
    return urllib.parse.urlsplit(base or "").netloc.lower()


def host_path(base):
    """The address without "https://". It keeps the keys of different hosts apart."""
    return (base or "").split("://", 1)[-1].lower()


def clean_base(text):
    """"HTTPS://Git.Example.org/" -> "https://git.example.org"; "" if it is not a plain web address.

    Only http and https are accepted (never file: or ftp:), without user name, query
    or fragment, because the address can come from a file that was imported.
    """
    m = re.fullmatch(r"(https?)://([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?)"
                     r"((?:/[A-Za-z0-9_.~-]{1,100}){0,5})/?", (text or "").strip(), re.I)
    return "%s://%s%s" % (m.group(1).lower(), m.group(2).lower(), m.group(3)) if m else ""


def guess_kind(host):
    """"github", "gitlab" or "gitea" when the host name says so, else ""."""
    host = (host or "").lower().split(":")[0]
    if host in KNOWN_HOSTS:
        return KNOWN_HOSTS[host]
    label = host.split(".")[0]
    if label.startswith("gitlab"):
        return "gitlab"
    if label.startswith(("gitea", "forgejo", "codeberg")):
        return "gitea"
    return ""


def valid_ident(kind, owner, repo):
    """True for a safe owner (on GitLab: the group path) and project name."""
    if not (isinstance(owner, str) and isinstance(repo, str)):
        return False
    parts = owner.split("/") if kind == "gitlab" else [owner]
    return len(parts) <= 20 and all(NAME_RE.match(x) and x.strip(".") for x in parts + [repo])


MAX_ADD_AT_ONCE = 20   # addresses taken from one paste; the rest stay in the box


def split_project_refs(text):
    """Split pasted text into separate project addresses (spaces, new lines, commas, semicolons)."""
    return [t for t in re.split(r"[\s,;]+", text or "") if t]


def parse_project_ref(text, known=None):
    """Read a pasted project address. Returns candidates, best guess first; [] if unusable.

    A candidate is {"kind", "base", "owner", "repo"}. A GitHub address (or plain
    owner/repo) gives one candidate. So does a host that is known to be a GitLab or
    Gitea/Forgejo server: by its name (gitlab.com, codeberg.org, gitlab.example.org),
    by "/-/" in the address (GitLab only), or by known = {host: kind} taken from
    projects already in the list. Any other host gives two candidates that are tried
    in turn: Gitea/Forgejo first, then GitLab.
    """
    text = (text or "").strip()
    if not text or len(text) > 500:
        return []
    gh = parse_repo(text)
    if gh:
        return [{"kind": "github", "base": GITHUB_BASE, "owner": gh[0], "repo": gh[1]}]
    m = re.match(r"^git@([A-Za-z0-9.-]+):(.+)$", text)            # git@host:owner/repo.git
    if m:
        text = "https://%s/%s" % m.groups()
    m = re.match(r"^(?:(https?)://)?([A-Za-z0-9.-]+(?::\d{1,5})?)/(.+)$", text, re.I)
    if not m or not ("." in m.group(2) or m.group(2).lower().startswith("localhost")):
        return []
    scheme = (m.group(1) or "https").lower()
    base = clean_base("%s://%s" % (scheme, m.group(2)))
    if not base:
        return []
    host = host_of(base)
    path = urllib.parse.urlsplit("%s://%s/%s" % (scheme, host, m.group(3))).path
    segs = [urllib.parse.unquote(s) for s in path.split("/") if s]
    gitlab_only = "-" in segs                 # only GitLab has /group/project/-/releases
    if gitlab_only:
        segs = segs[:segs.index("-")]
    else:
        for i in range(2, len(segs)):
            if segs[i] in _URL_STOP:
                segs = segs[:i]
                break
    if segs and segs[-1].endswith(".git"):
        segs[-1] = segs[-1][:-4]
    if len(segs) < 2:
        return []
    kind = "gitlab" if gitlab_only else ((known or {}).get(host) or guess_kind(host))
    if kind == "github":
        return []                              # GitHub Enterprise servers are not supported
    cands = []

    def add(k, owner, repo):
        c = {"kind": k, "base": base, "owner": owner, "repo": repo}
        if valid_ident(k, owner, repo) and c not in cands:
            cands.append(c)

    if kind in ("gitea", ""):
        add("gitea", segs[0], segs[1])
    if kind in ("gitlab", ""):
        add("gitlab", "/".join(segs[:-1]), segs[-1])
    return cands


def _origin(url):
    s = urllib.parse.urlsplit(url)
    scheme = s.scheme.lower()
    try:
        port = s.port
    except ValueError:
        port = None
    return scheme, (s.hostname or "").lower(), port or (443 if scheme == "https" else 80)


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never pass an access token on to another site."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() not in ("http", "https"):
            return None
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _origin(new.full_url) != _origin(req.full_url):
            for name in ("Authorization", "Private-token"):
                new.remove_header(name)
        return new


_OPENER = urllib.request.build_opener(_SameOriginRedirect)
# host -> epoch seconds until which calls to that host fail fast, after it said "too many requests"
host_blocked_until = {}


def _retry_after(headers):
    value = (headers.get("Retry-After") or "").strip() if headers else ""
    seconds = int(value) if value.isdigit() else 60
    return max(30, min(seconds, 3600))     # an hour at most, so a wrong answer cannot block for long


def http_get(url, token="", scheme="gitea", limit=MAX_JSON_BYTES, timeout=15):
    """GET a web address and return the body as bytes.

    scheme "gitlab" sends the token as PRIVATE-TOKEN, anything else as
    "Authorization: token". Errors become HostError (NotFoundError for HTTP 404,
    RateLimitError for HTTP 429).
    """
    if urllib.parse.urlsplit(url).scheme.lower() not in ("http", "https"):
        raise HostError("Unsupported address: %s" % url[:80])
    host = urllib.parse.urlsplit(url).netloc.lower()
    until = host_blocked_until.get(host, 0)
    if time.time() < until:
        raise RateLimitError("%s is limiting requests. Try again after %s." % (
            host, datetime.fromtimestamp(until).strftime("%H:%M")))
    check_host_up(host)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain;q=0.9, */*;q=0.5",
               "Accept-Encoding": "gzip"}
    if token:
        if scheme == "gitlab":
            headers["PRIVATE-TOKEN"] = token
        else:
            headers["Authorization"] = "token " + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with host_gate(host):
            with _OPENER.open(req, timeout=timeout) as resp:
                body = _read_body(resp, limit, host)
        mark_host_up(host)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            host_blocked_until[host] = time.time() + _retry_after(e.headers)
            raise RateLimitError("%s is limiting requests (HTTP 429). Try again after %s." % (
                host, datetime.fromtimestamp(host_blocked_until[host]).strftime("%H:%M")))
        if e.code == 404:
            raise NotFoundError("Not found on %s (wrong name, or a private project)." % host)
        if e.code in (401, 403):
            raise HostError("%s refused access (HTTP %d). A private project needs an access token: "
                            "right-click the project and choose \"Set access token for this host\"."
                            % (host, e.code))
        raise HostError("%s returned HTTP %d." % (host, e.code))
    except urllib.error.URLError as e:
        mark_host_down(host)
        raise NetworkError("Network error: %s" % e.reason)
    except (TimeoutError, OSError, http.client.HTTPException) as e:
        mark_host_down(host)
        raise NetworkError("Network error: %s" % e)
    return body


def host_json(url, token="", scheme="gitea"):
    """GET a web address and decode the JSON answer."""
    body = http_get(url, token, scheme)
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (ValueError, RecursionError):   # includes UnicodeDecodeError
        raise HostError("%s did not answer with JSON. It may block automated requests, or it is not "
                        "a GitLab, Gitea or Forgejo server." % urllib.parse.urlsplit(url).netloc.lower())


def _q(text):
    return urllib.parse.quote(text, safe="")


def api_url(kind, base, path):
    return base + ("/api/v4" if kind == "gitlab" else "/api/v1") + path


def _project_api(kind, owner, repo):
    """API path of one project: GitLab takes the whole path as one encoded name."""
    if kind == "gitlab":
        return "/projects/" + _q("%s/%s" % (owner, repo))
    return "/repos/%s/%s" % (_q(owner), _q(repo))


def repo_url(base, owner, repo):
    return "%s/%s/%s" % (base, owner, repo)


def releases_url(kind, base, owner, repo):
    return repo_url(base, owner, repo) + ("/-/releases" if kind == "gitlab" else "/releases")


def release_url(kind, base, owner, repo, tag):
    if kind == "gitlab":
        return "%s/-/releases/%s" % (repo_url(base, owner, repo), _q(tag))
    return "%s/releases/tag/%s" % (repo_url(base, owner, repo), _q(tag))


def pick_token(settings, kind, base):
    """The access token for a host: the GitHub token, or the one saved for that host."""
    if kind == "github":
        return (settings.get("token") or "").strip()
    return ((settings.get("host_tokens") or {}).get(host_of(base)) or "").strip()


def fetch_project_info(kind, base, owner, repo, token=""):
    """Name, description and web address of a project, as stored in the list."""
    if kind == "github":
        info = fetch_repo_info(owner, repo, token)
        info.update(kind="github", base=GITHUB_BASE)
        return info
    d = host_json(api_url(kind, base, _project_api(kind, owner, repo)), token, kind)
    full = d.get("path_with_namespace" if kind == "gitlab" else "full_name") if isinstance(d, dict) else None
    if not (isinstance(full, str) and "/" in full):
        raise HostError("%s did not answer like a %s server." % (host_of(base), KIND_LABEL[kind]))
    real_owner, real_repo = full.rsplit("/", 1)
    if not valid_ident(kind, real_owner, real_repo):
        real_owner, real_repo = owner, repo
    link = d.get("web_url" if kind == "gitlab" else "html_url")
    return {
        "kind": kind, "base": base, "owner": real_owner, "repo": real_repo,
        "title": _s(d.get("name"), 200) or real_repo,
        "description": _s(d.get("description"), 500),
        "html_url": safe_web_url(link, base, repo_url(base, real_owner, real_repo)),
    }


def resolve_project(cands, token_for):
    """Find out which candidate (see parse_project_ref) exists. Returns its project info.

    token_for(kind, base) gives the access token to use. A GitHub project is also
    accepted when only the API is unavailable (rate limit): its feed is enough.
    """
    errors = []
    for c in cands:
        try:
            return fetch_project_info(c["kind"], c["base"], c["owner"], c["repo"],
                                      token_for(c["kind"], c["base"]))
        except NotFoundError as e:
            errors.append(e)
        except HostError as e:
            if c["kind"] == "github":
                return {"kind": "github", "base": GITHUB_BASE, "owner": c["owner"], "repo": c["repo"],
                        "title": c["repo"], "description": "",
                        "html_url": "%s/%s/%s" % (GITHUB_BASE, c["owner"], c["repo"])}
            if isinstance(e, NetworkError):
                raise       # the host cannot be reached: asking it again as another kind is pointless
            errors.append(e)
    if len(errors) == 1:
        raise errors[0]
    c = cands[0]
    raise HostError("Could not read %s/%s on %s as a Gitea/Forgejo or GitLab project. %s"
                    % (c["owner"], c["repo"], host_of(c["base"]), errors[0]))


def _file_name_from_url(url, fallback):
    """The file name at the end of a download address, or fallback when it has none."""
    name = urllib.parse.unquote(urllib.parse.urlsplit(url or "").path).rsplit("/", 1)[-1]
    return name if name and "." in name else fallback


def _forge_release(kind, r, base, owner, repo):
    """One release of a GitLab, Gitea or Forgejo API as a pool release, or None.

    Besides the usual fields it has "_files" (name, size or -1, download address of each
    file) and "_text" (the release notes). Drafts and upcoming releases are left out.
    """
    tag = r.get("tag_name")
    if not (isinstance(tag, str) and tag.strip()):
        return None
    files = []
    if kind == "gitea":
        if r.get("draft"):
            return None
        for a in (r.get("assets") if isinstance(r.get("assets"), list) else [])[:MAX_ASSETS_PER_RELEASE]:
            if isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"]:
                size = a.get("size")
                files.append({"name": a["name"][:200],
                              "size": size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else -1,
                              "url": a.get("browser_download_url") if isinstance(a.get("browser_download_url"), str) else ""})
        rid = r.get("id")
        rel = {"id": rid if isinstance(rid, int) and not isinstance(rid, bool) else tag,
               "tag": tag, "name": r.get("name") or "",
               "published_at": r.get("published_at") or r.get("created_at") or "",
               "url": r.get("html_url") or release_url(kind, base, owner, repo, tag),
               "prerelease": bool(r.get("prerelease")), "source": "release"}
        text = r.get("body")
    else:
        if r.get("upcoming_release"):
            return None
        assets = r.get("assets") if isinstance(r.get("assets"), dict) else {}
        for a in (assets.get("links") if isinstance(assets.get("links"), list) else [])[:MAX_ASSETS_PER_RELEASE]:
            if not isinstance(a, dict):
                continue
            url = a.get("direct_asset_url") or a.get("url") or ""
            name = _file_name_from_url(url, a.get("name") if isinstance(a.get("name"), str) else "")
            if name and isinstance(url, str):
                files.append({"name": name[:200], "size": -1, "url": url})   # GitLab gives no sizes
        links = r.get("_links") if isinstance(r.get("_links"), dict) else {}
        rel = {"id": tag, "tag": tag, "name": r.get("name") or "",
               "published_at": r.get("released_at") or r.get("created_at") or "",
               "url": links.get("self") or release_url(kind, base, owner, repo, tag),
               "prerelease": looks_prerelease(tag), "source": "release"}   # GitLab has no pre-release flag
        text = r.get("description")
    for key in ("name", "published_at", "url"):
        if not isinstance(rel[key], str):
            rel[key] = ""
    rel["_files"] = files
    rel["_text"] = text if isinstance(text, str) else ""
    return rel


def _forge_pool(kind, base, owner, repo, token):
    """Recent releases of a GitLab, Gitea or Forgejo project, newest first."""
    if kind == "gitea":
        path = _project_api(kind, owner, repo) + "/releases?limit=30&per_page=30"
    else:
        path = _project_api(kind, owner, repo) + "/releases?per_page=30"
    data = host_json(api_url(kind, base, path), token, kind)
    if not isinstance(data, list):
        raise HostError("%s sent an unexpected answer." % host_of(base))
    out = []
    for r in data:
        rel = _forge_release(kind, r, base, owner, repo) if isinstance(r, dict) else None
        if rel:
            out.append(rel)
    return out


def _forge_newest_tag(kind, base, owner, repo, token):
    """Newest tag, used when a project has tags but no releases. None if it has neither."""
    if kind == "gitea":
        path = _project_api(kind, owner, repo) + "/tags?limit=30&per_page=30"
    else:
        path = _project_api(kind, owner, repo) + "/repository/tags?per_page=30&order_by=updated&sort=desc"
    data = host_json(api_url(kind, base, path), token, kind)
    tags = [t for t in data if isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"]] \
        if isinstance(data, list) else []
    if not tags:
        return None
    first = tags[0]
    commit = first.get("commit") if isinstance(first.get("commit"), dict) else {}
    date = commit.get("created_at") or commit.get("created") or ""
    return {
        "id": commit.get("id") or commit.get("sha") or first["name"],
        "tag": first["name"],
        "name": "",
        "published_at": date if isinstance(date, str) else "",
        "url": release_url(kind, base, owner, repo, first["name"]),
        "prerelease": False,
        "source": "tag",
        "history": _unique_tags([t["name"] for t in tags]),
    }


_SIGNATURE_EXT = (".sig", ".asc", ".minisig", ".pem", ".gpg", ".sigstore", ".bundle", ".cert")


def is_checksum_name(name):
    """True for the name of a checksum file: SHA256SUMS, checksums.txt, app.zip.sha256, ..."""
    n = (name or "").casefold()
    if n.endswith(_SIGNATURE_EXT):
        return False
    return "sha256" in n or "sha-256" in n or bool(re.fullmatch(r"checksums?(?:\.txt)?", n))


def is_metadata_name(name):
    """A checksum or signature file: it says something about the release but is not the download."""
    return is_checksum_name(name) or (name or "").casefold().endswith(_SIGNATURE_EXT)


_HEX = r"([0-9a-fA-F]{64})"
_SUM_STD = re.compile(r"^" + _HEX + r"\s+\*?(.+)$")                           # <hash>  file
_SUM_BSD = re.compile(r"^SHA-?256\s*\((.+)\)\s*=\s*" + _HEX + r"$", re.I)       # SHA256 (file) = <hash>
_SUM_NAMED = re.compile(r"^(.+?)\s*[:=|]\s*" + _HEX + r"$")                    # file: <hash>, | file | <hash> |
_SUM_ONLY = re.compile(r"^" + _HEX + r"$")
_SUM_LABELS = ("sha256", "sha-256", "sha256sum", "hash", "checksum", "digest")


def parse_checksums(text, single_name=""):
    """{file name (casefolded): SHA-256 hex} from a checksum file or from release notes.

    Understands "<hash>  file" (what sha256sum writes), "SHA256 (file) = <hash>",
    "file: <hash>" and table rows such as "| file | <hash> |". A text that holds
    one bare hash belongs to single_name. Hashes of other lengths (MD5, SHA-1,
    SHA-512) are ignored.
    """
    out, bare = {}, []
    for raw in (text or "").splitlines()[:5000]:
        line = raw.strip().replace("`", "").strip("|- ").strip()
        if not line or len(line) > 1000:
            continue
        m = _SUM_STD.match(line)
        if m:
            digest, name = m.group(1), m.group(2)
        else:
            m = _SUM_BSD.match(line)
            if m:
                name, digest = m.group(1), m.group(2)
            else:
                m = _SUM_NAMED.match(line)
                if m:
                    name, digest = m.group(1), m.group(2)
                    if name.strip("*_ ").casefold() in _SUM_LABELS:
                        bare.append(digest.lower())      # "SHA256: <hash>" without a file name
                        continue
                else:
                    m = _SUM_ONLY.match(line)
                    if m:
                        bare.append(m.group(1).lower())
                    continue
        name = name.strip().strip("*| ").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if name:
            out.setdefault(name.casefold(), digest.lower())
    if not out and len(bare) == 1 and single_name:
        out[single_name.casefold()] = bare[0]
    return out


def _strip_sum_suffix(name):
    """"app.zip.sha256" -> "app.zip"."""
    return re.sub(r"\.sha-?256(?:sums?)?(?:\.txt)?$", "", name, flags=re.I)


def _fetch_text(url, kind, base, token):
    """A small text file of a release. The token goes only to the project's own host."""
    use = token if _origin(url) == _origin(base) else ""
    return http_get(url, use, kind, MAX_CHECKSUM_BYTES).decode("utf-8", "replace")


def _same_listing(listing, stored):
    """True if stored ([[name, size, digest], ...]) lists the same files as listing."""
    return (isinstance(stored, list)
            and all(isinstance(a, list) and len(a) == 3 for a in stored)
            and sorted((n, s) for n, s, _d in listing) == sorted((a[0], a[1]) for a in stored))


def forge_assets(rel, kind, base, token, stored=None):
    """[[file name, size or -1, SHA-256 hex or ""], ...] for one GitLab, Gitea or Forgejo release.

    The digests come from checksum files attached to the release and from checksum
    lines in the release notes. A release is read once: when stored (what the last
    check kept) lists the same files it is reused, unless the release is under a day
    old and may still be getting files.
    """
    listing = [[f["name"], f["size"], ""] for f in rel["_files"]]
    if _same_listing(listing, stored) and not _release_is_young(rel.get("published_at")):
        return stored
    sources = []
    sums = [f for f in rel["_files"] if is_checksum_name(f["name"]) and f["url"] and f["size"] <= MAX_CHECKSUM_BYTES]
    for f in sums[:MAX_CHECKSUM_FILES]:
        try:
            sources.append(parse_checksums(_fetch_text(f["url"], kind, base, token), _strip_sum_suffix(f["name"])))
        except RateLimitError:
            raise
        except HostError:
            continue        # a dead link or a timeout: this release has no digests for now
    sources.append(parse_checksums(rel.get("_text", "")[:200000]))
    digest_by_name = {}
    for table in sources:
        for k, v in table.items():
            digest_by_name.setdefault(k, v)
    for item in listing:
        item[2] = digest_by_name.get(item[0].casefold(), "")
    return listing


def fetch_latest_forge(kind, base, owner, repo, token="", include_prereleases=True, known=None):
    """Latest release of a GitLab, Gitea or Forgejo project, shaped like the GitHub result.

    The dict also carries "history", "pre_tags", "pre_exact" and "assets". With no
    release at all, the newest tag is used. Returns None if the project has neither.
    """
    pool = _forge_pool(kind, base, owner, repo, token)
    shown = [r for r in pool if include_prereleases or not r["prerelease"]]
    first = (shown or pool or [None])[0]
    if first is None:
        return _forge_newest_tag(kind, base, owner, repo, token)
    latest = {k: v for k, v in first.items() if not k.startswith("_")}
    latest["history"] = _unique_tags([latest["tag"]] + [r["tag"] for r in shown])
    latest["pre_tags"] = _unique_tags([r["tag"] for r in [first] + shown if r["prerelease"]])
    latest["pre_exact"] = True      # the host's flag, or (GitLab) the tag name: nothing better exists
    stored = (known or {}).get("assets") or {}
    by_tag = {r["tag"]: r for r in [first] + shown}
    latest["assets"] = {t: forge_assets(by_tag[t], kind, base, token, stored.get(t))
                        for t in latest["history"][:MAX_ASSET_RELEASES] if t in by_tag}
    return latest


def _round_robin(snapshot):
    """Indexes of snapshot items ordered so that different hosts alternate."""
    by_host = {}
    for i, item in enumerate(snapshot):
        by_host.setdefault(host_of(item[4]), []).append(i)
    lanes, order = list(by_host.values()), []
    while any(lanes):
        for lane in lanes:
            if lane:
                order.append(lane.pop(0))
    return order


def check_projects(snapshot, settings, progress=None, workers=CHECK_WORKERS):
    """Look for new releases of many projects at the same time (runs in a background thread).

    snapshot: [(key, owner, repo, kind, base, include_prereleases, known), ...]
    settings: {"token": ..., "host_tokens": {...}} (see pick_token)
    progress: function(done, total), called from the worker threads as projects finish.

    Returns [(key, latest or None, error text or None), ...] in snapshot order. How many
    requests reach one host at a time is limited by host_gate(). A host that says "too
    many requests" is not asked again in this run: its remaining projects get no entry,
    so they keep their state. A project that fails never stops the others.
    """
    total = len(snapshot)
    results = [None] * total
    todo = queue.Queue()
    for i in _round_robin(snapshot):
        todo.put(i)
    limited, lock, done = set(), threading.Lock(), [0]

    def worker():
        while True:
            try:
                i = todo.get_nowait()
            except queue.Empty:
                return
            key, owner, repo, kind, base, inc, known = snapshot[i]
            host = host_of(base)
            with lock:
                skip = host in limited
            if not skip:
                try:
                    results[i] = (key, get_latest(owner, repo, pick_token(settings, kind, base),
                                                  inc, known, kind, base), None)
                except RateLimitError as e:
                    results[i] = (key, None, str(e))
                    with lock:
                        limited.add(host)
                except HostError as e:
                    results[i] = (key, None, str(e))
                except Exception as e:  # noqa: BLE001 - one broken answer must not lose the others
                    results[i] = (key, None, "Unexpected error: %s" % e)
            with lock:
                done[0] += 1
                finished = done[0]
            if progress:
                progress(finished, total)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(workers, total))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [r for r in results if r is not None]


def lookup_project(cands, token_for):
    """Everything needed to add a project: (info, latest). Runs independent requests together.

    With one candidate, the project details and the release list are asked for at the
    same time. With several (an unknown host), the kind of host is settled first.
    """
    if len(cands) == 1:
        c = cands[0]
        latest = spawn(get_latest, c["owner"], c["repo"], token_for(c["kind"], c["base"]),
                       True, None, c["kind"], c["base"])
        info = resolve_project(cands, token_for)
        return info, latest.result()
    info = resolve_project(cands, token_for)
    return info, get_latest(info["owner"], info["repo"], token_for(info["kind"], info["base"]),
                            True, None, info["kind"], info["base"])


def _pop_meta(latest):
    """Remove and return the extra release-list fields from a fetch result."""
    if not latest:
        return {"history": [], "pre_tags": [], "pre_exact": False, "assets": {}}
    return {
        "history": latest.pop("history", None) or [],
        "pre_tags": latest.pop("pre_tags", None) or [],
        "pre_exact": bool(latest.pop("pre_exact", False)),
        "assets": latest.pop("assets", None) or {},
    }


def apply_result(p, latest, err, now):
    """Store one check result on project p, without inventing false updates."""
    p["last_checked"] = now
    if err:
        p["error"] = err
        return
    p["error"] = None
    history, pre, exact, new_assets = [], [], False, {}
    if latest:
        meta = _pop_meta(latest)
        history, pre, exact, new_assets = meta["history"], meta["pre_tags"], meta["pre_exact"], meta["assets"]
        if p.get("seen_tag") and p["seen_tag"] == latest["tag"]:
            # Same release as the one already seen; only the ID scheme differs
            # (API release ID vs feed entry ID), so carry the acknowledgement over.
            p["seen_id"] = latest["id"]
        elif p.get("fmt") != 2 and p.get("seen_id") is None:
            # Entry saved by an older version that found nothing: treat what
            # exists now as the baseline instead of flagging it.
            p["seen_id"], p["seen_tag"] = latest["id"], latest["tag"]
    tags = _unique_tags(([latest["tag"]] if latest else []) + history)
    old_hist, old_pre = set(p.get("history") or []), set(p.get("pre_tags") or [])
    if exact:
        pre_set = set(pre)
    else:
        # Flags are only a guess this time: keep what an earlier check already
        # decided for known tags, and guess only for tags that are new.
        pre_set = {t for t in tags if t in old_pre or (t not in old_hist and t in pre)}
    p["pre_exact"] = exact or (bool(p.get("pre_exact")) and all(t in old_hist for t in tags))
    p["history"] = tags
    p["pre_tags"] = [t for t in tags if t in pre_set]
    # Release files: take the fresh list when this check read one, else keep the stored one.
    old_assets = p.get("assets") or {}
    p["assets"] = {t: (new_assets[t] if t in new_assets else old_assets[t])
                   for t in tags[:MAX_ASSET_RELEASES] if t in new_assets or t in old_assets}
    if latest and latest["tag"] in pre_set:
        latest["prerelease"] = True   # the feed cannot say this itself
    p["latest"] = latest
    p["fmt"] = 2


# --------------------------------------------------------------------------
# Download folder scan: which release files are present on disk
# --------------------------------------------------------------------------
# Words that mark a pre-release. A file "app-1.2.3-beta.zip" is not release 1.2.3.
_PRE_WORDS = r"(?:alpha|beta|rc|preview|nightly|snapshot|pre|dev)(?![a-z])"
_PRE_TAG = re.compile(r"(?<![a-z])" + _PRE_WORDS)
_DOTTED = re.compile(r"\d+(?:\.\d+)+")


def looks_prerelease(tag):
    """Guess from the tag name alone: "v2.0.0-beta.1" and "v1.0-rc2" are pre-releases."""
    return bool(_PRE_TAG.search((tag or "").casefold()))


def version_regex(tag):
    """Regex that finds this release's version inside a lowercase file path, or None.

    "v1.2.3" and "release-1.2.3" both become the version "1.2.3". It matches
    "app-1.2.3-setup.exe" and "app-1.2.3.0.zip", but not "app-1.2.30.exe",
    "app-11.2.3.exe", "app-1.2.3.4.zip" or "app-1.2.3-beta.zip".
    """
    t = (tag or "").strip().casefold().split("+", 1)[0]   # drop build metadata
    m = re.search(r"\d", t)
    if m:
        t = t[m.start():]                                  # drop "v", "release-", ...
    t = t.strip("-_. ")
    if not t:
        return None
    pure = bool(re.fullmatch(_DOTTED, t))
    if pure:                                               # 1.0.0 -> 1.0 (trailing zeros)
        parts = t.split(".")
        while len(parts) > 2 and parts[-1] == "0":
            parts.pop()
        t = ".".join(parts)
    body = "[-_]+".join(re.escape(x) for x in re.split(r"[-_]+", t))
    start = r"(?<![0-9])(?<![0-9]\.)" if t[0].isdigit() else r"(?<![a-z0-9])"
    end = r"(?![0-9])(?!\.[0-9]+(?![a-z]))(?![-_. ]?" + _PRE_WORDS + ")"
    if pure:
        end = r"(?:\.0+)*" + end                           # 1.2.3 also matches 1.2.3.0
    if t[-1].isalpha():
        end = r"(?![a-z])" + end
    return re.compile(start + body + end)


def name_regex(names):
    """Regex for a project name in a lowercase relative file path, or None.

    The full name may start at any word in the path: "yt-dlp" matches
    "tools/yt-dlp_2024.exe". The leading words of a multi-word name also count,
    but only at the very start of a file or folder name, and only when they
    hold at least 4 letters: the repository "totk-pc-recomp" matches
    "TotK-Setup-0.4.1-windows.zip" through "totk". Both rules keep generic words
    such as "windows" in the middle of a file name from matching by accident.
    """
    full, lead = [], []
    for n in names:
        parts = [x for x in re.split(r"[-_.\s]+", (n or "").casefold()) if x]
        for k in range(len(parts), 0, -1):
            if k < len(parts) and sum(len(x) for x in parts[:k]) < 4:
                break
            pat = "[-_. ]?".join(re.escape(x) for x in parts[:k])
            target = full if k == len(parts) else lead
            if pat not in target:
                target.append(pat)
    alts = []
    if full:
        alts.append(r"(?<![a-z0-9])(?:" + "|".join(full) + ")")
    if lead:
        alts.append(r"(?:^|/)(?:" + "|".join(lead) + ")")
    return re.compile("|".join(alts)) if alts else None


class ScanCancelled(Exception):
    """Raised inside a scan when a newer scan has replaced it."""


def fmt_size(n):
    size = float(n)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return "%d B" % size if unit == "B" else "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%.1f GB" % size


def file_sha256(path, cancelled=None, on_bytes=None):
    """SHA-256 of a file as lowercase hex.

    Raises OSError if the file cannot be read, and ScanCancelled if cancelled()
    turns true while the file is being read.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if cancelled and cancelled():
                raise ScanCancelled()
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            if on_bytes:
                on_bytes(len(chunk))
    return h.hexdigest()


def list_folder(folder):
    """Entries under folder, a few levels deep.

    Each entry is (path relative to folder with '/', is_dir, size, mtime_ns); the
    size is -1 for folders and for files that cannot be examined. Partial
    downloads are skipped. Returns None if the folder cannot be read.
    """
    if not os.path.isdir(folder):
        return None
    out = []
    stack = [(folder, "", 0)]
    while stack and len(out) < SCAN_MAX_ENTRIES:
        path, rel, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except OSError:
            if depth == 0:
                return None
            continue
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if not is_dir and e.name.casefold().endswith(PARTIAL_EXT):
                continue
            size, mtime = -1, 0
            if not is_dir:
                try:
                    st = e.stat()
                    size, mtime = st.st_size, st.st_mtime_ns
                except OSError:
                    pass
            out.append((rel + e.name, is_dir, size, mtime))
            if is_dir and depth < SCAN_MAX_DEPTH:
                stack.append((e.path, rel + e.name + "/", depth + 1))
    return out


def _make_listing(folder):
    """List a folder once for all projects that scan it. None if it cannot be read."""
    entries = list_folder(folder)
    if entries is None:
        return None
    by_size, by_base = {}, {}
    for idx, (rel, is_dir, size, _mtime) in enumerate(entries):
        if not is_dir and size >= 0:
            by_size.setdefault(size, []).append(idx)
            by_base.setdefault(rel.rsplit("/", 1)[-1].casefold(), []).append(idx)
    return {"folder": os.path.abspath(folder), "entries": entries,
            "folded": [e[0].casefold() for e in entries], "by_size": by_size, "by_base": by_base}


def _path_of(listing, idx):
    return os.path.join(listing["folder"], *listing["entries"][idx][0].split("/"))


def find_name_matches(names, tags, folded, dedicated):
    """{tag index: [entry indexes]} for entries whose path holds a release's version.

    When the folder is not dedicated to the project, the project name must also
    appear in the path. At most MAX_MATCHES entries are kept for each release.
    """
    if dedicated:
        cand = list(range(len(folded)))
    else:
        rx = name_regex(names)
        if rx is None:
            return {}
        cand = [i for i, s in enumerate(folded) if rx.search(s)]
    if not cand:
        return {}
    blob = "\n".join(folded[i] for i in cand)
    offsets, pos = [], 0
    for i in cand:
        offsets.append(pos)
        pos += len(folded[i]) + 1
    out = {}
    for n, tag in enumerate(tags):
        rx = version_regex(tag)
        if rx is None:
            continue
        found = []
        for m in rx.finditer(blob):
            idx = cand[bisect.bisect_right(offsets, m.start()) - 1]
            if idx not in found:
                found.append(idx)
                if len(found) >= MAX_MATCHES:
                    break
        if found:
            out[n] = found
    return out


def _version_hit(rx_cache, path, tag):
    if tag not in rx_cache:
        rx_cache[tag] = version_regex(tag)
    rx = rx_cache[tag]
    return bool(rx and rx.search(path))


def _digest_tables(tags, assets, verify):
    """What the stored release files say about each of the newest releases.

    Returns (digests, plain, digest_rel, sizes, unsized):
      digests[n]   set of SHA-256 digests of release n's files; empty = cannot be verified
      plain[n]     sizes of release n's files that have no digest (-1 = size not published)
      digest_rel   {digest: [release indexes, newest first]}
      sizes        every size of a file with a digest: only local files of these sizes are hashed
      unsized[n]   lowercase names of release n's files that have a digest but no published
                   size (GitLab): local files with such a name are hashed as well
    """
    digests, plain, digest_rel, sizes, unsized = [], [], {}, set(), []
    for n, tag in enumerate(tags[:MAX_ASSET_RELEASES]):
        ds, nd, nu = set(), set(), set()
        for name, size, digest in (assets.get(tag) or []) if verify else []:
            if digest:
                ds.add(digest)
                rel = digest_rel.setdefault(digest, [])
                if n not in rel:
                    rel.append(n)
                if size >= 0:
                    sizes.add(size)
                else:
                    nu.add(name.casefold())
            elif not is_metadata_name(name):    # a checksum file is not a download to look for
                nd.add(size)
        digests.append(ds)
        plain.append(nd)
        unsized.append(nu)
    return digests, plain, digest_rel, sizes, unsized


def _evaluate(listing, hashes, names, tags, pre_tags, folder, dedicated, tables, cand, matches=None):
    """Decide which release a folder holds for one project (see scan_projects).

    matches = find_name_matches(...) for this project, when the caller has it already.
    """
    entries, folded = listing["entries"], listing["folded"]
    digests, plain, digest_rel = tables[0], tables[1], tables[2]
    if matches is None:
        matches = find_name_matches(names, tags, folded, dedicated)
    rx_cache = {}

    def checkable(n):
        return n < len(digests) and bool(digests[n])

    # 1. A file with the SHA-256 of a release file proves that release, whatever its name.
    file_hash, present = {}, {}
    for idx in sorted(cand):
        h = hashes.get(os.path.normcase(_path_of(listing, idx)))
        file_hash[idx] = h
        ns = digest_rel.get(h) if h else None
        if not ns:
            continue
        if len(ns) == 1:
            n_eff = ns[0]
        else:  # the same file is in several releases: trust the file name, else assume the oldest
            named = [n for n in ns if _version_hit(rx_cache, folded[idx], tags[n])]
            n_eff = min(named) if named else max(ns)
        present.setdefault(n_eff, (idx, "hash"))

    # 2. A file whose name holds the project name and a release version. When GitHub
    #    published checksums for that release, the file must match one of them.
    rejected = {}
    for n, idxs in matches.items():
        best, first_bad = None, None
        for idx in idxs:
            _rel, is_dir, size, _mtime = entries[idx]
            if is_dir or not checkable(n):
                how = "name"       # nothing to compare it with
            elif file_hash.get(idx, False) is None:
                how = "name"       # could not be read, so it cannot be checked
            elif file_hash.get(idx) in digests[n]:
                how = "hash"
            else:
                # A file of the size of a release file that has no digest passes by name.
                # Size -1 = a release file whose size is unknown: it could be this file.
                how = "name" if (size in plain[n] or -1 in plain[n]) else None   # None = differs from every file
            if how == "hash":
                best = (idx, "hash")
                break
            if how == "name" and best is None:
                best = (idx, "name")
            if how is None and first_bad is None:
                first_bad = idx
        if best is not None:
            if best[1] == "hash" or n not in present:
                present[n] = best
        elif n not in present:
            rejected[n] = first_bad

    info = {"state": "missing", "note": "", "tag": "", "file": "", "folder": folder,
            "newest": tags[0], "verify": "", "mismatch": []}
    best_n = min(present) if present else None
    if best_n is not None:
        idx, how = present[best_n]
        pre = set(pre_tags)
        stable_idx = next((i for i, t in enumerate(tags) if t not in pre), None)
        if best_n == 0:
            info["state"], info["note"] = "latest", "latest"
        elif best_n == stable_idx:
            info["state"], info["note"] = "latest", "prerelease"   # a newer pre-release exists
        else:
            info["state"] = "older"
        info.update(tag=tags[best_n], file=entries[idx][0], verify=how)
    info["mismatch"] = [{"tag": tags[n], "file": entries[i][0]} for n, i in sorted(rejected.items())
                        if best_n is None or n < best_n][:3]
    return info


def _byte_progress(progress, label, size):
    """Callback for file_sha256 that reports the percentage a few times a second."""
    state = {"done": 0, "t": time.time()}

    def on_bytes(n):
        state["done"] += n
        now = time.time()
        if now - state["t"] >= 0.3:
            state["t"] = now
            progress("%s, %d%% ..." % (label, min(100, int(100 * state["done"] / size)) if size else 100))
    return on_bytes


def scan_projects(snapshot, verify=True, cache=None, cancelled=None, progress=None, stats=None):
    """Compare download folders with release lists (runs in a background thread).

    snapshot: list of (key, names, tags, pre_tags, folder, dedicated[, assets]).
      tags[0] is the newest release and pre_tags lists the tags that are pre-releases.
      assets maps a tag to [[file name, size, SHA-256 hex or ""], ...].
    verify: compare SHA-256 digests (needs assets). False = file names only.
    cache: {path key: [size, mtime_ns, sha256]}; new hashes are added in place.
    cancelled: function that returns True when this scan should stop.
    progress: function that takes a status text.
    stats: dict that receives hashed, bytes, unreadable and cancelled.

    Returns {key: {"state", "note", "tag", "file", "folder", "newest", "verify",
    "mismatch"}} where state is "latest" (up to date), "older" (needs update),
    "missing" (not downloaded) or "nofolder" (the folder does not exist).
    For "latest", note is "latest" when the file is the newest release, or
    "prerelease" when it is the newest stable release and a newer pre-release exists.
    verify is "hash" (SHA-256 matches a release file) or "name" (file name only).
    mismatch lists up to 3 files whose name matches a newer release but whose
    SHA-256 differs from every file of that release: {"tag", "file"}.
    """
    cache = {} if cache is None else cache
    stats = {} if stats is None else stats
    stats.update(hashed=0, bytes=0, unreadable=0, cancelled=False)

    listings, plans, needed = {}, [], {}
    for item in snapshot:
        key, names, tags, pre_tags, folder, dedicated = item[:6]
        assets = item[6] if len(item) > 6 and isinstance(item[6], dict) else {}
        fk = os.path.normcase(os.path.normpath(folder))
        if fk not in listings:
            listings[fk] = _make_listing(folder)
        listing = listings[fk]
        tables = _digest_tables(tags, assets, verify)
        cand, matches = set(), None
        if listing is not None:
            entries = listing["entries"]
            for size in tables[3]:
                cand.update(listing["by_size"].get(size, ()))
            for unsized in tables[4]:           # files without a published size: look at same-named files
                for name in unsized:
                    cand.update(listing["by_base"].get(name, ()))
            matches = find_name_matches(names, tags, listing["folded"], dedicated)
            for n, idxs in matches.items():     # ... and at files whose name holds the version
                if n < len(tables[4]) and tables[4][n]:
                    cand.update(i for i in idxs if not entries[i][1] and entries[i][2] >= 0)
            for idx in cand:
                path = _path_of(listing, idx)
                _rel, _is_dir, size, mtime = entries[idx]
                needed[os.path.normcase(path)] = (path, size, mtime)
        plans.append((key, names, tags, pre_tags, folder, dedicated, listing, tables, cand, matches))

    # Hash the files that could be release files: same size as a release file.
    hashes, todo = {}, []
    for hk, (path, size, mtime) in needed.items():
        c = cache.get(hk)
        if c and c[0] == size and c[1] == mtime:
            hashes[hk] = c[2]
            del cache[hk]
            cache[hk] = c               # recently used entries stay at the end
        else:
            todo.append((size, hk, path, mtime))
    todo.sort()
    try:
        for i, (size, hk, path, mtime) in enumerate(todo, 1):
            if cancelled and cancelled():
                raise ScanCancelled()
            label = "Checking SHA-256, file %d of %d: %s (%s)" % (
                i, len(todo), os.path.basename(path), fmt_size(size))
            if progress:
                progress(label + " ...")
            try:
                digest = file_sha256(path, cancelled, _byte_progress(progress, label, size) if progress else None)
            except OSError:
                hashes[hk] = None       # locked or unreadable: the name decides
                stats["unreadable"] += 1
                continue
            hashes[hk] = digest
            cache.pop(hk, None)
            cache[hk] = [size, mtime, digest]
            stats["hashed"] += 1
            stats["bytes"] += size
    except ScanCancelled:
        stats["cancelled"] = True
        return {}

    out = {}
    for key, names, tags, pre_tags, folder, dedicated, listing, tables, cand, matches in plans:
        if listing is None:
            out[key] = {"state": "nofolder", "note": "", "tag": "", "file": "", "folder": folder,
                        "newest": tags[0], "verify": "", "mismatch": []}
        else:
            out[key] = _evaluate(listing, hashes, names, tags, pre_tags, folder, dedicated, tables, cand, matches)
    return out


def same_path(a, b):
    return bool(a) and bool(b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


# --------------------------------------------------------------------------
# Storage, import and export (all input is treated as untrusted)
# --------------------------------------------------------------------------
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def _s(value, limit=300):
    return value.strip()[:limit] if isinstance(value, str) else ""


def safe_web_url(url, base, fallback):
    """Only ever open links on the project's own host, whatever a JSON file says."""
    if (isinstance(url, str) and base and url.startswith(base + "/") and len(url) < 500
            and not any(c.isspace() for c in url)):
        return url
    return fallback


def safe_github_url(url, fallback):
    """Only ever open https://github.com/... links, whatever a JSON file says."""
    return safe_web_url(url, GITHUB_BASE, fallback)


def _id_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    return value[:300] if isinstance(value, str) else value


def normalize_release(r, owner, repo, kind="github", base=GITHUB_BASE):
    if not isinstance(r, dict):
        return None
    tag = _s(r.get("tag"), 200)
    rid = _id_value(r.get("id"))
    if rid is None:
        rid = tag or None
    if rid is None:
        return None
    source = r.get("source")
    return {
        "id": rid,
        "tag": tag,
        "name": _s(r.get("name"), 300),
        "published_at": _s(r.get("published_at"), 40),
        "url": safe_web_url(r.get("url"), base, releases_url(kind, base, owner, repo)),
        "prerelease": bool(r.get("prerelease")),
        "source": source if source in ("release", "tag", "feed") else "release",
    }


def clean_name(value):
    """A user-chosen display name: one line, single spaces, at most MAX_CUSTOM_NAME characters."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:MAX_CUSTOM_NAME].strip()


def display_name(p):
    """What the Project column shows: the user's own name if set, else the GitHub name."""
    return p.get("custom_name") or p.get("title") or p["repo"]
def normalize_assets(raw):
    """Clean {tag: [[file name, size (-1 = unknown), SHA-256 hex or ""], ...]} read from a file."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for tag, items in list(raw.items())[:MAX_ASSET_RELEASES]:
        tag = _s(tag, 200)
        if not tag or not isinstance(items, list):
            continue
        files = []
        for a in items[:MAX_ASSETS_PER_RELEASE]:
            if (isinstance(a, list) and len(a) == 3 and isinstance(a[0], str) and a[0]
                    and isinstance(a[1], int) and not isinstance(a[1], bool) and a[1] >= -1
                    and isinstance(a[2], str)):
                digest = a[2].strip().lower()
                files.append([a[0][:200], a[1], digest if re.fullmatch(r"[0-9a-f]{64}", digest) else ""])
        out[tag] = files
    return out


def normalize_project(raw):
    """Return a clean project dict from untrusted input, or None if unusable.

    A plain address is only accepted when the kind of host is clear from the address
    (GitHub, or a host name such as gitlab.com or codeberg.org): nothing can be asked
    of the network here. An entry without "kind" is a GitHub project (older files).
    """
    if isinstance(raw, str):
        cands = parse_project_ref(raw)
        if len(cands) != 1:
            return None
        raw = cands[0]
    if not isinstance(raw, dict):
        return None
    owner, repo = raw.get("owner"), raw.get("repo")
    kind = raw.get("kind")
    if kind is None or kind == "":
        kind = "github" if not raw.get("base") else guess_kind(host_of(clean_base(raw.get("base"))))
    if kind not in KINDS:
        return None
    base = GITHUB_BASE if kind == "github" else clean_base(raw.get("base"))
    if not base or not valid_ident(kind, owner, repo):
        return None
    fmt = raw.get("fmt")
    out = {
        "kind": kind,
        "base": base,
        "owner": owner,
        "repo": repo,
        "title": _s(raw.get("title"), 200) or repo,
        "description": _s(raw.get("description"), 500),
        "html_url": safe_web_url(raw.get("html_url"), base, repo_url(base, owner, repo)),
        "include_prereleases": bool(raw.get("include_prereleases", True)),
        "fmt": fmt if fmt == 2 else None,
        "latest": normalize_release(raw.get("latest"), owner, repo, kind, base),
        "seen_id": _id_value(raw.get("seen_id")),
        "seen_tag": _s(raw.get("seen_tag"), 200) or None,
        "last_checked": _s(raw.get("last_checked"), 40),
        "error": _s(raw.get("error"), 300) or None,
        "history": _unique_tags([_s(t, 200) for t in raw["history"]]
                                if isinstance(raw.get("history"), list) else []),
        "pre_tags": _unique_tags([_s(t, 200) for t in raw["pre_tags"]]
                                 if isinstance(raw.get("pre_tags"), list) else []),
        "pre_exact": raw.get("pre_exact") is True,   # True = flags came from the GitHub API
        "assets": normalize_assets(raw.get("assets")),   # files and SHA-256 digests of recent releases
        "folder": _s(raw.get("folder"), 500),   # "" = use the default download folder
    }
    custom = clean_name(raw.get("custom_name"))
    if custom:  # only present when the user renamed the project
        out["custom_name"] = custom
    return out


def parse_import(raw):
    """Return (projects, skipped_count), or (None, 0) if there is no project list.

    Accepts this app's file ({"projects": [...]}), a bare list, and lists of
    plain "owner/repo" strings or project URLs (GitHub, or a host whose kind its
    name shows, such as gitlab.com or codeberg.org).
    """
    items = raw.get("projects") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return None, 0
    seen, out, skipped = set(), [], max(0, len(items) - MAX_PROJECTS)
    for item in items[:MAX_PROJECTS]:
        p = normalize_project(item)
        if not p or project_key(p) in seen:
            skipped += 1
            continue
        seen.add(project_key(p))
        out.append(p)
    return out, skipped


def merge_projects(existing, incoming):
    """Add incoming projects that are not already listed. Returns how many were added."""
    keys = {project_key(p) for p in existing}
    added = 0
    for p in incoming:
        k = project_key(p)
        if k not in keys:
            existing.append(p)
            keys.add(k)
            added += 1
    return added


def build_export(projects):
    """Export payload. The access token is deliberately never included.

    The stored release files ("assets") are left out: the next check reads them again.
    """
    return {
        "app": APP_NAME,
        "format": 2,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "projects": [{k: v for k, v in p.items() if k not in ("assets", "pending")}
                     for p in projects if not p.get("pending")],
    }


SORTABLE = ("name", "repo", "published", "status")  # columns whose header can be clicked


def _title_key(p):
    return display_name(p).casefold()


def status_rank(p, dl=None):
    """Order of the Status column. Same precedence as status_text().

    dl is the folder scan result for the project (None = no download folder).
    """
    if p.get("pending"):
        return 6                      # Adding ... (still being looked up)
    if p.get("error"):
        return 3                      # Error
    if not p.get("latest"):
        return 4                      # No releases published
    if dl:
        return {"older": 0, "missing": 1, "nofolder": 2}.get(dl["state"], 5)
    return 0 if has_update(p) else 5  # Update available / Up to date


def sort_projects(projects, col, asc, scan=None):
    """Return projects sorted by column. col "" = default (needs attention first, then A-Z).

    Projects without a publish date (no release, or a tag) always stay at the
    bottom for "published", whichever direction is chosen.
    Status: ascending = Needs update, Not downloaded, Folder not found, Error,
    No releases, Up to date (without a download folder: Update available, Error,
    No releases, Up to date); descending = the reverse, so "Up to date" comes
    first. Projects with the same status are always A-Z.
    scan maps project keys to folder scan results (see scan_projects).
    """
    scan = scan or {}
    if col == "status":
        sign = 1 if asc else -1
        return sorted(projects, key=lambda p: (sign * status_rank(p, scan.get(project_key(p))),
                                               _title_key(p), project_key(p)))
    if col == "name":
        return sorted(projects, key=lambda p: (_title_key(p), project_key(p)), reverse=not asc)
    if col == "repo":
        return sorted(projects, key=project_key, reverse=not asc)
    if col == "published":
        dated = [p for p in projects if (p.get("latest") or {}).get("published_at")]
        undated = [p for p in projects if not (p.get("latest") or {}).get("published_at")]
        dated.sort(key=lambda p: (p["latest"]["published_at"], _title_key(p)), reverse=not asc)
        undated.sort(key=_title_key)
        return dated + undated
    return sorted(projects, key=lambda p: (status_rank(p, scan.get(project_key(p))) > 1, _title_key(p)))


def default_data():
    return {"settings": {"token": "", "check_on_launch": False, "theme": "",
                         "sort_col": "", "sort_asc": True, "download_folder": "",
                         "verify_hash": True, "host_tokens": {}},
            "projects": []}


def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data()
    try:
        with open(DATA_FILE, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        if not isinstance(d, dict) or not isinstance(d.get("projects", []), list):
            raise ValueError("bad structure")
    except (OSError, ValueError, RecursionError):
        try:
            os.replace(DATA_FILE, DATA_FILE + ".bak")
        except OSError:
            pass
        return default_data()
    base = default_data()
    s = d.get("settings")
    if isinstance(s, dict):
        base["settings"]["token"] = _s(s.get("token"), 200)
        base["settings"]["check_on_launch"] = bool(s.get("check_on_launch"))
        base["settings"]["theme"] = s.get("theme") if s.get("theme") in ("light", "dark") else ""
        base["settings"]["sort_col"] = s.get("sort_col") if s.get("sort_col") in SORTABLE else ""
        base["settings"]["sort_asc"] = s.get("sort_asc") is not False
        base["settings"]["download_folder"] = _s(s.get("download_folder"), 500)
        base["settings"]["verify_hash"] = s.get("verify_hash") is not False
        tokens = s.get("host_tokens")
        if isinstance(tokens, dict):    # {"git.example.org": "token"}: one access token per host
            base["settings"]["host_tokens"] = {
                k.lower(): v.strip()[:300] for k, v in list(tokens.items())[:100]
                if isinstance(k, str) and re.fullmatch(r"[A-Za-z0-9.:-]{1,260}", k)
                and isinstance(v, str) and v.strip()}
    projects, _ = parse_import(d)
    base["projects"] = projects or []
    return base


def write_json_atomic(path, obj, indent=2):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False)
    os.replace(tmp, path)


def save_data(data):
    """Write projects.json. A project that is still being added is not saved yet."""
    projects = [p for p in data.get("projects", []) if not p.get("pending")]
    write_json_atomic(DATA_FILE, dict(data, projects=projects))


def acquire_instance_lock(path):
    """Lock a file so that a second copy of the app on the same data is refused.

    Two copies would overwrite each other's changes to projects.json. The operating
    system drops the lock when the app ends, even after a crash, so it is never stale.
    Returns the open file (keep it open while the app runs), None if another copy
    holds the lock, or True if locking is not possible here (the app then just starts).
    """
    try:
        f = open(path, "a+b")
    except OSError:
        return True
    try:
        f.seek(0, 2)
        if f.tell() == 0:
            f.write(b"\n")
            f.flush()
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        f.close()
        return True
    except OSError:
        f.close()
        return None
    return f


def load_hash_cache():
    """{path key: [size, mtime_ns, sha256]} remembered from earlier scans (untrusted file)."""
    try:
        with open(HASH_CACHE_FILE, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (OSError, ValueError, RecursionError):
        return {}
    items = raw.get("files") if isinstance(raw, dict) else None
    if not isinstance(items, dict):
        return {}
    out = {}
    for k, v in items.items():
        if (isinstance(k, str) and isinstance(v, list) and len(v) == 3
                and all(isinstance(x, int) and not isinstance(x, bool) for x in v[:2])
                and isinstance(v[2], str) and re.fullmatch(r"[0-9a-f]{64}", v[2])):
            out[k[:1000]] = [v[0], v[1], v[2]]
    return dict(list(out.items())[-HASH_CACHE_MAX:])


def save_hash_cache(cache):
    """Keep the most recently used HASH_CACHE_MAX entries. A failure only costs a re-scan."""
    try:
        write_json_atomic(HASH_CACHE_FILE, {"files": dict(list(cache.items())[-HASH_CACHE_MAX:])}, indent=None)
    except OSError:
        pass


def repo_label(p):
    """"owner/repo" for GitHub; "host/owner/repo" for any other host."""
    if (p.get("kind") or "github") == "github":
        return "%s/%s" % (p["owner"], p["repo"])
    return "%s/%s/%s" % (host_path(p.get("base")), p["owner"], p["repo"])


def project_key(p):
    """Identity of a project. GitHub projects keep the key "owner/repo" from older versions."""
    return repo_label(p).lower()


def has_update(p):
    latest = p.get("latest")
    return bool(latest) and latest.get("id") != p.get("seen_id")


# Status icons: green / yellow / red circles. The App swaps them for a plain dot if
# this Tk build cannot take characters above U+FFFF. Row colors carry the meaning
# either way, because Tk on Windows often draws emoji in the text color.
DL_ICON = {"latest": "\U0001F7E2", "older": "\U0001F7E1", "missing": "\U0001F534"}
DL_LABEL = {"latest": "Up to date", "older": "Needs update", "missing": "Not downloaded"}


def status_text(p, dl=None):
    """Status column text. dl is the folder scan result (None = no download folder)."""
    if p.get("pending"):
        return "Adding ..."
    if p.get("error"):
        return "Error: " + p["error"]
    latest = p.get("latest")
    if not latest:
        return "No releases published"
    if dl:
        if dl["state"] == "nofolder":
            return "Folder not found"
        if dl["state"] == "latest":
            note = "Pre-release available" if dl.get("note") == "prerelease" else "latest"
            return "%s %s (%s)" % (DL_LABEL["latest"], DL_ICON["latest"], note)
        text = "%s %s" % (DL_LABEL[dl["state"]], DL_ICON[dl["state"]])
        return text + " (hash mismatch)" if dl.get("mismatch") else text
    if has_update(p):
        old = p.get("seen_tag")
        new = latest.get("tag") or latest.get("name") or "new release"
        return "Update available: %s -> %s" % (old, new) if old else "Update available: " + new
    return "Up to date"


def scan_details(p, dl):
    """One or two sentences for the status bar: what the folder scan found for a project."""
    latest_tag = (p.get("latest") or {}).get("tag") or "?"
    if dl["state"] == "nofolder":
        return "Folder not found: %s" % dl["folder"]
    mismatch = ""
    if dl.get("mismatch"):
        m = dl["mismatch"][0]
        mismatch = (" %s matches release %s by name, but its SHA-256 differs from every file of "
                    "that release (incomplete, corrupt, modified, or not a release file)."
                    % (m["file"], m["tag"]))
    if dl["state"] in ("latest", "older"):
        how = ("SHA-256 verified" if dl.get("verify") == "hash"
               else "matched by file name only, no SHA-256 to compare")
        newest = ("Newest pre-release: %s." if dl.get("note") == "prerelease"
                  else "Latest release: %s.") % (dl.get("newest") or latest_tag)
        return "Found %s for release %s (%s) in %s. %s%s" % (
            dl["file"], dl["tag"], how, dl["folder"], newest, mismatch)
    return ("No file for release %s (or its recent predecessors) found in %s.%s "
            "A file counts when its SHA-256 equals a release file, or its name holds "
            "the project name and the version." % (latest_tag, dl["folder"], mismatch))


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------
THEMES = {
    "light": dict(bg="#f3f3f3", fg="#1b1b1b", field="#ffffff", sel_bg="#0078d4", sel_fg="#ffffff",
                  head_bg="#e5e5e5", btn_bg="#e1e1e1", btn_active="#d0d0d0", border="#bdbdbd",
                  update_bg="#fff3cd", update_fg="#1b1b1b", error_fg="#b00020",
                  none_fg="#777777", sub_fg="#666666", ok_fg="#1a7f37", line="#d4d4d4", tip_bg="#ffffe1", tip_fg="#1b1b1b"),
    "dark": dict(bg="#202124", fg="#e8eaed", field="#2b2d31", sel_bg="#2f6fbf", sel_fg="#ffffff",
                 head_bg="#33363b", btn_bg="#3a3d42", btn_active="#4a4d52", border="#4a4d52",
                 update_bg="#4d4210", update_fg="#ffe9a6", error_fg="#ff8a80",
                 none_fg="#9aa0a6", sub_fg="#9aa0a6", ok_fg="#56d364", line="#3d4046", tip_bg="#3a3d42", tip_fg="#e8eaed"),
}


def system_theme():
    """Windows' own app theme (dark/light); light if it cannot be read."""
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except Exception:  # noqa: BLE001 - not Windows / value missing
        return "light"


def set_titlebar_dark(win, dark):
    """Best effort: dark title bar on Windows 10/11. May show after a repaint."""
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # 20 = current, 19 = older Windows 10 builds
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# Icons (drawn from embedded alpha masks; no image files, no extra packages)
# --------------------------------------------------------------------------
def make_png(w, h, rgba):
    """Encode raw RGBA bytes as a PNG (standard library only)."""
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(kind, body):
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def icon_image(master, name, size, color):
    """A PhotoImage of a toolbar icon in the given color, or None if anything goes wrong
    (the buttons then simply show their text without an icon)."""
    try:
        mask = zlib.decompress(base64.b64decode(ICON_MASKS[name][size]))
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        rgba = b"".join(bytes((r, g, b, a)) for a in mask)
        return tk.PhotoImage(master=master, data=base64.b64encode(make_png(size, size, rgba)))
    except Exception:  # noqa: BLE001
        return None


class Tooltip:
    """A small hover label for a widget (used on the icon-only theme button)."""

    def __init__(self, widget, text_fn, colors_fn):
        self.widget, self.text_fn, self.colors_fn = widget, text_fn, colors_fn
        self.tip, self.job = None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._hide()
        self.job = self.widget.after(500, self._show)

    def _show(self):
        self.job = None
        bg, fg = self.colors_fn()
        tip = self.tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tk.Label(tip, text=self.text_fn(), bg=bg, fg=fg, bd=1, relief="solid", padx=6, pady=2).pack()
        tip.update_idletasks()
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        x = max(0, min(x, self.widget.winfo_screenwidth() - tip.winfo_reqwidth() - 4))
        tip.wm_geometry("+%d+%d" % (x, y))

    def _hide(self, _e=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
class App(tk.Tk):
    # Background work is tracked by separate flags, so adding projects, checking for
    # updates and scanning the folders never wait for each other.
    checking = False        # a "Check for updates" run is going
    adding = 0              # projects still being looked up
    _add_errors = ()        # (label, message) of adds that failed, shown together at the end
    _adds_started = 0       # lookups started since the last time all of them were done
    _scanning = False       # a folder scan is running
    _rescan_queued = False  # another scan was asked for meanwhile: run it when this one ends
    _rescan_prefix = None
    _scan_folders = frozenset()   # folders the running scan reads

    @property
    def busy(self):
        """True while a check or an add is going (a folder scan does not count)."""
        return self.checking or self.adding > 0

    def __init__(self):
        super().__init__()
        self.title("%s v%s" % (APP_NAME, APP_VERSION))
        self.geometry("1320x560")  # replaced below by a screen-aware size
        self.app_icon = None
        try:  # window / taskbar icon (the .exe's own icon comes from build.bat --icon)
            self.app_icon = tk.PhotoImage(master=self, data=APP_ICON_PNG)
            self.iconphoto(True, self.app_icon)
        except Exception:  # noqa: BLE001 - cosmetic only
            self.app_icon = None
        # Toolbar icons: 16 px normally, 24 px on high-DPI screens (150% and up).
        try:
            self.icon_px = 24 if self.winfo_fpixels("1i") / 96.0 >= 1.4 else 16
        except tk.TclError:
            self.icon_px = 16
        self._btn_icons = []      # (button, icon name) pairs, recolored when the theme changes
        self._icon_refs = []      # PhotoImages must stay referenced or Tk blanks them
        self._pencil_imgs = {}
        self._editor = None       # inline rename box: (entry, row id, project)
        self._suppress_select = False  # True while render() restores the selection (see _on_select)
        self._col_base, self._col_min = {}, {}   # preferred / minimum column widths (see _layout_columns)
        self._tree_w, self._col_drag = 0, False
        self._lines, self._lines_job = [], None
        self._vlines, self._head_h = [], None   # column lines; measured height of the header row
        self._hsb_shown = False
        self._xorg = 2
        self.data = load_data()
        self.theme_name = self.data["settings"].get("theme") or system_theme()
        self.sort_col = self.data["settings"].get("sort_col") or ""
        self.sort_asc = self.data["settings"].get("sort_asc") is not False
        self.q = queue.Queue()
        self.scan = {}        # project key -> folder scan result (see scan_projects)
        self._scan_gen = 0    # lets a newer scan replace one that is still running
        self._progress_shown = False   # True while the status bar holds scan progress text
        self.hash_cache = load_hash_cache()   # SHA-256 of local files, until they change
        try:  # some Tk builds reject characters above U+FFFF; fall back to a plain dot
            self.tk.call("set", "_icon_probe", DL_ICON["latest"])
        except Exception:  # noqa: BLE001
            for k in DL_ICON:
                DL_ICON[k] = "●"
        self._build_ui()
        self.apply_theme()
        self.render()
        # Never let the window get narrower than the toolbar needs (buttons overlapped).
        self.update_idletasks()
        min_w, min_h = max(700, self.toolbar.winfo_reqwidth() + 20), 340
        self.minsize(min_w, min_h)
        # Normal start size: wide enough that every column fits (no horizontal scrollbar),
        # but never bigger than the screen, never below the minimum; opens centered.
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = max(min(1320, sw - 40), min_w)
        h = max(min(560, sh - 120), min_h)
        self.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        self.after(100, self._poll)
        if self.any_folder() and self.data["projects"]:
            self.rescan("Folders scanned")
        if self.data["settings"].get("check_on_launch") and self.data["projects"]:
            self.after(400, self.check_updates)

    # ---- layout ----------------------------------------------------------
    def _build_ui(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")  # the only built-in theme that is fully recolorable
        except tk.TclError:
            pass

        top = ttk.Frame(self, padding=(10, 10, 10, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Project URL (GitHub, GitLab, Gitea, Forgejo):").pack(side="left")
        self.entry = ttk.Entry(top)
        self.entry.pack(side="left", fill="x", expand=True, padx=8)
        self.entry.bind("<Return>", lambda e: self.add_project())
        self.btn_add = self._button(top, "Add project", "plus", self.add_project)
        self.btn_add.pack(side="left")

        bar = ttk.Frame(self, padding=(10, 4, 10, 6))
        bar.pack(fill="x")
        self.toolbar = bar
        self.btn_check = self._button(bar, "Check for updates", "refresh", self.check_updates)
        self.btn_check.pack(side="left")
        self._button(bar, "Rescan files", "folder", self.rescan_clicked).pack(side="left", padx=(8, 0))
        self._button(bar, "Mark as seen", "eye", self.mark_seen).pack(side="left", padx=(8, 0))
        self._button(bar, "Open release page", "ext", self.open_release).pack(side="left", padx=(8, 0))
        self._button(bar, "Remove", "trash", self.remove_selected).pack(side="left", padx=(8, 0))
        self._button(bar, "Settings", "gear", self.open_settings).pack(side="right")
        # Icon-only: shows the mode you will switch TO (moon = go dark, sun = go light).
        self.btn_theme = self._button(bar, "", "moon", self.toggle_theme)
        self.btn_theme.pack(side="right", padx=(0, 8))
        Tooltip(self.btn_theme,
                lambda: "Switch to light mode" if self.theme_name == "dark" else "Switch to dark mode",
                lambda: (THEMES[self.theme_name]["tip_bg"], THEMES[self.theme_name]["tip_fg"]))
        self._button(bar, "Export", "export", self.export_json).pack(side="right", padx=(0, 8))
        self._button(bar, "Import", "import", self.import_json).pack(side="right", padx=(0, 8))

        frame = ttk.Frame(self, padding=(10, 0, 10, 0))
        frame.pack(fill="both", expand=True)
        cols = ("name", "repo", "release", "published", "status", "folder", "checked")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        heads = [
            ("name", "Project", 140, 110),
            ("repo", "Repository", 355, 110),          # fits "gitlab.com/engage-pc-recomp/engage-pc-recomp"
            ("release", "Current release", 175, 90),   # fits "v2.1.0-beta (pre-release)"
            ("published", "Published", 120, 115),  # wide enough for the sort arrow
            ("status", "Status", 250, 170),
            ("folder", "Folder", 110, 90),
            ("checked", "Last checked", 130, 110),
        ]
        self.head_text = {cid: text for cid, text, _w, _mw in heads}
        for cid, text, w, mw in heads:
            if cid in SORTABLE:  # Current release / Last checked: not clickable
                self.tree.heading(cid, text=text, anchor="w", command=lambda c=cid: self.sort_by(c))
            else:
                self.tree.heading(cid, text=text, anchor="w")
            # No Tk "stretch": _layout_columns() resizes every column in proportion to the window.
            self.tree.column(cid, width=w, minwidth=mw, stretch=False)
            self._col_base[cid], self._col_min[cid] = w, mw
        self.update_headings()
        # Grid (not pack) so the scrollbars always keep their own space: with pack the
        # list took the full width of its columns and pushed the scrollbar out of view.
        self.vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self._on_yscroll, xscrollcommand=self._on_xscroll)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.hsb.grid_remove()   # shown only when the columns do not fit (see _on_xscroll)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._popup)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<F2>", lambda e: self.rename_selected())
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<Configure>", self._schedule_lines, add="+")
        self.tree.bind("<Configure>", self._layout_columns, add="+")
        self.tree.bind("<ButtonPress-1>", self._col_press, add="+")
        self.tree.bind("<ButtonRelease-1>", self._col_release, add="+")
        self.tree.bind("<B1-Motion>", lambda e: self._schedule_lines() if self._col_drag else None, add="+")
        self.tree.bind("<Motion>", self._on_motion, add="+")
        self.tree.bind("<Leave>", self._on_leave, add="+")
        self.tree.bind("<MouseWheel>", lambda e: self._hide_pencil(), add="+")
        # Hover pencil (rename). A Label placed over the list: Treeview cannot hold widgets in cells.
        self.pencil = tk.Label(self.tree, bd=0, highlightthickness=0, cursor="hand2")
        self.pencil.bind("<Button-1>", lambda e: self.begin_rename(self._pencil_row))
        self.pencil.bind("<MouseWheel>", self._forward_wheel)
        self.pencil.bind("<Leave>", self._on_leave)
        self._pencil_row = None

        self.menu = tk.Menu(self, tearoff=0)
        self.pre_var = tk.BooleanVar(value=False)
        self.menu.add_command(label="Open release page", command=self.open_release)
        self.menu.add_command(label="Open repository", command=self.open_repo)
        self.menu.add_command(label="Mark as seen", command=self.mark_seen)
        self.menu.add_separator()
        self.menu.add_command(label="Rename...", accelerator="F2", command=self.rename_selected)
        self.menu.add_command(label="Reset name", command=self.reset_name)
        self.menu.add_checkbutton(label="Include pre-releases", variable=self.pre_var,
                                  command=self.toggle_prerelease)
        self.menu.add_separator()
        self.menu.add_command(label="Change folder...", command=self.change_folder)
        self.menu.add_command(label="Use default folder", command=self.use_default_folder)
        self.menu_default_idx = self.menu.index("end")
        self.menu.add_separator()
        self.menu.add_command(label="Set access token for this host...", command=self.set_host_token)
        self.menu.add_separator()
        self.menu.add_command(label="Remove", command=self.remove_selected)

        self.status = tk.StringVar(value="Add a project to get started.")
        self.status_label = ttk.Label(self, textvariable=self.status, anchor="w", padding=(10, 6))
        self.status_label.pack(fill="x")
        self._build_text_menus()

    # ---- theme -----------------------------------------------------------
    def apply_theme(self):
        c = THEMES[self.theme_name]
        s = self.style
        self.configure(bg=c["bg"])
        s.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["field"],
                    bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"],
                    troughcolor=c["bg"], insertcolor=c["fg"])
        s.configure("TFrame", background=c["bg"])
        s.configure("TLabel", background=c["bg"], foreground=c["fg"])
        s.configure("Sub.TLabel", background=c["bg"], foreground=c["sub_fg"])
        s.configure("TButton", background=c["btn_bg"], foreground=c["fg"], bordercolor=c["border"],
                    lightcolor=c["btn_bg"], darkcolor=c["btn_bg"], focuscolor=c["btn_bg"],
                    padding=(10, 4))
        s.map("TButton",
              background=[("disabled", c["bg"]), ("pressed", c["btn_active"]), ("active", c["btn_active"])],
              foreground=[("disabled", c["sub_fg"])])
        s.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"], insertcolor=c["fg"],
                    bordercolor=c["border"], lightcolor=c["field"], darkcolor=c["field"])
        s.configure("TCheckbutton", background=c["bg"], foreground=c["fg"])
        s.map("TCheckbutton", background=[("active", c["bg"])])
        s.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["fg"],
                    bordercolor=c["border"], lightcolor=c["field"], darkcolor=c["field"], rowheight=26)
        s.map("Treeview", background=[("selected", c["sel_bg"])], foreground=[("selected", c["sel_fg"])])
        s.configure("Treeview.Heading", background=c["head_bg"], foreground=c["fg"], relief="flat",
                    bordercolor=c["border"], lightcolor=c["head_bg"], darkcolor=c["head_bg"],
                    padding=(3, 4), font=self._head_font())
        s.map("Treeview.Heading", background=[("active", c["btn_active"])])
        for name in ("TScrollbar", "Vertical.TScrollbar"):
            s.configure(name, background=c["btn_bg"], troughcolor=c["bg"], arrowcolor=c["fg"],
                        bordercolor=c["bg"], lightcolor=c["btn_bg"], darkcolor=c["btn_bg"])
            s.map(name, background=[("active", c["btn_active"])])
        self.tree.tag_configure("update", background=c["update_bg"], foreground=c["update_fg"])
        self.tree.tag_configure("error", foreground=c["error_fg"])
        self.tree.tag_configure("none", foreground=c["none_fg"])
        self.tree.tag_configure("pending", foreground=c["sub_fg"])
        self.tree.tag_configure("dl_latest", foreground=c["ok_fg"])
        self.tree.tag_configure("dl_older", background=c["update_bg"], foreground=c["update_fg"])
        self.tree.tag_configure("dl_missing", foreground=c["error_fg"])
        for mnu in (self.menu, self.edit_menu, self.status_menu):
            mnu.configure(bg=c["field"], fg=c["fg"], activebackground=c["sel_bg"],
                          activeforeground=c["sel_fg"], disabledforeground=c["none_fg"], bd=0)
        self.refresh_icons()
        self.arrow_up = self._triangle(True, c["fg"])      # sort arrows follow the theme color
        self.arrow_down = self._triangle(False, c["fg"])
        self.update_headings()
        self._pencil_imgs = {}
        self._hide_pencil()
        self._head_h = None   # re-measure the header row (its height can depend on the theme)
        self._schedule_lines()
        set_titlebar_dark(self, self.theme_name == "dark")

    def toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.data["settings"]["theme"] = self.theme_name
        self.persist()
        self.apply_theme()
        self.set_status("%s mode." % self.theme_name.capitalize())

    # ---- toolbar icons ---------------------------------------------------
    def _button(self, parent, text, icon, command):
        btn = ttk.Button(parent, text=text, command=command)
        self._btn_icons.append((btn, icon))
        return btn

    def refresh_icons(self):
        """(Re)draw every button icon in the theme's colors, with a greyed copy for disabled."""
        c = THEMES[self.theme_name]
        self._icon_refs = []
        for btn, name in self._btn_icons:
            if btn is getattr(self, "btn_theme", None):
                name = "sun" if self.theme_name == "dark" else "moon"
            normal = icon_image(self, name, self.icon_px, c["fg"])
            grey = icon_image(self, name, self.icon_px, c["sub_fg"])
            if normal is None or grey is None:
                continue
            self._icon_refs += [normal, grey]
            icon_only = not str(btn.cget("text"))
            btn.configure(image=(normal, "disabled", grey), compound="image" if icon_only else "left")

    # ---- column widths ---------------------------------------------------
    def _head_font(self):
        """The list's normal font, in bold, for the column headers."""
        if getattr(self, "_head_font_obj", None) is None:
            import tkinter.font as tkfont
            f = tkfont.nametofont("TkDefaultFont", root=self).copy()
            f.configure(weight="bold")
            self._head_font_obj = f
        return self._head_font_obj

    def _layout_columns(self, _event=None):
        """Size the columns to the window, in proportion to their preferred widths.

        Wider than the preferred total: every column grows by the same ratio. Narrower: each
        column shrinks from its preferred width toward its minimum, all at the same rate, so
        the columns hit their minimums together and no single column gets squeezed first.
        Runs only when the list's width changes, so a column the user dragged keeps its width
        until the window is resized.
        """
        width = self.tree.winfo_width()
        if width <= 1 or width == self._tree_w:
            return
        self._tree_w = width
        avail = width - 4  # the list draws a 2 px border on each side
        ids = list(self._col_base)
        pref = [self._col_base[c] for c in ids]
        low = [self._col_min[c] for c in ids]
        total_pref, total_low = sum(pref), sum(low)
        if avail >= total_pref:
            target = [p * avail / float(total_pref) for p in pref]
        else:
            t = max(0.0, (avail - total_low) / float(total_pref - total_low))
            target = [lo + (p - lo) * t for p, lo in zip(pref, low)]
        sizes = [max(lo, int(x)) for x, lo in zip(target, low)]
        if avail >= total_low:                     # hand the rounding remainder to Status
            sizes[ids.index("status")] += max(0, avail - sum(sizes))
        for cid, w in zip(ids, sizes):
            self.tree.column(cid, width=w)
        self._schedule_lines()

    def _col_press(self, event):
        self._col_drag = self.tree.identify_region(event.x, event.y) == "separator"

    def _col_release(self, _event):
        if self._col_drag:  # the user resized a column: that is the new preferred layout
            self._col_drag = False
            ids = list(self._col_base)
            slack = self.tree.winfo_width() - 4 - sum(int(self.tree.column(c, "width")) for c in ids)
            if slack > 0:       # a column was made narrower: the last column takes the freed space, no empty strip
                last = ids[-1]
                self.tree.column(last, width=int(self.tree.column(last, "width")) + slack)
            self._col_base = {c: int(self.tree.column(c, "width")) for c in self._col_base}
            self._schedule_lines()

    # ---- row and column separators (thin lines) ---------------------------
    def _on_xscroll(self, first, last):
        self.hsb.set(first, last)
        needed = (float(last) - float(first)) < 0.998     # less than ~2 px hidden does not count
        if needed != self._hsb_shown:
            self._hsb_shown = needed
            if needed:
                self.hsb.grid()
            else:
                self.hsb.grid_remove()
        self._schedule_lines()

    def _on_yscroll(self, first, last):
        self.vsb.set(first, last)
        self._schedule_lines()
        self._hide_pencil()

    def _schedule_lines(self, _e=None):
        if self._lines_job is None:
            self._lines_job = self.after_idle(self._redraw_lines)

    def _redraw_lines(self):
        self._lines_job = None
        tree = self.tree
        ys = []
        for iid in tree.get_children():
            box = tree.bbox(iid)
            if box:
                ys.append(box[1] + box[3] - 1)
        while len(self._lines) < len(ys):
            f = tk.Frame(tree, height=1, bd=0, highlightthickness=0)
            # A click that lands exactly on the 1 px line is passed on to the list.
            f.bind("<Button-1>", lambda e: self._forward(e, "<Button-1>"))
            f.bind("<ButtonRelease-1>", lambda e: self._forward(e, "<ButtonRelease-1>"))
            f.bind("<Button-3>", lambda e: self._forward(e, "<Button-3>"))
            f.bind("<MouseWheel>", self._forward_wheel)
            self._lines.append(f)
        color = THEMES[self.theme_name]["line"]
        for i, f in enumerate(self._lines):
            if i < len(ys):
                f.configure(bg=color)
                f.place(x=0, y=ys[i], relwidth=1, height=1)
                f.lift()
            else:
                f.place_forget()
        self._redraw_vlines()

    def _header_height(self):
        """Pixel height of the header row (measured once; the column lines start below it)."""
        if self._head_h is None:
            tree = self.tree
            x, y = max(3, tree.winfo_width() // 2), 3
            while y < 80 and tree.identify_region(x, y) in ("heading", "separator"):
                y += 1
            self._head_h = y if 3 < y < 80 else None
        return self._head_h

    def _redraw_vlines(self):
        tree = self.tree
        hh = self._header_height()
        cols = list(tree["columns"])
        widths = [int(tree.column(c, "width")) for c in cols]
        off = int(round(tree.xview()[0] * sum(widths)))      # how far the list is scrolled sideways
        # where the first column really starts inside the widget (border width differs per theme/OS)
        for iid in tree.get_children():
            b = tree.bbox(iid, cols[0])
            if b:
                self._xorg = b[0] + off
                break
        edges, cum = [], 0
        for w in widths[:-1]:
            cum += w
            edges.append(cum - 1 - off + self._xorg)
        while len(self._vlines) < len(edges):
            f = tk.Frame(tree, width=1, bd=0, highlightthickness=0)
            f.bind("<Button-1>", lambda e: self._forward(e, "<Button-1>", True))
            f.bind("<ButtonRelease-1>", lambda e: self._forward(e, "<ButtonRelease-1>", True))
            f.bind("<Button-3>", lambda e: self._forward(e, "<Button-3>", True))
            f.bind("<MouseWheel>", self._forward_wheel)
            self._vlines.append(f)
        color = THEMES[self.theme_name]["line"]
        visible_w = tree.winfo_width() - 2
        for f, x in zip(self._vlines, edges):
            if hh and 0 <= x < visible_w:
                f.configure(bg=color)
                f.place(x=x, y=hh, width=1, relheight=1.0, height=-hh)
                f.lift()
            else:
                f.place_forget()

    def _forward(self, event, sequence, vertical=False):
        """Pass a click that landed on a 1 px line on to the list underneath."""
        w = event.widget
        x, y = (w.winfo_x() - 1, event.y + w.winfo_y()) if vertical else (event.x, w.winfo_y() - 1)
        try:
            self.tree.event_generate(sequence, x=x, y=y, rootx=event.x_root, rooty=event.y_root)
        except tk.TclError:
            pass

    def _forward_wheel(self, event):
        self.tree.yview_scroll(-1 if event.delta > 0 else 1, "units")

    # ---- rename (pencil on hover, F2, right-click) ------------------------
    def _row_bg(self, iid):
        c = THEMES[self.theme_name]
        if iid in self.tree.selection():
            return c["sel_bg"], c["sel_fg"]
        if "update" in self.tree.item(iid, "tags"):
            return c["update_bg"], c["update_fg"]
        return c["field"], c["fg"]

    def _on_motion(self, event):
        if self._editor:
            return
        iid = self.tree.identify_row(event.y)
        if (not iid or self.tree.identify_region(event.x, event.y) != "cell"
                or "pending" in self.tree.item(iid, "tags")):
            self._hide_pencil()
            return
        box = self.tree.bbox(iid, "name")
        if not box:
            self._hide_pencil()
            return
        x, y, w, h = box
        bg, fg = self._row_bg(iid)
        px = self.icon_px
        img = self._pencil_imgs.get(fg)
        if img is None:
            img = self._pencil_imgs[fg] = icon_image(self, "pencil", px, fg)
        if img is None:
            return
        self.pencil.configure(image=img, bg=bg)
        self.pencil.place(x=x + w - px - 8, y=y + (h - px) // 2)
        self.pencil.lift()
        self._pencil_row = iid

    def _on_tree_click(self, _event):
        if self._editor:  # a click elsewhere in the list saves the name being typed
            self.after_idle(lambda: self._finish_rename(True))

    def _on_leave(self, _event=None):
        # Moving from the list onto the pencil itself must not hide it.
        under = self.winfo_containing(*self.winfo_pointerxy())
        if under is not self.pencil:
            self._hide_pencil()

    def _hide_pencil(self):
        self.pencil.place_forget()
        self._pencil_row = None

    def rename_selected(self):
        sel = self.selected_projects()
        if len(sel) != 1:
            self.set_status("Select one project to rename.")
            return
        self.begin_rename(project_key(sel[0]))

    def begin_rename(self, iid):
        if not iid or self._editor or not self.tree.exists(iid):
            return
        self._close_editor(True)
        self.tree.see(iid)
        self.update_idletasks()
        box = self.tree.bbox(iid, "name")
        p = next((q for q in self.data["projects"] if project_key(q) == iid), None)
        if not box or not p or p.get("pending"):   # a row that is still being added cannot be renamed
            return
        self._hide_pencil()
        x, y, w, h = box
        ent = ttk.Entry(self.tree)
        ent.insert(0, display_name(p))
        ent.place(x=x, y=y, width=w, height=h)
        ent.focus_force()
        ent.select_range(0, "end")
        ent.icursor("end")
        self.attach_edit_menu(ent)
        self._editor = (ent, iid, p)
        ent.bind("<Return>", lambda e: self._finish_rename(True))
        ent.bind("<Escape>", lambda e: self._finish_rename(False))
        # No save-on-focus-loss: opening the box's right-click menu (Paste) takes focus away
        # and must not close it. Clicking elsewhere in the list saves it instead (_on_tree_click).

    def _finish_rename(self, commit):
        if not self._editor:
            return
        changed = self._close_editor(commit)
        self.render()
        if changed:
            self.set_status(changed)

    def _close_editor(self, commit):
        """Close the rename box; returns a status message if a name changed, else ''."""
        if not self._editor:
            return ""
        ent, _iid, p = self._editor
        self._editor = None
        text = clean_name(ent.get())
        ent.destroy()
        if not commit:
            return ""
        original = p.get("title") or p["repo"]
        before = display_name(p)
        if text and text != original:
            p["custom_name"] = text
        else:
            p.pop("custom_name", None)  # blank or the GitHub name itself = back to the original
        if display_name(p) == before:
            return ""
        self.persist()
        return "Renamed to %s." % display_name(p) if p.get("custom_name") else "Name reset to %s." % display_name(p)

    def reset_name(self):
        sel = [p for p in self.selected_projects() if p.get("custom_name")]
        if not sel:
            self.set_status("Nothing to reset: the selection has no custom name.")
            return
        for p in sel:
            p.pop("custom_name", None)
        self.persist()
        self.render()
        self.set_status("Reset %d name(s) to the GitHub name." % len(sel))

    # ---- About -----------------------------------------------------------
    def show_about(self, parent=None):
        c = THEMES[self.theme_name]
        parent = parent or self
        win = tk.Toplevel(self)
        win.title("About " + APP_NAME)
        win.configure(bg=c["bg"])
        win.transient(parent)

        def close():
            win.destroy()
            if parent is not self and parent.winfo_exists():
                parent.grab_set()  # back to the Settings window, which is modal
        win.resizable(False, False)
        if self.app_icon is not None:
            try:
                win.iconphoto(False, self.app_icon)
            except tk.TclError:
                pass
        body = ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)
        if self.app_icon is not None:
            tk.Label(body, image=self.app_icon, bg=c["bg"], bd=0).grid(row=0, column=0, rowspan=4, sticky="n", padx=(0, 16))
        ttk.Label(body, text=APP_NAME, font=("Segoe UI", 14, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(body, text="Version %s" % APP_VERSION).grid(row=1, column=1, sticky="w")
        ttk.Label(body, style="Sub.TLabel", wraplength=340, justify="left",
                  text="Tracks the latest release of the GitHub projects you follow. "
                       "No account, login or token needed. MIT License.").grid(row=2, column=1, sticky="w", pady=(6, 6))
        link = tk.Label(body, text=REPO_URL, fg="#4da3ff" if self.theme_name == "dark" else "#0b57d0",
                        bg=c["bg"], cursor="hand2", bd=0)
        link.grid(row=3, column=1, sticky="w")
        link.bind("<Button-1>", lambda e: webbrowser.open(REPO_URL))
        btns = ttk.Frame(body)
        btns.grid(row=4, column=0, columnspan=2, sticky="e", pady=(16, 0))

        def copy_version():
            self.clipboard_clear()
            self.clipboard_append("%s v%s" % (APP_NAME, APP_VERSION))
            self.set_status("Copied: %s v%s" % (APP_NAME, APP_VERSION))

        ttk.Button(btns, text="Close", command=close).pack(side="right")
        ttk.Button(btns, text="Copy version", command=copy_version).pack(side="right", padx=(0, 8))
        set_titlebar_dark(win, self.theme_name == "dark")
        win.grab_set()
        win.bind("<Escape>", lambda e: close())
        win.protocol("WM_DELETE_WINDOW", close)

    # ---- helpers ---------------------------------------------------------
    # ---- right-click menus for text (Cut / Copy / Paste / Select all) -------
    def _build_text_menus(self):
        em = self.edit_menu = tk.Menu(self, tearoff=0)
        em.add_command(label="Cut", accelerator="Ctrl+X", command=lambda: self._edit("<<Cut>>"))
        em.add_command(label="Copy", accelerator="Ctrl+C", command=lambda: self._edit("<<Copy>>"))
        em.add_command(label="Paste", accelerator="Ctrl+V", command=lambda: self._edit("<<Paste>>"))
        em.add_separator()
        em.add_command(label="Select all", accelerator="Ctrl+A", command=lambda: self._select_all(self._edit_target))
        self._edit_target = None
        self.status_menu = tk.Menu(self, tearoff=0)
        self.status_menu.add_command(label="Copy", command=self.copy_status)
        self.attach_edit_menu(self.entry)
        self.status_label.bind("<Button-3>", self._show_status_menu)

    def attach_edit_menu(self, entry, masked=False):
        """Right-click menu + Ctrl+A for a text box. masked=True (token box): no Cut/Copy."""
        entry.bind("<Button-3>", lambda e, m=masked: self._show_edit_menu(e, m))
        entry.bind("<Control-a>", lambda e: self._select_all(e.widget))
        entry.bind("<Control-A>", lambda e: self._select_all(e.widget))

    @staticmethod
    def _select_all(w):
        if w is not None:
            w.selection_range(0, "end")
            w.icursor("end")
        return "break"  # stop Tk's own Ctrl+A (jump to line start on some platforms)

    def _edit(self, virtual_event):
        w = self._edit_target
        if w is not None:
            w.focus_set()
            w.event_generate(virtual_event)  # use the text box's own, native Cut/Copy/Paste

    def _show_edit_menu(self, event, masked=False):
        w = event.widget
        state = str(w.cget("state"))
        if state == "disabled":
            return
        w.focus_set()
        try:
            has_clip = bool(self.clipboard_get())
        except tk.TclError:  # clipboard empty or holds something that is not text
            has_clip = False
        has_sel = bool(w.selection_present())
        editable = state == "normal"
        em = self.edit_menu
        em.entryconfigure("Cut", state="normal" if (has_sel and editable and not masked) else "disabled")
        em.entryconfigure("Copy", state="normal" if (has_sel and not masked) else "disabled")
        em.entryconfigure("Paste", state="normal" if (has_clip and editable) else "disabled")
        em.entryconfigure("Select all", state="normal" if w.get() else "disabled")
        self._edit_target = w
        try:
            em.tk_popup(event.x_root, event.y_root)
        finally:
            em.grab_release()

    def _show_status_menu(self, event):
        self.status_menu.entryconfigure("Copy", state="normal" if self.status.get() else "disabled")
        try:
            self.status_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.status_menu.grab_release()

    def copy_status(self):
        self.clipboard_clear()
        self.clipboard_append(self.status.get())

    def token(self):
        return (self.data["settings"].get("token") or "").strip()

    def token_for(self, kind, base):
        """The access token for a host. The GitHub token never goes to another host."""
        return pick_token(self.data["settings"], kind, base)

    def set_host_token(self):
        """Ask for the access token of the selected project's host (GitHub: see Settings)."""
        sel = self.selected_projects()
        if not sel:
            self.set_status("Select a project first.")
            return
        p = sel[0]
        if (p.get("kind") or "github") == "github":
            self.open_settings()          # GitHub's token has its own field there
            return
        host = host_of(p["base"])
        tokens = self.data["settings"].setdefault("host_tokens", {})
        answer = simpledialog.askstring(
            APP_NAME,
            "Access token for %s (%s).\nNeeded for private projects, or when the server limits "
            "anonymous requests.\nIt is stored in plain text in projects.json and is only sent "
            "to %s.\nLeave empty to remove it." % (host, KIND_LABEL[p["kind"]], host),
            initialvalue=tokens.get(host, ""), show="*", parent=self)
        if answer is None:
            return
        answer = answer.strip()[:300]
        if answer:
            tokens[host] = answer
        else:
            tokens.pop(host, None)
        host_blocked_until.pop(host, None)    # a new token has its own limit
        self.persist()
        self.set_status("Access token for %s %s. Click \"Check for updates\" to use it." % (
            host, "saved" if answer else "removed"))

    def set_status(self, text):
        self.status.set(text)

    def _sync_buttons(self):
        """Only "Check for updates" is locked while a check runs. Adding stays possible."""
        self.btn_check.configure(state="disabled" if self.checking else "normal")

    def run_async(self, fn, done):
        def target():
            try:
                self.q.put((done, fn(), None))
            except Exception as e:  # noqa: BLE001 - surfaced to the UI
                self.q.put((done, None, e))
        threading.Thread(target=target, daemon=True).start()

    def _poll(self):
        while True:
            try:
                done, res, exc = self.q.get_nowait()
            except queue.Empty:
                break
            try:
                done(res, exc)
            except Exception as e:  # noqa: BLE001 - the handlers reset their own flags first
                self.set_status("Internal error: %s" % e)
        self.after(100, self._poll)

    def selected_projects(self, with_pending=False):
        """Selected projects. A row that is still being added has no data yet, so it is left out."""
        keys = set(self.tree.selection())
        return [p for p in self.data["projects"]
                if project_key(p) in keys and (with_pending or not p.get("pending"))]

    def persist(self):
        try:
            save_data(self.data)
        except OSError as e:
            messagebox.showerror(APP_NAME, "Could not save projects.json:\n%s" % e)

    # ---- download folders ------------------------------------------------
    def default_folder(self):
        return (self.data["settings"].get("download_folder") or "").strip()

    def any_folder(self):
        return bool(self.default_folder()) or any((p.get("folder") or "").strip() for p in self.data["projects"])

    def rescan_clicked(self):
        if not self.any_folder():
            self.set_status("No download folder set. Choose one in Settings first.")
            return
        self.rescan("Folders scanned")

    def rescan(self, prefix=None):
        """Re-read the download folders in the background (no network).

        prefix: start of the status message shown when the scan finishes;
        None = leave the status bar alone.

        A running scan that still reads the right folders is not stopped: hashing a large
        file again from the start would waste the work done so far. The request is queued
        instead, and one more scan (with the newest data) starts when the running one ends.
        Many requests in a row, such as several projects added together, give a single extra
        scan. If a folder the running scan reads is no longer wanted (changed or removed),
        the running scan stops and a new one starts at once.
        """
        if self._scanning:
            wanted = {item[4] for item in self._scan_snapshot()}
            if self._scan_folders <= wanted:
                self._rescan_queued = True
                if prefix is not None:
                    self._rescan_prefix = prefix
                return
            if prefix is None:
                prefix = self._rescan_prefix
            self._rescan_queued, self._rescan_prefix = False, None
        self._start_scan(prefix)

    def _scan_snapshot(self):
        """What a scan needs, copied from the project list (the scan thread must not share it)."""
        default = self.default_folder()
        snapshot = []
        for p in self.data["projects"]:
            latest = p.get("latest") or {}
            if not latest.get("tag"):
                continue  # nothing to compare: the old status logic applies
            own = (p.get("folder") or "").strip()
            folder = own or default
            if not folder:
                continue
            tags = _unique_tags([latest["tag"]] + list(p.get("history") or []))
            names = [p["repo"], p.get("title") or ""]
            # A folder chosen for this project alone does not need the name in the file names.
            dedicated = bool(own) and not same_path(own, default)
            snapshot.append((project_key(p), names, tags, list(p.get("pre_tags") or []), folder, dedicated,
                             dict(p.get("assets") or {})))
        return snapshot

    def _start_scan(self, prefix):
        verify = self.data["settings"].get("verify_hash") is not False
        snapshot = self._scan_snapshot()
        self._scan_folders = {item[4] for item in snapshot}
        self._scan_gen += 1
        gen = self._scan_gen
        if not snapshot:
            self._scanned({}, None, gen, prefix)
            return
        cache, stats = dict(self.hash_cache), {}   # the scan thread works on its own copy
        self._scanning = True

        def progress(text):  # called from the scan thread
            if gen == self._scan_gen:
                self.q.put((lambda _res, _exc: self._progress(gen, text), None, None))

        self.run_async(
            lambda: scan_projects(snapshot, verify, cache, lambda: gen != self._scan_gen, progress, stats),
            lambda res, exc: self._scanned(res, exc, gen, prefix, cache, stats))

    def _progress(self, gen, text):
        if gen == self._scan_gen:
            self._progress_shown = True
            self.set_status(text)

    def _scanned(self, result, exc, gen, prefix, cache=None, stats=None):
        if gen == self._scan_gen:
            self._scanning = False    # first, so that no later error can block future scans
        if cache:  # keep the hashes even from a scan that was replaced: they are still valid
            merged = dict(self.hash_cache)
            for k, v in cache.items():
                merged.pop(k, None)
                merged[k] = v
            self.hash_cache = dict(list(merged.items())[-HASH_CACHE_MAX:])
            if stats and stats.get("hashed"):
                save_hash_cache(self.hash_cache)
        if gen != self._scan_gen:
            return  # a newer scan was started meanwhile
        if self._rescan_queued:
            # The data changed while this scan ran. Show what it found, then scan again.
            self._rescan_queued = False
            if self._rescan_prefix is not None:
                prefix = self._rescan_prefix
            self._rescan_prefix = None
            if not exc:
                self.scan = result
                self.render()
            self._start_scan(prefix)
            return
        shown, self._progress_shown = self._progress_shown, False
        if exc:
            self.set_status("Folder scan failed: %s" % exc)
            return
        self.scan = result
        self.render()
        if prefix is None and shown:
            prefix = "Folders scanned"   # replace the leftover "Checking SHA-256" text
        if prefix is None:
            return
        summary = self.summary_text()
        msg = prefix + (": " + summary if summary else "") + "."
        if stats and stats.get("unreadable"):
            msg += " %d file(s) could not be read for the SHA-256 check." % stats["unreadable"]
        verify = self.data["settings"].get("verify_hash") is not False
        if self.scan and any(
                p.get("latest") and (p["latest"].get("source") != "tag")
                and not (p.get("history") and (p.get("assets") or not verify))
                for p in self.data["projects"]):
            msg += (" Click \"Check for updates\" once to load each project's older releases"
                    + (" and SHA-256 checksums." if verify else "."))
        self.set_status(msg)

    def summary_text(self):
        counts = {"latest": 0, "older": 0, "missing": 0, "nofolder": 0}
        legacy, folder_mode, mismatched = 0, False, 0
        for p in self.data["projects"]:
            if p.get("error") or not p.get("latest"):
                continue
            dl = self.scan.get(project_key(p))
            if dl:
                counts[dl["state"]] += 1
                folder_mode = True
                if dl["state"] in ("older", "missing") and dl.get("mismatch"):
                    mismatched += 1
            elif has_update(p):
                legacy += 1
        labels = (("latest", "up to date"), ("older", "need an update"),
                  ("missing", "not downloaded"), ("nofolder", "with a missing folder"))
        parts = ["%d %s" % (counts[k], text) for k, text in labels if counts[k]]
        if mismatched:
            parts.append("%d with a hash mismatch" % mismatched)
        if legacy or not folder_mode:
            parts.append("%d update(s) available" % legacy)
        return ", ".join(parts)

    def change_folder(self):
        sel = self.selected_projects()
        if not sel:
            self.set_status("Select one or more projects first.")
            return
        start = (sel[0].get("folder") or "").strip() or self.default_folder()
        opts = {"title": "Folder to scan for %s" % (sel[0].get("title") or sel[0]["repo"]),
                "mustexist": True, "parent": self}
        if start and os.path.isdir(start):
            opts["initialdir"] = start
        path = filedialog.askdirectory(**opts)
        if not path:
            return
        path = os.path.normpath(path)
        for p in sel:
            p["folder"] = path
        self.persist()
        self.render()
        self.rescan()
        self.set_status("Scan folder for %d project(s) set to %s." % (len(sel), path))

    def use_default_folder(self):
        sel = self.selected_projects()
        if not sel:
            self.set_status("Select one or more projects first.")
            return
        for p in sel:
            p["folder"] = ""
        self.persist()
        self.render()
        self.rescan()
        if self.default_folder():
            self.set_status("%d project(s) now use the default folder." % len(sel))
        else:
            self.set_status("%d project(s) reset. No default folder is set yet (see Settings)." % len(sel))

    # ---- sorting ---------------------------------------------------------
    def _triangle(self, up, color):
        """A small drawn arrow (no font needed, so it looks the same everywhere)."""
        img = tk.PhotoImage(master=self, width=11, height=6)
        for r in range(6):
            half = r if up else 5 - r
            img.put(color, to=(5 - half, r, 5 + half + 1, r + 1))
        return img

    def update_headings(self):
        """Show an up/down arrow on the header of the column that is sorted."""
        for cid, text in self.head_text.items():
            img = ""
            if cid == self.sort_col and getattr(self, "arrow_up", None) is not None:
                img = self.arrow_up if self.sort_asc else self.arrow_down
            self.tree.heading(cid, text=text, image=img)

    def sort_by(self, col):
        if col == self.sort_col:
            self.sort_asc = not self.sort_asc          # same column again: flip direction
        else:
            self.sort_col = col
            # A-Z first for names; newest first for dates (like Explorer's "Date modified")
            self.sort_asc = (col != "published")
        self.data["settings"]["sort_col"] = self.sort_col
        self.data["settings"]["sort_asc"] = self.sort_asc
        self.persist()
        self.update_headings()
        self.render()

    # ---- rendering -------------------------------------------------------
    def render(self):
        self._close_editor(True)  # rows are rebuilt below: save a name being typed first
        self._hide_pencil()
        # Re-selecting the rows below fires <<TreeviewSelect>> a moment later, which would replace
        # a status message such as "Renamed to ..." with the project description. Ignore those
        # events until the event queue is empty (idle callbacks run after pending events).
        self._suppress_select = True
        self.after_idle(self._allow_select)
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        projects = sort_projects(self.data["projects"], self.sort_col, self.sort_asc, self.scan)
        default = self.default_folder()
        for p in projects:
            latest = p.get("latest") or {}
            dl = self.scan.get(project_key(p))
            release = latest.get("tag") or latest.get("name") or ""
            if latest.get("source") == "tag":
                release += " (tag)"
            elif latest.get("prerelease"):
                release += " (pre-release)"
            if p.get("pending"):
                tag = "pending"
            elif p.get("error"):
                tag = "error"
            elif not latest:
                tag = "none"
            elif dl:
                tag = {"latest": "dl_latest", "older": "dl_older",
                       "missing": "dl_missing"}.get(dl["state"], "error")
            elif has_update(p):
                tag = "update"
            else:
                tag = ""
            own = (p.get("folder") or "").strip()
            folder = own or ("(default)" if default else "-")
            checked = (p.get("last_checked") or "")[:16].replace("T", " ")
            self.tree.insert("", "end", iid=project_key(p), tags=(tag,) if tag else (), values=(
                display_name(p),
                repo_label(p),
                release or "-",
                (latest.get("published_at") or "")[:10] or "-",
                status_text(p, dl),
                folder,
                checked or "never",
            ))
        keep = [k for k in selected if self.tree.exists(k)]
        if keep:
            self.tree.selection_set(keep)
        self._schedule_lines()

    def _on_double_click(self, event):
        """Open the release page only for a double-click on a project row.

        A fast second click on a column header (or on its resize edge, or on
        empty space) must not open anything.
        """
        if self.tree.identify_region(event.x, event.y) == "cell" and self.tree.identify_row(event.y):
            self.open_release()

    def _allow_select(self):
        self._suppress_select = False

    def _on_select(self, _event=None):
        if self._suppress_select:
            return
        sel = self.selected_projects()
        if len(sel) == 1:
            p = sel[0]
            dl = self.scan.get(project_key(p))
            if p.get("error"):
                self.set_status(p["error"])
            elif dl and p.get("latest"):
                self.set_status(scan_details(p, dl))
            else:
                # Always replace the status text: skipping this when the About box is
                # empty left the previous project's description on screen.
                self.set_status(p.get("description") or NO_DESCRIPTION)

    def _popup(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            sel = self.selected_projects()
            if sel:
                self.pre_var.set(bool(sel[0].get("include_prereleases")))
            self.menu.entryconfigure("Rename...", state="normal" if len(sel) == 1 else "disabled")
            self.menu.entryconfigure("Reset name", state="normal" if any(p.get("custom_name") for p in sel) else "disabled")
            has_own = any((p.get("folder") or "").strip() for p in sel)
            self.menu.entryconfigure(self.menu_default_idx, state="normal" if has_own else "disabled")
            try:
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()

    # ---- actions ---------------------------------------------------------
    def add_project(self):
        """Add the address(es) in the box. Each one appears as a row at once and fills in later."""
        tokens = split_project_refs(self.entry.get())
        if not tokens:
            self._bad_address_dialog()
            return
        known = {host_of(p["base"]): p["kind"] for p in self.data["projects"]
                 if (p.get("kind") or "github") != "github" and p.get("base")}
        have = {project_key(p) for p in self.data["projects"]}
        accepted, bad, dups, left = [], [], [], []   # accepted: candidate lists; bad/dups: (address, label)
        for tok in tokens[:MAX_ADD_AT_ONCE]:
            cands = parse_project_ref(tok, known)
            if not cands:
                bad.append((tok, tok))
                left.append(tok)
            elif any(project_key(c) in have for c in cands):
                dups.append((tok, repo_label(cands[0])))
                left.append(tok)
            else:
                have.add(project_key(cands[0]))
                accepted.append(cands)
        extra = tokens[MAX_ADD_AT_ONCE:]
        left += extra   # what was not added stays in the box, in the order it was pasted
        # Copy the tokens now: the worker threads must not read the settings while they can change.
        settings = {"token": self.token(),
                    "host_tokens": dict(self.data["settings"].get("host_tokens") or {})}
        if accepted:
            clear_host_down()   # a click is a new try, even for a host that failed a moment ago
            for cands in accepted:
                self._start_add(cands, settings)
            self.render()
            self.set_status("Adding %s ..." % ", ".join(repo_label(c[0]) for c in accepted[:3])
                            + (" and %d more" % (len(accepted) - 3) if len(accepted) > 3 else ""))
        self.entry.delete(0, "end")
        if left:
            self.entry.insert(0, " ".join(left))
        if bad and not accepted and not dups:
            self._bad_address_dialog()   # nothing usable at all: show the examples
        elif len(tokens) == 1 and dups:
            messagebox.showinfo(APP_NAME, "%s is already in the list." % dups[0][1])
        elif bad or dups or extra:
            lines = []
            if bad:
                lines.append("Not a project address:\n  " + "\n  ".join(t for t, _ in bad))
            if dups:
                lines.append("Already in the list:\n  " + "\n  ".join(label for _, label in dups))
            if extra:
                lines.append("Only %d addresses are added at once. The other %d are still in the box."
                             % (MAX_ADD_AT_ONCE, len(extra)))
            messagebox.showinfo(APP_NAME, "\n\n".join(lines))

    def _bad_address_dialog(self):
        messagebox.showerror(
            APP_NAME,
            "Enter the address of a project, for example\n"
            "https://github.com/owner/repo\n"
            "https://gitlab.com/group/project\n"
            "https://codeberg.org/owner/repo\n"
            "or the address on any Gitea, Forgejo or GitLab server.\n"
            "For GitHub, owner/repo is enough. Several addresses can be pasted at once.")

    def _start_add(self, cands, settings):
        """Put a placeholder row in the list and look the project up in the background."""
        first = cands[0]
        ph = {"owner": first["owner"], "repo": first["repo"], "kind": first["kind"],
              "base": first["base"], "title": first["repo"], "pending": True}
        self.data["projects"].append(ph)
        self.adding += 1
        self._adds_started += 1

        def work():
            return lookup_project(cands, lambda kind, base: pick_token(settings, kind, base))

        self.run_async(work, lambda res, exc: self._added(ph, res, exc))

    def _added(self, ph, result, exc):
        self.adding = max(0, self.adding - 1)     # first: a later error must not leave this stuck
        if not any(x is ph for x in self.data["projects"]):
            self._show_add_errors()               # the row was removed meanwhile: drop the answer
            return
        self.data["projects"] = [x for x in self.data["projects"] if x is not ph]
        label = repo_label(ph)
        if exc:
            self._add_errors += ((label, str(exc)),)
            self.render()
            self.set_status("Could not add %s." % label)
            self._show_add_errors()
            return
        info, latest = result
        p = dict(info)
        if any(project_key(x) == project_key(p) for x in self.data["projects"]):
            self.render()
            self.set_status("%s is already in the list." % repo_label(p))
            self._show_add_errors()
            return
        meta = _pop_meta(latest)
        pre = set(meta["pre_tags"])
        tags = _unique_tags(([latest["tag"]] if latest else []) + meta["history"])
        if latest and latest["tag"] in pre:
            latest["prerelease"] = True
        p.update({
            "include_prereleases": True,  # "whatever is newest", as on the Releases page
            "fmt": 2,
            "latest": latest,
            "history": tags,
            "pre_tags": [t for t in tags if t in pre],
            "pre_exact": meta["pre_exact"],
            "assets": {t: meta["assets"][t] for t in tags[:MAX_ASSET_RELEASES] if t in meta["assets"]},
            "folder": "",  # "" = use the default download folder
            # Baseline: the release that exists now counts as already seen.
            "seen_id": latest["id"] if latest else None,
            "seen_tag": latest["tag"] if latest else None,
            "last_checked": datetime.now().isoformat(timespec="seconds"),
            "error": None,
        })
        self.data["projects"].append(p)
        self.persist()
        self.render()
        self.rescan()
        if latest:
            msg = "Added %s - current release %s." % (p["title"], latest["tag"] or latest["name"])
        else:
            msg = "Added %s - it has no published releases yet." % p["title"]
        if self.adding:
            msg += " %d more being looked up ..." % self.adding
        self.set_status(msg)
        self._show_add_errors()

    def _show_add_errors(self):
        """One dialog for all failed adds, once the last lookup has finished."""
        if self.adding:
            return
        started, self._adds_started = self._adds_started, 0
        if not self._add_errors:
            return
        errors, self._add_errors = self._add_errors, ()
        if len(errors) == 1 and started == 1:
            messagebox.showerror(APP_NAME, errors[0][1])      # the only project: the message is enough
        else:
            messagebox.showerror(APP_NAME, "Could not add %d of %d projects:\n\n%s" % (
                len(errors), started, "\n".join("%s: %s" % e for e in errors)))

    def check_updates(self):
        if self.checking:
            return
        real = [p for p in self.data["projects"] if not p.get("pending")]
        if not real:
            self.set_status("Nothing to check - add a project first.")
            return
        settings = {"token": self.token(),
                    "host_tokens": dict(self.data["settings"].get("host_tokens") or {})}
        snapshot = [(project_key(p), p["owner"], p["repo"], p.get("kind") or "github",
                     p.get("base") or GITHUB_BASE, bool(p.get("include_prereleases")),
                     {"history": list(p.get("history") or []), "pre_tags": list(p.get("pre_tags") or []),
                      "pre_exact": bool(p.get("pre_exact")), "assets": dict(p.get("assets") or {})})
                    for p in real]
        total = len(snapshot)
        clear_host_down()
        self.checking = True
        self._sync_buttons()
        self.set_status("Checking %d project(s) ..." % total)

        def progress(done, count):  # called from the worker threads
            self.q.put((lambda _res, _exc: self._check_progress(done, count), None, None))

        self.run_async(lambda: check_projects(snapshot, settings, progress),
                       lambda res, exc: self._checked(res, exc, total))

    def _check_progress(self, done, count):
        if self.checking and done < count:
            self.set_status("Checking projects: %d of %d done ..." % (done, count))

    def _checked(self, result, exc, total=None):
        self.checking = False                     # first: a later error must not leave the button off
        self._sync_buttons()
        if exc:
            self.set_status("Check failed: %s" % exc)
            return
        now = datetime.now().isoformat(timespec="seconds")
        by_key = {project_key(p): p for p in self.data["projects"]}
        errors = 0
        for key, latest, err in result:
            p = by_key.get(key)
            if not p or p.get("pending"):
                continue
            apply_result(p, latest, err, now)
            if err:
                errors += 1
        self.persist()
        self.render()
        msg = "Checked %d project(s)" % len(result)
        if errors:
            msg += ", %d error(s)" % errors
        if total is not None and total > len(result):
            msg += ", %d skipped (their host asked to slow down)" % (total - len(result))
        if last_rate_remaining is not None and any((p.get("kind") or "github") == "github"
                                                   for p in self.data["projects"]):
            msg += " (GitHub API calls left this hour: %d)" % last_rate_remaining
        self.rescan(msg)  # compares the fresh release lists with the files; sets the status

    def mark_seen(self):
        sel = self.selected_projects()
        if not sel:
            self.set_status("Select one or more projects first.")
            return
        n = 0
        for p in sel:
            latest = p.get("latest")
            if latest and has_update(p):
                p["seen_id"] = latest["id"]
                p["seen_tag"] = latest["tag"]
                n += 1
        self.persist()
        self.render()
        msg = "Marked %d project(s) as seen." % n if n else "No updates to mark in the selection."
        if any(project_key(p) in self.scan for p in sel):
            msg += " Projects with a download folder get their status from the files, not from this."
        self.set_status(msg)

    def open_release(self):
        sel = self.selected_projects()
        if not sel:
            self.set_status("Select a project first.")
            return
        p = sel[0]
        kind, base = p.get("kind") or "github", p.get("base") or GITHUB_BASE
        fallback = releases_url(kind, base, p["owner"], p["repo"])
        webbrowser.open(safe_web_url((p.get("latest") or {}).get("url"), base, fallback))

    def open_repo(self):
        sel = self.selected_projects()
        if sel:
            p = sel[0]
            base = p.get("base") or GITHUB_BASE
            webbrowser.open(safe_web_url(p.get("html_url"), base, repo_url(base, p["owner"], p["repo"])))

    def toggle_prerelease(self):
        sel = self.selected_projects()
        for p in sel:
            p["include_prereleases"] = self.pre_var.get()
        self.persist()
        if self.pre_var.get():
            self.set_status("Pre-releases included (uses the free release feed). Click \"Check for updates\" to apply.")
        else:
            if any((p.get("kind") or "github") == "github" for p in sel):
                self.set_status("Stable-only mode uses the GitHub API, which is rate-limited without a token. "
                                "Click \"Check for updates\" to apply.")
            else:
                self.set_status("Stable-only mode on. Click \"Check for updates\" to apply.")

    def remove_selected(self):
        sel = self.selected_projects(with_pending=True)
        if not sel:
            self.set_status("Select a project first.")
            return
        names = ", ".join(display_name(p) for p in sel[:3]) + ("..." if len(sel) > 3 else "")
        if not messagebox.askyesno(APP_NAME, "Remove %d project(s)?\n%s" % (len(sel), names)):
            return
        drop = {project_key(p) for p in sel}
        self.data["projects"] = [p for p in self.data["projects"] if project_key(p) not in drop]
        self.persist()
        self.render()
        self.set_status("Removed %d project(s)." % len(sel))

    # ---- import / export -------------------------------------------------
    def import_json(self):
        path = filedialog.askopenfilename(
            title="Import projects (.json)",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            if os.path.getsize(path) > MAX_IMPORT_BYTES:
                raise ValueError("The file is larger than 5 MB.")
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
        except (OSError, ValueError, RecursionError) as e:
            messagebox.showerror(APP_NAME, "Could not read that file as JSON:\n%s" % e)
            return
        projects, skipped = parse_import(raw)
        if projects is None:
            messagebox.showerror(APP_NAME, "This file has no project list.")
            return
        if not projects:
            messagebox.showerror(APP_NAME, "No valid projects found in this file.")
            return
        note = " (%d entries skipped as invalid or duplicate)" % skipped if skipped else ""
        choice = messagebox.askyesnocancel(
            APP_NAME,
            "Found %d project(s)%s.\n\n"
            "Yes = Merge: keep your current list and add the new ones\n"
            "No = Replace: discard your current list and use this file\n"
            "Cancel = do nothing" % (len(projects), note))
        if choice is None:
            return
        if choice:
            added = merge_projects(self.data["projects"], projects)
            msg = "Imported: %d new project(s) added, %d already in the list." % (added, len(projects) - added)
        else:
            self.data["projects"] = projects
            msg = "Imported: list replaced with %d project(s)." % len(projects)
        self.persist()
        self.render()
        self.rescan()
        self.set_status(msg + " Click \"Check for updates\" to refresh them.")

    def export_json(self):
        if not self.data["projects"]:
            messagebox.showinfo(APP_NAME, "There are no projects to export yet.")
            return
        path = filedialog.asksaveasfilename(
            title="Export projects (.json)",
            defaultextension=".json",
            initialfile="github_release_tracker_%s.json" % datetime.now().strftime("%Y-%m-%d"),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            write_json_atomic(path, build_export(self.data["projects"]))
        except OSError as e:
            messagebox.showerror(APP_NAME, "Could not write the file:\n%s" % e)
            return
        self.set_status("Exported %d project(s) to %s (token not included)." % (len(self.data["projects"]), path))

    # ---- settings --------------------------------------------------------
    def open_settings(self):
        c = THEMES[self.theme_name]
        win = tk.Toplevel(self)
        win.title("Settings")
        win.configure(bg=c["bg"])
        win.transient(self)
        win.resizable(False, False)
        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Default download folder").grid(row=0, column=0, sticky="w")
        fvar = tk.StringVar(value=self.default_folder())
        frow = ttk.Frame(body)
        frow.grid(row=1, column=0, sticky="we", pady=(2, 2))
        fent = ttk.Entry(frow, textvariable=fvar, width=52)
        fent.pack(side="left", fill="x", expand=True)

        def browse():
            opts = {"title": "Default download folder", "mustexist": True, "parent": win}
            if os.path.isdir(fvar.get().strip()):
                opts["initialdir"] = fvar.get().strip()
            path = filedialog.askdirectory(**opts)
            if path:
                fvar.set(os.path.normpath(path))

        ttk.Button(frow, text="Browse...", command=browse).pack(side="left", padx=(8, 0))
        ttk.Label(body, style="Sub.TLabel", wraplength=480, justify="left",
                  text="The app scans this folder (and its sub-folders) for your downloaded "
                       "releases. A file counts when its SHA-256 equals a release file, or when "
                       "its name holds the project name (or the first word of it) and the "
                       "release version. "
                       "Latest release found: Up to date. Only an older one: "
                       "Needs update. None: Not downloaded. Right-click a project to give it "
                       "its own folder instead. Leave this empty to turn the scan off."
                  ).grid(row=2, column=0, sticky="w", pady=(0, 8))

        verify = tk.BooleanVar(value=self.data["settings"].get("verify_hash") is not False)
        ttk.Checkbutton(body, text="Verify files with SHA-256 (recommended)", variable=verify).grid(
            row=3, column=0, sticky="w")
        ttk.Label(body, style="Sub.TLabel", wraplength=480, justify="left",
                  text="Compares each file with the checksum GitHub publishes for the release "
                       "(on GitLab, Gitea and Forgejo: the checksum file attached to the release, "
                       "such as SHA256SUMS or app.zip.sha256), so renamed files are found and "
                       "damaged or modified ones are reported. Only files with the same size as "
                       "a release file are read. Large files take a while the first time; the "
                       "result is remembered in hash_cache.json."
                  ).grid(row=4, column=0, sticky="w", pady=(0, 12))

        ttk.Label(body, text="GitHub personal access token (optional)").grid(row=5, column=0, sticky="w")
        tok = tk.StringVar(value=self.data["settings"].get("token", ""))
        ent = ttk.Entry(body, textvariable=tok, show="*", width=52)
        ent.grid(row=6, column=0, sticky="we", pady=(2, 2))
        self.attach_edit_menu(ent, masked=True)  # hidden token: Paste yes, Cut/Copy no
        ttk.Label(body, style="Sub.TLabel", wraplength=480, justify="left",
                  text="Releases are read from GitHub's public feed. The GitHub API (60 calls an "
                       "hour without a token) tells pre-releases from normal releases and "
                       "provides the SHA-256 of each release file, so a token helps if you track "
                       "many projects. Without API calls left, pre-releases are guessed from tag "
                       "names such as -beta or -rc1, and files are matched by name. "
                       "It is stored in plain text in projects.json and is never written to "
                       "exported files. For GitLab, Gitea and Forgejo hosts, right-click a "
                       "project and choose \"Set access token for this host\".").grid(
                           row=7, column=0, sticky="w", pady=(0, 10))
        launch = tk.BooleanVar(value=bool(self.data["settings"].get("check_on_launch")))
        ttk.Checkbutton(body, text="Check for updates when the app starts", variable=launch).grid(
            row=8, column=0, sticky="w")

        def save():
            raw_folder = fvar.get().strip()
            folder = os.path.normpath(raw_folder) if raw_folder else ""
            if folder and not os.path.isdir(folder):
                messagebox.showerror(APP_NAME, "That folder does not exist:\n%s" % folder, parent=win)
                return
            old_folder = self.default_folder()
            old_verify = self.data["settings"].get("verify_hash") is not False
            if tok.get().strip() != self.token():
                clear_api_block()  # a new token has its own API limit
            self.data["settings"]["download_folder"] = folder
            self.data["settings"]["verify_hash"] = verify.get()
            self.data["settings"]["token"] = tok.get().strip()
            self.data["settings"]["check_on_launch"] = launch.get()
            self.persist()
            win.destroy()
            if folder != old_folder:
                self.render()
                self.rescan("Default folder saved. Folders scanned")
            elif verify.get() != old_verify:
                self.rescan("SHA-256 check " + ("on" if verify.get() else "off") + ". Folders scanned")
            else:
                self.set_status("Settings saved.")

        btns = ttk.Frame(body)
        btns.grid(row=9, column=0, sticky="we", pady=(12, 0))
        ttk.Button(btns, text="About", command=lambda: self.show_about(win)).pack(side="left")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=save).pack(side="right", padx=(0, 8))
        set_titlebar_dark(win, self.theme_name == "dark")
        win.grab_set()
        fent.focus_set()


def main():
    try:  # crisp text on high-DPI Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - not Windows / not available
        pass
    try:  # own taskbar identity, so Windows shows this app's icon instead of Python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001
        pass
    lock = acquire_instance_lock(os.path.join(_DATA_DIR, "projects.lock"))
    if lock is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            APP_NAME,
            "%s is already running with this data folder.\n\n"
            "Two copies would overwrite each other's changes, so this one will close. "
            "Look for the other window in the taskbar." % APP_NAME)
        root.destroy()
        return
    App().mainloop()


if __name__ == "__main__":
    main()
