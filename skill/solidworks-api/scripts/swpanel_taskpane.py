"""Claude chat INSIDE SolidWorks: a Task Pane tab (right-hand side panel) hosting a local HTML page, driven from
this Python process over COM. No add-in, no C#, no registry: ISldWorks.CreateTaskpaneView2 + AddControl
("Shell.Explorer.2").

Each message typed in the tab runs Claude Code headless (`claude -p`, stream-json) with the solidworks-api skill;
the first message starts a conversation, later ones `--resume` it, so the tab is one continuous chat until
"New chat". Replies, tool steps, approvals ([[APPROVE]] -> Approve / Reject buttons), Stop, save folder and file
attachments are handled here. All DOM access stays on this (main) thread; Claude runs in a worker thread.

    pythonw swpanel_taskpane.py          add the tab and keep it alive (the tab lives as long as this process)
    python  swpanel_taskpane.py stop     remove the tab and end the process

State: %USERPROFILE%\\.solidworks-api\\swpanel\\ (settings.json, chat.log.jsonl, taskpane.log, agent\\ = Claude's cwd).
"""
import glob
import html as htmlmod
import json
import os
import queue
import shutil
import struct
import subprocess
import sys
import threading
import time

PANEL = os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel")
AGENT = os.path.join(PANEL, "agent")              # fixed cwd: Claude Code stores conversations per folder
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "swpanel")
REQUIRE = os.environ.get("SW_REQUIRE_REV", "27.")
STOP = os.path.join(PANEL, "taskpane.stop")
SETTINGS = os.path.join(PANEL, "settings.json")
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Claude SolidWorks")
SEL_TYPES = {1: "edge", 2: "face", 3: "vertex", 4: "plane", 5: "axis", 9: "sketch segment", 11: "sketch point",
             20: "component", 22: "feature", 25: "dimension", 31: "sketch"}  # swSelectType_e (subset)
ALLOWED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Skill", "TodoWrite", "Bash(python:*)", "Bash(py:*)", "PowerShell(python:*)", "PowerShell(py:*)",
                 "Bash(ls:*)", "Bash(dir:*)", "Bash(mkdir:*)", "Bash(copy:*)", "Bash(cp:*)", "Bash(tasklist:*)"]
TXT = {
    "hello": "שלום. בחר משהו בסוליד וכתוב מה לעשות.",
    "new": "שיחה חדשה",
    "resumed": "ממשיך את השיחה הקודמת (שיחה חדשה - בכפתור למעלה)",
    "stopped": "נעצר.",
    "no_cli": "Claude Code לא נמצא במחשב (אפליקציית Claude מותקנת?)",
    "login": "Claude לא מחובר - לחץ 'התחבר ל-Claude' (פעם אחת במחשב).",
    "need_login": "כדי שאוכל לעבוד מכאן צריך להתחבר לחשבון Claude פעם אחת במחשב הזה.",
    "login_btn": "התחבר ל-Claude",
    "login_wait": "נפתח דפדפן להתחברות. אשר שם - הלשונית תזהה לבד כשסיימת.",
    "login_ok": "מחובר. אפשר לכתוב.",
    "busy": "Claude עדיין עובד על הבקשה הקודמת.",
    "dir": "תיקיית שמירה: {d}",
    "att": "מצורף: {n}",
    "done": "{s:.0f} שנ'",
    "approved": "אושר",
    "approve_q": "לבצע?",
    "rejected": "נדחה",
}


def log(s):
    with open(os.path.join(PANEL, "taskpane.log"), "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + s + "\n")


def write_json(path, obj):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _get(obj, name):
    """No-argument COM member: late binding exposes some methods as properties."""
    v = getattr(obj, name)
    return v() if callable(v) else v


def find_claude():
    hits = glob.glob(os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude-code", "*", "*", "claude.exe"))
    if hits:
        def ver(p):
            v = os.path.basename(os.path.dirname(os.path.dirname(p)))
            return [int(x) if x.isdigit() else 0 for x in v.split(".")]
        return max(hits, key=lambda p: (ver(p), os.path.getmtime(p)))
    return shutil.which("claude")


def icon_bmp(path):
    w = h = 16
    rows = []
    for y in range(h):
        row = b""
        for x in range(w):
            d = ((x - 7.5) ** 2 + (y - 7.5) ** 2) ** 0.5
            ring = 3.5 <= d <= 5.5 and not (x > 9 and 5 <= y <= 10)
            row += b"\xff\xff\xff" if ring else b"\x8f\x4d\x1a"
        rows.append(row)
    pix = b"".join(reversed(rows))
    with open(path, "wb") as f:
        f.write(struct.pack("<2sIHHI", b"BM", 54 + len(pix), 0, 0, 54))
        f.write(struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pix), 2835, 2835, 0, 0) + pix)


def esc(s):
    return htmlmod.escape(s or "", quote=True)


class ClaudeSession:
    """ONE long-lived headless Claude Code process (stream-json in and out): no start-up per message.
    Restarted with --resume when it died, was stopped, or the allowed folders changed. MCP servers are not
    loaded (--strict-mcp-config): the panel needs none and they cost seconds at start-up."""

    def __init__(self, exe, out, effort="medium"):
        self.exe, self.out, self.effort = exe, out, effort
        self.proc, self.dirs, self.busy, self.t0 = None, None, False, 0.0

    def is_alive(self):
        return self.busy

    def _start(self, session, dirs):
        cmd = [self.exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--append-system-prompt-file", os.path.join(AGENT, "PANEL_PROMPT.md"),
               "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS,
               # PowerShell tool start-up cost ~7 s per call here (profile); Bash runs swx.py in 0.7 s
               "--disallowedTools", "PowerShell",
               # only the built-in tools the tab needs: fixed context 39.5k -> 9.6k tokens per round
               "--tools", "Bash,Read,Write,Edit,Glob,Grep",
               "--effort", self.effort]
        for d in dirs:
            cmd += ["--add-dir", d]
        if session:
            cmd += ["--resume", session]
        self.proc = subprocess.Popen(cmd, cwd=AGENT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        self.dirs = list(dirs)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        log(f"claude process started pid={self.proc.pid} resume={session}")

    def send(self, prompt, session, dirs):
        if self.proc is None or self.proc.poll() is not None or self.dirs != list(dirs):
            self.kill()
            self._start(session, dirs)
        self.busy, self.t0 = True, time.time()
        msg = {"type": "user", "message": {"role": "user", "content": prompt}}
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _read(self, proc):
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    self.out.put(("raw", line[:300]))  # logged, not shown
                    continue
                t = ev.get("type")
                if t == "system" and ev.get("subtype") == "init":
                    self.out.put(("session", ev.get("session_id")))
                elif t == "assistant":
                    for blk in ev.get("message", {}).get("content", []):
                        if blk.get("type") == "text" and blk.get("text", "").strip():
                            self.out.put(("text", blk["text"].strip()))
                        elif blk.get("type") == "tool_use":
                            inp = blk.get("input", {})
                            what = inp.get("description") or inp.get("command") or inp.get("file_path") or                                 inp.get("skill") or inp.get("pattern") or ""
                            self.out.put(("step", f"{blk.get('name')}: {str(what)[:140]}"))
                elif t == "result":
                    self.out.put(("result", {"ok": not ev.get("is_error"), "text": ev.get("result", ""),
                                             "session": ev.get("session_id"), "s": time.time() - self.t0,
                                             "denied": len(ev.get("permission_denials") or []),
                                             "usage": ev.get("usage") or {}, "turns": ev.get("num_turns"),
                                             "cost": ev.get("total_cost_usd")}))
                    for dn in ev.get("permission_denials") or []:
                        self.out.put(("raw", "DENIED " + json.dumps(dn, ensure_ascii=False)[:250]))
                    self.busy = False
                    self.out.put(("end", 0))
        except Exception as e:
            self.out.put(("error", repr(e)[:300]))
        if proc is self.proc and self.busy:      # died in the middle of a turn
            self.busy = False
            self.out.put(("end", proc.poll()))

    def kill(self):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.busy = False


def start_worker():
    """Warm SolidWorks worker (swpanel_worker.py); returns the Popen, or None when one already answers."""
    sys.path.insert(0, HERE)
    import swx
    if swx.call("ping", []).get("ok"):
        return None
    wj = os.path.join(PANEL, "worker.json")
    old = read_json(wj, {}) or {}
    if old.get("pid"):              # a worker of a closed SolidWorks: its connection is dead
        subprocess.run(["taskkill", "/F", "/PID", str(old["pid"])], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if os.path.exists(wj):
        os.remove(wj)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    p = subprocess.Popen([pyw if os.path.exists(pyw) else sys.executable, os.path.join(HERE, "swpanel_worker.py")],
                         creationflags=subprocess.CREATE_NO_WINDOW)
    t = time.time()
    while not os.path.exists(wj) and time.time() - t < 20:
        time.sleep(0.1)
    log(f"worker started pid={p.pid} in {time.time() - t:.1f} s")
    return p


class Bridge:
    def __init__(self, sw, ctl):
        import win32com.client
        self.sw, self.ctl, self.wc = sw, ctl, win32com.client
        self.q = queue.Queue()
        self.run_ = None
        self.claude = None
        self.worker = None
        self.attach = []
        self.sel_info, self.sel_txt = None, ""
        self.set = read_json(SETTINGS, {}) or {}
        self.set.setdefault("save_dir", DEFAULT_DIR)
        os.makedirs(self.set["save_dir"], exist_ok=True)
        self.exe = find_claude()
        self.pending_text = ""
        self.last_request = ""
        self.last_reply = ""

    # ---- page helpers (main thread only) ----
    def doc(self):
        d = self.wc.dynamic.Dispatch(self.ctl.Document)
        d._FlagAsMethod("getElementById")
        return d

    def el(self, i):
        e = self.doc().getElementById(i)
        e._FlagAsMethod("insertAdjacentHTML")
        return e

    def add(self, html_):
        chat = self.el("chat")
        chat.insertAdjacentHTML("beforeEnd", html_)
        chat.scrollTop = chat.scrollHeight

    @staticmethod
    def rich(text):
        """Escape, then the little markdown Claude uses in short replies: **bold**."""
        import re
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text))

    def bubble(self, text, who="ai", t=None, card=""):
        """LEO-style message: avatar, name + time, soft bubble; `card` = buttons inside the bubble."""
        who_cls = who.split()[0]
        err = " err" if "err" in who else ""
        name, av = ("Claude", "C") if who_cls == "ai" else ("אתה", "א")
        tm = t or time.strftime("%H:%M")
        self.add(f'<div class="row {who_cls}"><div class="av">{av}</div><div class="body">'
                 f'<div class="who">{name}<span>{esc(tm)}</span></div>'
                 f'<div class="msg{err}">{self.rich(text)}{card}</div></div></div>')

    def card(self, buttons):
        return '<div class="card">' + "".join(
            f'<button class="{cls}" onclick="act(\'{a}\')">{esc(label)}</button>' for a, label, cls in buttons) + \
            "</div>"

    def sys(self, text):
        self.add(f'<div class="sys"><span>{esc(text)}</span></div>')

    def busy(self, on):
        self.el("busy").style.display = "block" if on else "none"
        self.el("stop").style.display = "inline-block" if on else "none"
        self.el("send").style.display = "none" if on else "inline-block"
        if not on:
            self.el("step").innerText = ""

    def show_info(self):
        self.el("dir").innerText = self.set["save_dir"]
        self.el("att").innerText = TXT["att"].format(n=", ".join(os.path.basename(a) for a in self.attach)) \
            if self.attach else ""

    def save_settings(self):
        write_json(SETTINGS, self.set)

    def chatlog(self, who, text):
        with open(os.path.join(PANEL, "chat.log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "who": who, "text": text,
                                "session": self.set.get("session")}, ensure_ascii=False) + "\n")

    # ---- SolidWorks state ----
    def selection(self):
        try:
            doc = self.sw.ActiveDoc
            if doc is None:
                self.sel_info, self.sel_txt = None, "אין מסמך פעיל"
                return
            sm = doc.SelectionManager
            n = sm.GetSelectedObjectCount2(-1)
            items = [SEL_TYPES.get(sm.GetSelectedObjectType3(i, -1), str(sm.GetSelectedObjectType3(i, -1)))
                     for i in range(1, n + 1)]
            title = _get(doc, "GetTitle")
            path = _get(doc, "GetPathName")
            self.sel_info = {"doc": title, "path": path, "n": n, "types": items}
            self.sel_txt = title + (" | " + ", ".join(items) if items else "")
        except Exception as e:
            self.sel_info, self.sel_txt = {"error": repr(e)[:100]}, "SolidWorks לא זמין"

    # ---- actions ----
    def send(self, text, echo=True):
        if self.run_ and self.run_.is_alive():
            self.sys(TXT["busy"])
            return
        if not self.exe:
            self.bubble(TXT["no_cli"], "ai err")
            return
        self.last_request = text
        if echo:
            self.bubble(text, "me")
        self.chatlog("user", text)
        ctx = {"solidworks_rev": _get(self.sw, "RevisionNumber"), "require_rev": REQUIRE,
               "active_document": self.sel_info, "save_folder": self.set["save_dir"],
               "attached_files": self.attach}
        prompt = (text + "\n\n<swpanel_context>\n" + json.dumps(ctx, ensure_ascii=False, indent=1) +
                  "\n</swpanel_context>")
        self.attach = []
        self.show_info()
        self.last_reply = ""
        if self.claude is None:
            self.claude = ClaudeSession(self.exe, self.q, self.set.get("effort", "medium"))
        self.run_ = self.claude
        try:
            w = start_worker()
            self.worker = w or self.worker
        except Exception as e:
            log(f"worker start failed: {e!r}"[:200])
        self.claude.send(prompt, self.set.get("session"), [self.set["save_dir"]])
        self.busy(True)
        log(f"run: session={self.set.get('session')} chars={len(text)}")

    def pick_folder(self):
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        d = filedialog.askdirectory(parent=r, initialdir=self.set["save_dir"], title="תיקיית שמירה")
        r.destroy()
        if d:
            self.set["save_dir"] = os.path.normpath(d)
            self.save_settings()
            self.show_info()
            self.sys(TXT["dir"].format(d=self.set["save_dir"]))

    def pick_file(self):
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        fs = filedialog.askopenfilenames(parent=r, title="צרף קובץ")
        r.destroy()
        for f in fs or ():
            dst_dir = os.path.join(self.set["save_dir"], "attachments")
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, os.path.basename(f))
            if os.path.normcase(os.path.abspath(f)) != os.path.normcase(os.path.abspath(dst)):
                shutil.copy2(f, dst)
            self.attach.append(dst)
        self.show_info()

    def handle_flag(self, flag):
        if flag == "send":
            req = self.el("req")
            text = (req.value or "").strip()
            if text:
                req.value = ""
                self.send(text)
        elif flag == "stop" and self.run_:
            self.run_.kill()
            if self.worker and self.worker.poll() is None:     # a script may be running in it
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.worker.pid)], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
                self.worker = None
            self.sys(TXT["stopped"])
            self.chatlog("system", "stopped")
        elif flag == "new":
            if self.run_ and self.run_.is_alive():
                self.run_.kill()
            self.set.pop("session", None)
            self.save_settings()
            self.el("chat").innerHTML = ""
            self.sys(TXT["new"])
        elif flag == "folder":
            self.pick_folder()
        elif flag == "file":
            self.pick_file()
        elif flag == "login":
            self.start_login()
        elif flag in ("approve", "reject"):
            self.send(TXT["approved"] if flag == "approve" else TXT["rejected"])

    def handle_event(self, kind, p):
        if kind == "session" and p:
            self.new_session = p          # kept only if the turn succeeds (see "result")
        elif kind == "text":
            if p.startswith("Not logged in"):
                return
            show = p.replace("[[APPROVE]]", "").strip()
            if show:
                self.bubble(show)
            self.last_reply = p
            self.chatlog("claude", p)
        elif kind == "step":
            self.el("step").innerText = p          # one live line under "Claude is working", not a list
        elif kind == "result":
            txt = p.get("text") or ""
            sid = p.get("session") or getattr(self, "new_session", None)
            if p["ok"] and sid and self.set.get("session") != sid:
                self.set["session"] = sid
                self.save_settings()
            if not p["ok"] and "no conversation found" in txt.lower():
                self.set.pop("session", None)      # resumed conversation is gone: next message starts fresh
                self.save_settings()
            if not p["ok"]:
                if "login" in txt.lower():
                    self.offer_login()
                else:
                    self.bubble(txt or "error", "ai err")
            elif txt and txt.strip() != self.last_reply.strip():
                self.bubble(txt.replace("[[APPROVE]]", "").strip())
            self.sys(TXT["done"].format(s=p["s"]) + (f" | {p['denied']} denied" if p.get("denied") else ""))
            if "[[APPROVE]]" in (txt + self.last_reply):
                self.bubble(TXT["approve_q"], card=self.card([("approve", "אשר", "ok"), ("reject", "דחה", "no")]))
            log(f"result ok={p['ok']} s={p['s']:.1f} denied={p.get('denied')}")
            u = p.get("usage") or {}
            tf = os.path.join(PANEL, "tokens.csv")
            new = not os.path.exists(tf)
            with open(tf, "a", encoding="utf-8") as f:   # per request, from Claude Code's own result event
                if new:
                    f.write("time,session,ok,seconds,turns,input,cache_write,cache_read,output,cost_usd,request\n")
                req = (self.last_request or "").replace(",", " ").replace("\n", " ")[:60]
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{p.get('session')},{p['ok']},{p['s']:.1f},"
                        f"{p.get('turns')},{u.get('input_tokens', 0)},{u.get('cache_creation_input_tokens', 0)},"
                        f"{u.get('cache_read_input_tokens', 0)},{u.get('output_tokens', 0)},{p.get('cost')},{req}\n")
        elif kind == "raw":
            log(f"raw: {p}")
        elif kind == "error":
            self.bubble(p, "ai err")
            log(f"error: {p}")
        elif kind == "end":
            self.busy(False)

    # ---- login (claude auth status / login) ----
    def logged_in(self):
        if not self.exe:
            return False
        try:
            r = subprocess.run([self.exe, "auth", "status", "--json"], capture_output=True, encoding="utf-8",
                               errors="replace", timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
            return bool(json.loads(r.stdout).get("loggedIn"))
        except Exception as e:
            log(f"auth status failed: {e!r}"[:200])
            return False

    def offer_login(self):
        self.bubble(TXT["need_login"], card=self.card([("login", TXT["login_btn"], "ok")]))

    def start_login(self):
        # a small console window: the browser opens for the Anthropic sign-in; the window closes by itself
        subprocess.Popen([self.exe, "auth", "login"], cwd=AGENT, creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.sys(TXT["login_wait"])
        self.login_poll = time.time()

    def replay(self):
        sid = self.set.get("session")
        if not sid:
            return False
        rows = []
        try:
            for l in open(os.path.join(PANEL, "chat.log.jsonl"), encoding="utf-8"):
                d = json.loads(l)
                if d.get("session") == sid and d.get("who") in ("user", "claude"):
                    rows.append(d)
        except (OSError, ValueError):
            return False
        for d in rows[-40:]:
            self.bubble(d["text"].replace("[[APPROVE]]", "").strip(), "me" if d["who"] == "user" else "ai",
                        t=d.get("t", "")[11:16])
        if rows:
            self.sys(TXT["resumed"])
        return bool(rows)

    def loop(self):
        self.show_info()
        if not self.replay():
            self.bubble(TXT["hello"])
        self.login_poll = None
        if not self.logged_in():
            self.offer_login()
        last_sel = 0.0
        while not os.path.exists(STOP):
            flag = self.el("flag")
            f = flag.value
            if f:
                flag.value = ""
                self.handle_flag(f)
            inj = os.path.join(PANEL, "inject.json")   # test hook: {"text": ...} or {"flag": ...}
            if os.path.exists(inj):
                js = read_json(inj, {}) or {}
                os.remove(inj)
                if js.get("text"):
                    self.send(js["text"])
                elif js.get("flag"):
                    self.handle_flag(js["flag"])
            try:
                while True:
                    self.handle_event(*self.q.get_nowait())
            except queue.Empty:
                pass
            if self.login_poll and time.time() - self.login_poll >= 3:
                self.login_poll = time.time()
                if self.logged_in():
                    self.login_poll = None
                    self.sys(TXT["login_ok"])
            if time.time() - last_sel >= 1.5:
                last_sel = time.time()
                self.selection()
                self.el("sel").innerText = self.sel_txt
                write_json(os.path.join(PANEL, "seen.json"), {
                    "time": time.time(), "busy": bool(self.run_ and self.run_.is_alive()),
                    "session": self.set.get("session"), "sel": self.sel_txt,
                    "chat_text": self.el("chat").innerText[-1500:]})
            time.sleep(0.15)


def sw_running():
    import pythoncom
    try:
        pythoncom.GetActiveObject("SldWorks.Application")
        return True
    except pythoncom.com_error:
        return False


def watch():
    """Background watcher (started at Windows sign-in or by hand): every time SolidWorks starts, add the tab;
    when SolidWorks closes, wait for the next start. One instance per user. Ends with `stop`."""
    import pythoncom
    import win32api
    import win32event
    import winerror
    _mutex = win32event.CreateMutex(None, False, "Local\\swpanel_watch")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return
    os.makedirs(PANEL, exist_ok=True)
    if os.path.exists(STOP):
        os.remove(STOP)
    pythoncom.CoInitialize()
    log("watcher started")
    while not os.path.exists(STOP):
        if not sw_running():
            time.sleep(3)
            continue
        time.sleep(8)               # SolidWorks registers itself before its window is ready
        try:
            r = run(clear_stop=False)
        except Exception as e:
            log(f"watcher: run failed: {e!r}"[:300])
            r = "error"
        while sw_running() and not os.path.exists(STOP):   # same instance still up (closed tab / refused)
            time.sleep(5)
            if r is None:           # the tab ended while SolidWorks lives on (e.g. after an error): re-add
                break
    log("watcher stopped")


def run(clear_stop=True):
    import pythoncom
    import win32com.client
    os.makedirs(AGENT, exist_ok=True)
    if clear_stop and os.path.exists(STOP):
        os.remove(STOP)
    shutil.copyfile(os.path.join(SRC, "html", "panel.html"), os.path.join(PANEL, "panel.html"))
    shutil.copyfile(os.path.join(HERE, "swx.py"), os.path.join(PANEL, "swx.py"))
    with open(os.path.join(SRC, "PANEL_PROMPT.md"), encoding="utf-8") as f:
        prompt = f.read().replace("{SWX}", os.path.join(PANEL, "swx.py")).replace("{SCRIPTS}", HERE) \
            .replace("{SKILL}", os.path.dirname(HERE))
    with open(os.path.join(AGENT, "PANEL_PROMPT.md"), "w", encoding="utf-8") as f:
        f.write(prompt)
    icon = os.path.join(PANEL, "claude16.bmp")
    icon_bmp(icon)
    pythoncom.CoInitialize()
    sw = win32com.client.Dispatch(
        pythoncom.GetActiveObject("SldWorks.Application").QueryInterface(pythoncom.IID_IDispatch))
    rev = _get(sw, "RevisionNumber")
    if REQUIRE and not rev.startswith(REQUIRE):
        log(f"refused: SolidWorks {rev}, need {REQUIRE}*")
        return "refused"
    t0 = time.time()
    tp = sw.CreateTaskpaneView2(icon, "Claude")
    ctl = tp.AddControl("Shell.Explorer.2", "")
    ctl.Navigate2("file:///" + os.path.join(PANEL, "panel.html").replace("\\", "/"))
    while ctl.ReadyState != 4 and time.time() - t0 < 15:
        time.sleep(0.05)
    _get(tp, "ShowView")
    log(f"tab ready in {time.time() - t0:.2f} s, rev={rev}, claude={find_claude()}")
    br = None
    try:
        br = Bridge(sw, ctl)
        br.loop()
    except Exception as e:  # SolidWorks closed or the tab was removed
        log(f"loop ended: {e!r}"[:300])
    finally:
        if br and br.claude:
            br.claude.kill()
        try:
            _get(tp, "DeleteView")
        except Exception:
            pass
        log("stopped")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        open(STOP, "w").close()
    elif len(sys.argv) > 1 and sys.argv[1] == "watch":
        watch()
    else:
        run()
