"""Set up the Claude tab inside SolidWorks on this Windows user, in one run (and again after every update).

    python install_panel.py            install / update, start the tab now, start it at every Windows sign-in
    python install_panel.py --check    only report: installed version, watcher running, Claude Code found
    python install_panel.py --remove   stop the tab and remove the sign-in shortcut (files stay)

What it does (no admin rights, nothing outside the user's profile):
  1. pywin32 present (installs it with pip --user if missing)
  2. copies this skill to ~/.solidworks-api/app  - a stable place the tab runs from, wherever the skill itself
     lives (~/.claude/skills, a Claude app upload, a project folder)
  3. stops an older tab still running (it keeps the old code in memory: the classic "tab is still the old one")
  4. a shortcut in the Windows Startup folder that starts the tab watcher at sign-in
  5. starts the watcher now: the tab appears in the SolidWorks Task Pane ~10 s after SolidWorks is open
  6. writes ~/.solidworks-api/swpanel/installed.json  {version, app, time}  (SKILL.md checks it every session)
Prints one summary line per step; exit code 0 = tab ready.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
HOME = os.path.join(os.path.expanduser("~"), ".solidworks-api")
APP = os.path.join(HOME, "app")
PANEL = os.path.join(HOME, "swpanel")
STOP = os.path.join(PANEL, "taskpane.stop")
MARK = os.path.join(PANEL, "installed.json")
STARTUP = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
                       "Claude SolidWorks tab.lnk")


def version(skill_dir):
    try:
        with open(os.path.join(skill_dir, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "?"


def say(ok, text):
    print(("OK   " if ok else "FAIL ") + text, flush=True)


def ensure_pywin32():
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        pass
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "--quiet", "pywin32", "numpy"])
    if r.returncode:
        return False
    import site
    import importlib
    for p in (site.getusersitepackages(),):
        for sub in ("", "win32", os.path.join("win32", "lib"), "pywin32_system32"):
            q = os.path.join(p, sub)
            if os.path.isdir(q) and q not in sys.path:
                sys.path.append(q)
    if hasattr(os, "add_dll_directory"):
        d = os.path.join(site.getusersitepackages(), "pywin32_system32")
        if os.path.isdir(d):
            os.add_dll_directory(d)
    importlib.invalidate_caches()
    try:
        import win32com.client  # noqa: F401,F811
        return True
    except ImportError:
        return False


def pythonw():
    w = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return w if os.path.exists(w) else sys.executable


def panel_processes():
    """PIDs of python processes running the tab or its worker (any copy of the skill)."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
          "Where-Object { $_.CommandLine -match 'swpanel_taskpane|swpanel_worker' } | "
          "ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(x) for x in out.split() if x.isdigit() and int(x) != os.getpid()]


def stop_old():
    os.makedirs(PANEL, exist_ok=True)
    open(STOP, "w").close()
    pids = panel_processes()
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    time.sleep(1 if pids else 0)
    if os.path.exists(STOP):
        os.remove(STOP)
    return len(pids)


def copy_app():
    if os.path.normcase(os.path.abspath(SKILL)) == os.path.normcase(os.path.abspath(APP)):
        return
    tmp = APP + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(SKILL, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.rmtree(APP, ignore_errors=True)
    os.replace(tmp, APP)


def shortcut():
    import win32com.client
    sh = win32com.client.Dispatch("WScript.Shell")
    lnk = sh.CreateShortCut(STARTUP)
    lnk.TargetPath = pythonw()
    lnk.Arguments = '"%s" watch' % os.path.join(APP, "scripts", "swpanel_taskpane.py")
    lnk.WorkingDirectory = os.path.join(APP, "scripts")
    lnk.Description = "Adds the Claude tab to SolidWorks"
    lnk.Save()


def start_watcher():
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([pythonw(), os.path.join(APP, "scripts", "swpanel_taskpane.py"), "watch"],
                     cwd=os.path.join(APP, "scripts"), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        time.sleep(0.5)
        if panel_processes():
            return True
    return False


def find_claude():
    hits = glob.glob(os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude-code", "*", "*", "claude.exe"))
    local = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    return (hits and hits[0]) or (os.path.exists(local) and local) or shutil.which("claude")


def sw_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe"], capture_output=True, text=True).stdout
        return "SLDWORKS.exe" in out
    except OSError:
        return False


def check():
    mark = {}
    try:
        with open(MARK, encoding="utf-8") as f:
            mark = json.load(f)
    except (OSError, ValueError):
        pass
    running = bool(panel_processes())
    say(mark.get("version") == version(SKILL),
        f"installed tab version {mark.get('version', 'none')}, this skill {version(SKILL)}")
    say(running, "tab watcher running" if running else "tab watcher NOT running")
    say(os.path.exists(STARTUP), "starts at Windows sign-in" if os.path.exists(STARTUP) else "no sign-in shortcut")
    c = find_claude()
    say(bool(c), f"Claude Code: {c or 'not found'}")
    return 0 if running and mark.get("version") == version(SKILL) else 1


def main():
    if os.name != "nt":
        say(False, "Windows only (SolidWorks)")
        return 2
    if "--check" in sys.argv:
        return check()
    if "--remove" in sys.argv:
        n = stop_old()
        if os.path.exists(STARTUP):
            os.remove(STARTUP)
        say(True, f"tab stopped ({n} process(es)), sign-in shortcut removed")
        return 0

    if not ensure_pywin32():
        say(False, "pywin32 could not be installed: run  python -m pip install pywin32  and try again")
        return 1
    say(True, "pywin32")
    n = stop_old()
    say(True, f"old tab stopped ({n} process(es))" if n else "no old tab running")
    copy_app()
    say(True, f"tab files -> {APP}  (version {version(SKILL)})")
    try:
        shortcut()
        say(True, "starts automatically at Windows sign-in")
    except Exception as e:  # noqa: BLE001 - shortcut is a convenience; the tab works without it
        say(False, f"sign-in shortcut not created ({e!r:.120}); start by hand: install_panel.py")
    ok = start_watcher()
    say(ok, "tab watcher running" if ok else "tab watcher did not start: see ~/.solidworks-api/swpanel/taskpane.log")
    c = find_claude()
    say(bool(c), f"Claude Code found: {c}" if c else
        "Claude Code not found: install the Claude app (claude.com/download) or Claude Code, then reopen SolidWorks")
    os.makedirs(PANEL, exist_ok=True)
    with open(MARK, "w", encoding="utf-8") as f:
        json.dump({"version": version(SKILL), "app": APP, "time": time.strftime("%Y-%m-%d %H:%M")}, f)
    if sw_running():
        print("NEXT SolidWorks is open: the Claude tab appears in the Task Pane (right side) within ~10 s.")
    else:
        print("NEXT Open SolidWorks: the Claude tab appears in the Task Pane (right side) ~10 s after it starts.")
    print("NEXT First time only: click the 'connect to Claude' button in the tab.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
