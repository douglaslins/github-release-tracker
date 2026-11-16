"""
GitHub Release Tracker (portable)
=================================
A small portable Windows desktop app (Python + tkinter, standard library only)
that tracks the latest release of GitHub projects and tells you when a new one
has been published since you last acknowledged it.

How it works
- Add a project by pasting a GitHub URL or "owner/repo".
- The list shows project name, owner/repo, latest release, publish date, status.
- "Check for updates" reads each project's public release feed
  (github.com/owner/repo/releases.atom): no login or token needed and it does not
  use the GitHub API rate limit. The API is only a fallback.
- A project whose latest release differs from the one you last acknowledged is
  highlighted as "Update available: old -> new".
- "Mark as seen" acknowledges the current release (clears the highlight).
- The app never downloads or installs anything; it opens the release page.
- "Import" / "Export" read and write a .json file (merge or replace on import).
- "Dark mode" / "Light mode" toggles the theme; the choice is remembered.

Portable: no installer, no registry writes. Data lives in projects.json next to
the .exe (or this script). Only if that folder is read-only does the app fall
back to %APPDATA%\\GitHubReleaseTracker.

Build the single-file portable .exe on Windows: double-click build.bat, or run
    pip install pyinstaller
    pyinstaller --onefile --windowed --name GitHubReleaseTracker github_release_tracker.py
The exe appears in the dist folder.
"""

import json
import os
import queue
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import webbrowser
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "GitHub Release Tracker"
API = "https://api.github.com"
MAX_PROJECTS = 500
MAX_IMPORT_BYTES = 5 * 1024 * 1024


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


DATA_FILE = os.path.join(data_dir(), "projects.json")


# --------------------------------------------------------------------------
# GitHub API helpers
# --------------------------------------------------------------------------
class GitHubError(Exception):
    pass


class NotFoundError(GitHubError):
    pass


class RateLimitError(GitHubError):
    pass


# Remaining API calls reported by the last response (None = unknown).
last_rate_remaining = None


def api_get(path, token=""):
    global last_rate_remaining
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "GitHubReleaseTracker",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining is not None and remaining.isdigit():
                last_rate_remaining = int(remaining)
            return json.load(resp)
    except urllib.error.HTTPError as e:
        remaining = e.headers.get("X-RateLimit-Remaining") if e.headers else None
        if e.code in (403, 429) and remaining == "0":
            reset = e.headers.get("X-RateLimit-Reset", "")
            when = ""
            if reset.isdigit():
                when = " Resets at " + datetime.fromtimestamp(int(reset)).strftime("%H:%M") + "."
            last_rate_remaining = 0
            raise RateLimitError("GitHub API rate limit reached." + when +
                                 " Add a token in Settings for a higher limit.")
        if e.code == 404:
            raise NotFoundError("Not found (wrong name, or a private repository).")
        if e.code == 401:
            raise GitHubError("GitHub rejected the token (401). Check it in Settings.")
        raise GitHubError("GitHub returned HTTP %d." % e.code)
    except urllib.error.URLError as e:
        raise GitHubError("Network error: %s" % e.reason)
    except (TimeoutError, OSError) as e:
        raise GitHubError("Network error: %s" % e)
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


def _newest_release(owner, repo, token):
    """Newest non-draft release, pre-releases included. None if there are none."""
    try:
        data = api_get("/repos/%s/%s/releases?per_page=10" % (owner, repo), token)
    except NotFoundError:
        return None
    for r in data:
        if not r.get("draft"):
            return _release_dict(r)
    return None


def _newest_tag(owner, repo, token):
    """First tag GitHub returns. Used only when no GitHub Release exists at all.

    Caveat: the tags endpoint does not guarantee newest-first ordering, and
    tags carry no publish date.
    """
    try:
        data = api_get("/repos/%s/%s/tags?per_page=1" % (owner, repo), token)
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
    }


def fetch_latest_release(owner, repo, token="", include_prereleases=False):
    """Return the latest version info dict, or None if the project has nothing.

    Order of preference:
      1. newest stable GitHub Release (or newest incl. pre-releases if enabled)
      2. newest pre-release, when no stable release exists
      3. newest git tag, when no GitHub Release exists at all
    """
    if not include_prereleases:
        try:
            return _release_dict(api_get("/repos/%s/%s/releases/latest" % (owner, repo), token))
        except NotFoundError:
            pass  # no stable release; fall through to pre-releases / tags
    rel = _newest_release(owner, repo, token)
    if rel:
        return rel
    return _newest_tag(owner, repo, token)


FEED_NS = "{http://www.w3.org/2005/Atom}"


def fetch_latest_from_feed(owner, repo):
    """Newest release from the public releases.atom feed (no token, no API quota).

    The feed lists every published release, pre-releases included, newest first.
    It does not say which entries are pre-releases. Returns None if it is empty.
    """
    url = "https://github.com/%s/%s/releases.atom" % (owner, repo)
    req = urllib.request.Request(url, headers={
        "User-Agent": "GitHubReleaseTracker",
        "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFoundError("Not found (wrong name, or a private repository).")
        if e.code == 429:
            raise GitHubError("GitHub is rate-limiting the release feed (429). Try again later.")
        raise GitHubError("Release feed returned HTTP %d." % e.code)
    except urllib.error.URLError as e:
        raise GitHubError("Network error: %s" % e.reason)
    except (TimeoutError, OSError) as e:
        raise GitHubError("Network error: %s" % e)
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise GitHubError("Release feed was not valid XML.")
    entry = root.find(FEED_NS + "entry")
    if entry is None:
        return None
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


def get_latest(owner, repo, token="", include_prereleases=True):
    """Feed first (free, no quota); GitHub API as fallback.

    Stable-only mode needs the API, because the feed does not mark pre-releases.
    """
    if include_prereleases:
        try:
            rel = fetch_latest_from_feed(owner, repo)
            if rel:
                return rel
        except GitHubError:
            pass  # feed unavailable or repo has no releases: try the API
    return fetch_latest_release(owner, repo, token, include_prereleases)


def apply_result(p, latest, err, now):
    """Store one check result on project p, without inventing false updates."""
    p["last_checked"] = now
    if err:
        p["error"] = err
        return
    p["error"] = None
    if latest:
        if p.get("seen_tag") and p["seen_tag"] == latest["tag"]:
            # Same release as the one already seen; only the ID scheme differs
            # (API release ID vs feed entry ID), so carry the acknowledgement over.
            p["seen_id"] = latest["id"]
        elif p.get("fmt") != 2 and p.get("seen_id") is None:
            # Entry saved by an older version that found nothing: treat what
            # exists now as the baseline instead of flagging it.
            p["seen_id"], p["seen_tag"] = latest["id"], latest["tag"]
    p["latest"] = latest
    p["fmt"] = 2


# --------------------------------------------------------------------------
# Storage, import and export (all input is treated as untrusted)
# --------------------------------------------------------------------------
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def _s(value, limit=300):
    return value.strip()[:limit] if isinstance(value, str) else ""


def safe_github_url(url, fallback):
    """Only ever open https://github.com/... links, whatever a JSON file says."""
    if (isinstance(url, str) and url.startswith("https://github.com/") and len(url) < 500
            and not any(c.isspace() for c in url)):
        return url
    return fallback


def _id_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    return value[:300] if isinstance(value, str) else value


def normalize_release(r, owner, repo):
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
        "url": safe_github_url(r.get("url"), "https://github.com/%s/%s/releases" % (owner, repo)),
        "prerelease": bool(r.get("prerelease")),
        "source": source if source in ("release", "tag", "feed") else "release",
    }


def normalize_project(raw):
    """Return a clean project dict from untrusted input, or None if unusable."""
    if isinstance(raw, str):
        parsed = parse_repo(raw)
        if not parsed:
            return None
        raw = {"owner": parsed[0], "repo": parsed[1]}
    if not isinstance(raw, dict):
        return None
    owner, repo = raw.get("owner"), raw.get("repo")
    if not (isinstance(owner, str) and isinstance(repo, str)
            and NAME_RE.match(owner) and NAME_RE.match(repo)):
        return None
    fmt = raw.get("fmt")
    return {
        "owner": owner,
        "repo": repo,
        "title": _s(raw.get("title"), 200) or repo,
        "description": _s(raw.get("description"), 500),
        "html_url": safe_github_url(raw.get("html_url"), "https://github.com/%s/%s" % (owner, repo)),
        "include_prereleases": bool(raw.get("include_prereleases", True)),
        "fmt": fmt if fmt == 2 else None,
        "latest": normalize_release(raw.get("latest"), owner, repo),
        "seen_id": _id_value(raw.get("seen_id")),
        "seen_tag": _s(raw.get("seen_tag"), 200) or None,
        "last_checked": _s(raw.get("last_checked"), 40),
        "error": _s(raw.get("error"), 300) or None,
    }


def parse_import(raw):
    """Return (projects, skipped_count), or (None, 0) if there is no project list.

    Accepts this app's file ({"projects": [...]}), a bare list, and lists of
    plain "owner/repo" strings or GitHub URLs.
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
    """Export payload. The access token is deliberately never included."""
    return {
        "app": APP_NAME,
        "format": 2,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "projects": projects,
    }


SORTABLE = ("name", "repo", "published", "status")  # columns whose header can be clicked


def _title_key(p):
    return (p.get("title") or p["repo"]).casefold()


def status_rank(p):
    """Order of the Status column. Same precedence as status_text()."""
    if p.get("error"):
        return 1                      # Error
    if not p.get("latest"):
        return 2                      # No releases published
    return 0 if has_update(p) else 3  # Update available / Up to date


def sort_projects(projects, col, asc):
    """Return projects sorted by column. col "" = default (updates first, then A-Z).

    Projects without a publish date (no release, or a tag) always stay at the
    bottom for "published", whichever direction is chosen.
    Status: ascending = Update available, Error, No releases, Up to date;
    descending = the reverse, so "Up to date" comes first. Projects with the
    same status are always A-Z.
    """
    if col == "status":
        sign = 1 if asc else -1
        return sorted(projects, key=lambda p: (sign * status_rank(p), _title_key(p), project_key(p)))
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
    return sorted(projects, key=lambda p: (not has_update(p), _title_key(p)))


def default_data():
    return {"settings": {"token": "", "check_on_launch": False, "theme": "",
                         "sort_col": "", "sort_asc": True}, "projects": []}


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
    projects, _ = parse_import(d)
    base["projects"] = projects or []
    return base


def write_json_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def save_data(data):
    write_json_atomic(DATA_FILE, data)


def project_key(p):
    return ("%s/%s" % (p["owner"], p["repo"])).lower()


def has_update(p):
    latest = p.get("latest")
    return bool(latest) and latest.get("id") != p.get("seen_id")


def status_text(p):
    if p.get("error"):
        return "Error: " + p["error"]
    latest = p.get("latest")
    if not latest:
        return "No releases published"
    if has_update(p):
        old = p.get("seen_tag")
        new = latest.get("tag") or latest.get("name") or "new release"
        return "Update available: %s -> %s" % (old, new) if old else "Update available: " + new
    return "Up to date"


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------
THEMES = {
    "light": dict(bg="#f3f3f3", fg="#1b1b1b", field="#ffffff", sel_bg="#0078d4", sel_fg="#ffffff",
                  head_bg="#e5e5e5", btn_bg="#e1e1e1", btn_active="#d0d0d0", border="#bdbdbd",
                  update_bg="#fff3cd", update_fg="#1b1b1b", error_fg="#b00020",
                  none_fg="#777777", sub_fg="#666666"),
    "dark": dict(bg="#202124", fg="#e8eaed", field="#2b2d31", sel_bg="#2f6fbf", sel_fg="#ffffff",
                 head_bg="#33363b", btn_bg="#3a3d42", btn_active="#4a4d52", border="#4a4d52",
                 update_bg="#4d4210", update_fg="#ffe9a6", error_fg="#ff8a80",
                 none_fg="#9aa0a6", sub_fg="#9aa0a6"),
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
# GUI
# --------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1260x560")  # replaced below by a screen-aware size
        self.data = load_data()
        self.theme_name = self.data["settings"].get("theme") or system_theme()
        self.sort_col = self.data["settings"].get("sort_col") or ""
        self.sort_asc = self.data["settings"].get("sort_asc") is not False
        self.busy = False
        self.q = queue.Queue()
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
        w = max(min(1260, sw - 40), min_w)
        h = max(min(560, sh - 120), min_h)
        self.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        self.after(100, self._poll)
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
        ttk.Label(top, text="GitHub project (URL or owner/repo):").pack(side="left")
        self.entry = ttk.Entry(top)
        self.entry.pack(side="left", fill="x", expand=True, padx=8)
        self.entry.bind("<Return>", lambda e: self.add_project())
        self.btn_add = ttk.Button(top, text="Add project", command=self.add_project)
        self.btn_add.pack(side="left")

        bar = ttk.Frame(self, padding=(10, 4, 10, 6))
        bar.pack(fill="x")
        self.toolbar = bar
        self.btn_check = ttk.Button(bar, text="Check for updates", command=self.check_updates)
        self.btn_check.pack(side="left")
        ttk.Button(bar, text="Mark as seen", command=self.mark_seen).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Open release page", command=self.open_release).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Remove", command=self.remove_selected).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Settings", command=self.open_settings).pack(side="right")
        self.btn_theme = ttk.Button(bar, text="Dark mode", command=self.toggle_theme)
        self.btn_theme.pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="Export", command=self.export_json).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="Import", command=self.import_json).pack(side="right", padx=(0, 8))

        frame = ttk.Frame(self, padding=(10, 0, 10, 0))
        frame.pack(fill="both", expand=True)
        cols = ("name", "repo", "release", "published", "status", "checked")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        heads = [
            ("name", "Project", 230, 120),
            ("repo", "Repository", 280, 120),
            ("release", "Current release", 150, 90),
            ("published", "Published", 125, 115),  # wide enough for the sort arrow
            ("status", "Status", 260, 120),
            ("checked", "Last checked", 140, 110),
        ]
        self.head_text = {cid: text for cid, text, _w, _mw in heads}
        for cid, text, w, mw in heads:
            if cid in SORTABLE:  # Current release / Last checked: not clickable
                self.tree.heading(cid, text=text, command=lambda c=cid: self.sort_by(c))
            else:
                self.tree.heading(cid, text=text)
            self.tree.column(cid, width=w, minwidth=mw, stretch=(cid == "status"))
        self.update_headings()
        # Grid (not pack) so the scrollbars always keep their own space: with pack the
        # list took the full width of its columns and pushed the scrollbar out of view.
        self.vsb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._popup)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())

        self.menu = tk.Menu(self, tearoff=0)
        self.pre_var = tk.BooleanVar(value=False)
        self.menu.add_command(label="Open release page", command=self.open_release)
        self.menu.add_command(label="Open repository", command=self.open_repo)
        self.menu.add_command(label="Mark as seen", command=self.mark_seen)
        self.menu.add_checkbutton(label="Include pre-releases", variable=self.pre_var,
                                  command=self.toggle_prerelease)
        self.menu.add_separator()
        self.menu.add_command(label="Remove", command=self.remove_selected)

        self.status = tk.StringVar(value="Add a project to get started.")
        ttk.Label(self, textvariable=self.status, anchor="w", padding=(10, 6)).pack(fill="x")

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
                    padding=(6, 4))
        s.map("Treeview.Heading", background=[("active", c["btn_active"])])
        for name in ("TScrollbar", "Vertical.TScrollbar"):
            s.configure(name, background=c["btn_bg"], troughcolor=c["bg"], arrowcolor=c["fg"],
                        bordercolor=c["bg"], lightcolor=c["btn_bg"], darkcolor=c["btn_bg"])
            s.map(name, background=[("active", c["btn_active"])])
        self.tree.tag_configure("update", background=c["update_bg"], foreground=c["update_fg"])
        self.tree.tag_configure("error", foreground=c["error_fg"])
        self.tree.tag_configure("none", foreground=c["none_fg"])
        self.menu.configure(bg=c["field"], fg=c["fg"], activebackground=c["sel_bg"],
                            activeforeground=c["sel_fg"], bd=0)
        self.btn_theme.configure(text="Light mode" if self.theme_name == "dark" else "Dark mode")
        self.arrow_up = self._triangle(True, c["fg"])      # sort arrows follow the theme color
        self.arrow_down = self._triangle(False, c["fg"])
        self.update_headings()
        set_titlebar_dark(self, self.theme_name == "dark")

    def toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.data["settings"]["theme"] = self.theme_name
        self.persist()
        self.apply_theme()
        self.set_status("%s mode." % self.theme_name.capitalize())

    # ---- helpers ---------------------------------------------------------
    def token(self):
        return (self.data["settings"].get("token") or "").strip()

    def set_status(self, text):
        self.status.set(text)

    def set_busy(self, busy, text=None):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn_add.configure(state=state)
        self.btn_check.configure(state=state)
        if text:
            self.set_status(text)

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
            except Exception as e:  # noqa: BLE001
                self.set_busy(False, "Internal error: %s" % e)
        self.after(100, self._poll)

    def selected_projects(self):
        keys = set(self.tree.selection())
        return [p for p in self.data["projects"] if project_key(p) in keys]

    def persist(self):
        try:
            save_data(self.data)
        except OSError as e:
            messagebox.showerror(APP_NAME, "Could not save projects.json:\n%s" % e)

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
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        projects = sort_projects(self.data["projects"], self.sort_col, self.sort_asc)
        for p in projects:
            latest = p.get("latest") or {}
            release = latest.get("tag") or latest.get("name") or ""
            if latest.get("source") == "tag":
                release += " (tag)"
            elif latest.get("prerelease"):
                release += " (pre-release)"
            if p.get("error"):
                tag = "error"
            elif has_update(p):
                tag = "update"
            elif not latest:
                tag = "none"
            else:
                tag = ""
            checked = (p.get("last_checked") or "")[:16].replace("T", " ")
            self.tree.insert("", "end", iid=project_key(p), tags=(tag,) if tag else (), values=(
                p.get("title") or p["repo"],
                "%s/%s" % (p["owner"], p["repo"]),
                release or "-",
                (latest.get("published_at") or "")[:10] or "-",
                status_text(p),
                checked or "never",
            ))
        keep = [k for k in selected if self.tree.exists(k)]
        if keep:
            self.tree.selection_set(keep)

    def _on_double_click(self, event):
        """Open the release page only for a double-click on a project row.

        A fast second click on a column header (or on its resize edge, or on
        empty space) must not open anything.
        """
        if self.tree.identify_region(event.x, event.y) == "cell" and self.tree.identify_row(event.y):
            self.open_release()

    def _on_select(self, _event=None):
        sel = self.selected_projects()
        if len(sel) == 1:
            p = sel[0]
            if p.get("error"):
                self.set_status(p["error"])
            elif p.get("description"):
                self.set_status(p["description"])

    def _popup(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            sel = self.selected_projects()
            if sel:
                self.pre_var.set(bool(sel[0].get("include_prereleases")))
            self.menu.tk_popup(event.x_root, event.y_root)

    # ---- actions ---------------------------------------------------------
    def add_project(self):
        if self.busy:
            return
        parsed = parse_repo(self.entry.get())
        if not parsed:
            messagebox.showerror(APP_NAME, "Enter a GitHub URL such as\nhttps://github.com/owner/repo\nor just owner/repo.")
            return
        owner, repo = parsed
        if any(project_key(p) == ("%s/%s" % (owner, repo)).lower() for p in self.data["projects"]):
            messagebox.showinfo(APP_NAME, "%s/%s is already in the list." % (owner, repo))
            return
        token = self.token()
        self.set_busy(True, "Adding %s/%s ..." % (owner, repo))

        def work():
            latest = get_latest(owner, repo, token, True)
            try:
                info = fetch_repo_info(owner, repo, token)
            except NotFoundError:
                raise
            except GitHubError:
                # API unavailable (e.g. rate-limited): the release feed is enough.
                info = {"owner": owner, "repo": repo, "title": repo, "description": "",
                        "html_url": "https://github.com/%s/%s" % (owner, repo)}
            return info, latest

        self.run_async(work, self._added)

    def _added(self, result, exc):
        self.set_busy(False)
        if exc:
            self.set_status("Could not add project.")
            messagebox.showerror(APP_NAME, str(exc))
            return
        info, latest = result
        p = dict(info)
        if any(project_key(x) == project_key(p) for x in self.data["projects"]):
            self.set_status("Already in the list.")
            return
        p.update({
            "include_prereleases": True,  # "whatever is newest", as on the Releases page
            "fmt": 2,
            "latest": latest,
            # Baseline: the release that exists now counts as already seen.
            "seen_id": latest["id"] if latest else None,
            "seen_tag": latest["tag"] if latest else None,
            "last_checked": datetime.now().isoformat(timespec="seconds"),
            "error": None,
        })
        self.data["projects"].append(p)
        self.persist()
        self.entry.delete(0, "end")
        self.render()
        if latest:
            self.set_status("Added %s - current release %s." % (p["title"], latest["tag"] or latest["name"]))
        else:
            self.set_status("Added %s - it has no published releases yet." % p["title"])

    def check_updates(self):
        if self.busy:
            return
        if not self.data["projects"]:
            self.set_status("Nothing to check - add a project first.")
            return
        token = self.token()
        snapshot = [(p["owner"], p["repo"], bool(p.get("include_prereleases"))) for p in self.data["projects"]]
        self.set_busy(True, "Checking %d project(s) ..." % len(snapshot))

        def work():
            out = []
            for owner, repo, inc in snapshot:
                key = ("%s/%s" % (owner, repo)).lower()
                try:
                    out.append((key, get_latest(owner, repo, token, inc), None))
                except RateLimitError as e:
                    out.append((key, None, str(e)))
                    break  # no point continuing
                except GitHubError as e:
                    out.append((key, None, str(e)))
            return out

        self.run_async(work, self._checked)

    def _checked(self, result, exc):
        self.set_busy(False)
        if exc:
            self.set_status("Check failed: %s" % exc)
            return
        now = datetime.now().isoformat(timespec="seconds")
        by_key = {project_key(p): p for p in self.data["projects"]}
        errors = 0
        for key, latest, err in result:
            p = by_key.get(key)
            if not p:
                continue
            apply_result(p, latest, err, now)
            if err:
                errors += 1
        self.persist()
        self.render()
        updates = sum(1 for p in self.data["projects"] if has_update(p))
        msg = "Checked %d project(s): %d update(s) available" % (len(result), updates)
        if errors:
            msg += ", %d error(s)" % errors
        if last_rate_remaining is not None:
            msg += ". API calls left this hour: %d" % last_rate_remaining
        self.set_status(msg + ".")

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
        self.set_status("Marked %d project(s) as seen." % n if n else "No updates to mark in the selection.")

    def open_release(self):
        sel = self.selected_projects()
        if not sel:
            self.set_status("Select a project first.")
            return
        p = sel[0]
        fallback = "https://github.com/%s/%s/releases" % (p["owner"], p["repo"])
        webbrowser.open(safe_github_url((p.get("latest") or {}).get("url"), fallback))

    def open_repo(self):
        sel = self.selected_projects()
        if sel:
            p = sel[0]
            webbrowser.open(safe_github_url(p.get("html_url"), "https://github.com/%s/%s" % (p["owner"], p["repo"])))

    def toggle_prerelease(self):
        sel = self.selected_projects()
        for p in sel:
            p["include_prereleases"] = self.pre_var.get()
        self.persist()
        if self.pre_var.get():
            self.set_status("Pre-releases included (uses the free release feed). Click \"Check for updates\" to apply.")
        else:
            self.set_status("Stable-only mode uses the GitHub API, which is rate-limited without a token. "
                            "Click \"Check for updates\" to apply.")

    def remove_selected(self):
        sel = self.selected_projects()
        if not sel:
            self.set_status("Select a project first.")
            return
        names = ", ".join(p.get("title") or p["repo"] for p in sel[:3]) + ("..." if len(sel) > 3 else "")
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

        ttk.Label(body, text="GitHub personal access token (optional)").grid(row=0, column=0, sticky="w")
        tok = tk.StringVar(value=self.data["settings"].get("token", ""))
        ent = ttk.Entry(body, textvariable=tok, show="*", width=52)
        ent.grid(row=1, column=0, sticky="we", pady=(2, 2))
        ttk.Label(body, style="Sub.TLabel", wraplength=420, justify="left",
                  text="Not needed for normal use: releases are read from GitHub's public feed. "
                       "A token only helps if the feed is blocked or for stable-only mode. "
                       "It is stored in plain text in projects.json and is never written to "
                       "exported files.").grid(row=2, column=0, sticky="w", pady=(0, 10))
        launch = tk.BooleanVar(value=bool(self.data["settings"].get("check_on_launch")))
        ttk.Checkbutton(body, text="Check for updates when the app starts", variable=launch).grid(
            row=3, column=0, sticky="w")

        def save():
            self.data["settings"]["token"] = tok.get().strip()
            self.data["settings"]["check_on_launch"] = launch.get()
            self.persist()
            win.destroy()
            self.set_status("Settings saved.")

        btns = ttk.Frame(body)
        btns.grid(row=4, column=0, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=save).pack(side="right", padx=(0, 8))
        set_titlebar_dark(win, self.theme_name == "dark")
        win.grab_set()
        ent.focus_set()


def main():
    try:  # crisp text on high-DPI Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - not Windows / not available
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
