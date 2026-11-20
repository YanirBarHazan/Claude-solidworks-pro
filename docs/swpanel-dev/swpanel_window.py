"""Claude panel for SolidWorks - a small always-on-top Python window beside SolidWorks (no install, no code inside
SolidWorks). Stage 0: request text box + Send, status polled from status.json every 2 s, live SolidWorks state
(active document, selection count) read over COM in a worker thread so a busy SolidWorks never freezes the window.

    pythonw swpanel_window.py            open the panel (one instance; a second start just exits)

Files (UTF-8, no BOM, written as .tmp then renamed) in %USERPROFILE%\\.solidworks-api\\swpanel\\ - see swpanel/STAGE0.md.
SW_REQUIRE_REV (default "27." = 2019) guards the SolidWorks version.
"""
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

PANEL = os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel")
REQUIRE = os.environ.get("SW_REQUIRE_REV", "27.")
POLL_MS = 2000
TITLE = "Claude - SolidWorks"

T = {  # UI strings (Hebrew UI; code and files stay English)
    "req": "בקשה ל-Claude:",
    "send": "שלח",
    "waiting": "ממתין לסטטוס...",
    "sent": "נשלח ({n} תווים)",
    "empty": "אין טקסט לשליחה",
    "sw_none": "SolidWorks לא מחובר",
    "sw_rev": "גרסת SolidWorks {rev} - נדרש {need}*",
    "sw_ok": "מסמך: {doc}  |  נבחרו: {n}",
    "sw_nodoc": "אין מסמך פעיל",
    "sw_busy": "SolidWorks עסוק...",
}


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def single_instance():
    import win32api
    import win32event
    import winerror
    h = win32event.CreateMutex(None, False, "Local\\swpanel_window")
    return h, win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS


def _get(obj, name):
    """No-argument COM member: late binding exposes some methods (RevisionNumber, GetTitle) as properties."""
    v = getattr(obj, name)
    return v() if callable(v) else v


class SwWatcher(threading.Thread):
    """Own COM apartment; reads SolidWorks state every second and reports it through a queue.
    A COM call into a busy SolidWorks blocks only this thread."""

    def __init__(self, out):
        super().__init__(daemon=True)
        self.out = out
        self.stop = threading.Event()
        self.busy_since = None

    def run(self):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        sw = None
        while not self.stop.is_set():
            t = time.time()
            try:
                if sw is None:
                    sw = win32com.client.Dispatch(
                        pythoncom.GetActiveObject("SldWorks.Application").QueryInterface(pythoncom.IID_IDispatch))
                    rev = _get(sw, "RevisionNumber")
                    if REQUIRE and not rev.startswith(REQUIRE):
                        self.out.put(("sw", T["sw_rev"].format(rev=rev, need=REQUIRE), None))
                        sw = None
                        self.stop.wait(5)
                        continue
                doc = sw.ActiveDoc
                if doc is None:
                    info = {"doc": None, "n": 0}
                    msg = T["sw_nodoc"]
                else:
                    n = doc.SelectionManager.GetSelectedObjectCount2(-1)
                    info = {"doc": _get(doc, "GetTitle"), "n": n}
                    msg = T["sw_ok"].format(doc=info["doc"], n=n)
                info["call_s"] = round(time.time() - t, 3)
                self.out.put(("sw", msg, info))
            except Exception as e:  # SolidWorks closed / restarted / not started
                sw = None
                self.out.put(("sw", T["sw_none"], {"error": str(e)[:120]}))
                self.stop.wait(3)
            self.stop.wait(1.0)
        pythoncom.CoUninitialize()


class Panel:
    def __init__(self, root):
        self.root = root
        self.ticks = 0
        self.status_mtime = None
        self.status_text = T["waiting"]
        self.sw_info = None
        self.q = queue.Queue()
        root.title(TITLE)
        root.attributes("-topmost", True)
        root.resizable(True, True)
        f = tkfont.Font(family="Segoe UI", size=10)
        pad = {"padx": 6, "pady": 3}
        tk.Label(root, text=T["req"], font=f, anchor="e").pack(fill="x", **pad)
        self.txt = tk.Text(root, height=4, width=40, font=f, wrap="word")
        self.txt.tag_configure("rtl", justify="right")
        self.txt.bind("<KeyRelease>", lambda e: self.txt.tag_add("rtl", "1.0", "end"))
        self.txt.pack(fill="both", expand=True, **pad)
        row = tk.Frame(root)
        row.pack(fill="x", **pad)
        tk.Button(row, text=T["send"], font=f, width=10, command=self.send).pack(side="right")
        self.lbl_status = tk.Label(root, text=self.status_text, font=f, anchor="e", justify="right",
                                   wraplength=300, fg="#1a4d8f")
        self.lbl_status.pack(fill="x", **pad)
        self.lbl_sw = tk.Label(root, text="...", font=f, anchor="e", fg="#555")
        self.lbl_sw.pack(fill="x", **pad)
        self.lbl_tick = tk.Label(root, text="", font=("Segoe UI", 8), anchor="w", fg="#999")
        self.lbl_tick.pack(fill="x", padx=6)
        sw_, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"340x270+{sw_ - 360}+{sh - 360}")
        self.watcher = SwWatcher(self.q)
        self.watcher.start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.drain)
        root.after(POLL_MS, self.tick)

    def send(self):
        text = self.txt.get("1.0", "end").strip()
        if not text:
            self.lbl_status.config(text=T["empty"])
            return
        rid = time.strftime("%Y%m%d-%H%M%S")
        write_json(os.path.join(PANEL, "request.json"),
                   {"schema": "swpanel.request/0", "id": rid, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "text": text, "sw": self.sw_info})
        self.lbl_status.config(text=T["sent"].format(n=len(text)))

    def drain(self):
        try:
            while True:
                _, msg, info = self.q.get_nowait()
                self.lbl_sw.config(text=msg)
                self.sw_info = info
        except queue.Empty:
            pass
        self.root.after(150, self.drain)

    def tick(self):
        self.ticks += 1
        p = os.path.join(PANEL, "status.json")
        try:
            m = os.stat(p).st_mtime_ns
        except OSError:
            m = None
        if m and m != self.status_mtime:
            js = read_json(p)
            if js is not None:
                self.status_mtime = m
                self.status_text = js.get("text", "")
                self.lbl_status.config(text=self.status_text)
        self.lbl_tick.config(text=f"tick {self.ticks}")
        write_json(os.path.join(PANEL, "seen.json"),  # echo for automatic tests
                   {"ticks": self.ticks, "shown": self.lbl_status.cget("text"), "sw": self.sw_info,
                    "time": time.time()})
        self.root.after(POLL_MS, self.tick)

    def close(self):
        self.watcher.stop.set()
        self.root.destroy()


def main():
    os.makedirs(PANEL, exist_ok=True)
    _mutex, first = single_instance()
    if not first:
        return
    root = tk.Tk()
    Panel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
