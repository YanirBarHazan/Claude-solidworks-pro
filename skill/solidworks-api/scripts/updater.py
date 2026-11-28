"""Is there a newer version? Asked by the Claude tab at start and once a day; the user decides in the tab.

    latest(fetch) -> {"version", "ref", "url", "notes"} or None    the newest published release (GitHub),
                                                                   else the VERSION on main
    newer(a, b) -> True when version a is newer than b             ("2.10.0" > "2.9.1")
    due(state, now) -> True when a check is due                    once a day, or after a "not now" day
    start_update(ref)                                              runs the installer for that release in its own
                                                                   window; it replaces the tab and starts the new one
Network: two public GET requests to GitHub, no account, nothing about the user is sent."""
import json
import os
import re
import subprocess
import time
import urllib.request

REPO = "YanirBarHazan/Claude-solidworks-pro"
RELEASES = f"https://api.github.com/repos/{REPO}/releases/latest"
MAIN_VERSION = f"https://raw.githubusercontent.com/{REPO}/main/skill/solidworks-api/VERSION"
DAY = 24 * 3600


def _get(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "claude-solidworks-tab",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def parse(v):
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(v or ""))
    return tuple(int(x or 0) for x in m.groups()) if m else None


def newer(a, b):
    pa, pb = parse(a), parse(b)
    return bool(pa and pb and pa > pb)


def latest(fetch=_get):
    """The newest published release; when the repository has none yet, the VERSION on main."""
    try:
        r = json.loads(fetch(RELEASES))
        if parse(r.get("tag_name")) and not r.get("draft") and not r.get("prerelease"):
            return {"version": r["tag_name"].lstrip("v"), "ref": r["tag_name"], "url": r.get("html_url"),
                    "notes": (r.get("body") or "")[:1500]}
    except Exception:
        pass
    try:
        v = fetch(MAIN_VERSION).strip()
        if parse(v):
            return {"version": v, "ref": "main", "url": f"https://github.com/{REPO}/tree/main/docs/changelog",
                    "notes": ""}
    except Exception:
        pass
    return None


def due(state, now=None):
    now = now or time.time()
    if now < state.get("snooze_until", 0):
        return False
    return "checked" not in state or now - state["checked"] >= DAY


def check(current, state_path, fetch=_get, now=None, force=False):
    """-> info dict when a newer version is out and the user has not put it off; writes the check time."""
    try:
        state = json.load(open(state_path, encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not force and not due(state, now):
        return None
    info = latest(fetch)
    state["checked"] = now or time.time()
    state["latest"] = info and info["version"]
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    return info if info and newer(info["version"], current) else None


def snooze(state_path, days=1, now=None):
    try:
        state = json.load(open(state_path, encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state["snooze_until"] = (now or time.time()) + days * DAY
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f)


def update_command(ref):
    """The installer pinned to `ref`, as PowerShell runs it (the same line as the README's pinned install)."""
    if not re.match(r"^[\w.\-/]+$", ref):
        raise ValueError(f"bad ref {ref!r}")
    return (f"$env:SW_INSTALL_REF='{ref}'; Start-Sleep 3; "
            f"irm https://raw.githubusercontent.com/{REPO}/{ref}/install.ps1 | iex")


def start_update(ref):
    """Run the installer in its own window, detached: it stops this tab (which closes itself first), installs
    `ref`, and starts the new tab - it appears again in the Task Pane by itself."""
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(["powershell", "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-c", update_command(ref)],
                     creationflags=flags, close_fds=True)
