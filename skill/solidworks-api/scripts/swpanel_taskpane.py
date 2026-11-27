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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import panel_steps  # noqa: E402

PANEL = os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel")
AGENT = os.path.join(PANEL, "agent")              # fixed cwd: Claude Code stores conversations per folder
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "swpanel")
REQUIRE = os.environ.get("SW_REQUIRE_REV", "")   # "" = any version; set e.g. "27." to lock a project to 2019
STOP = os.path.join(PANEL, "taskpane.stop")
SETTINGS = os.path.join(PANEL, "settings.json")
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Claude SolidWorks")
SEL_TYPES = {1: "edge", 2: "face", 3: "vertex", 4: "plane", 5: "axis", 9: "sketch segment", 11: "sketch point",
             20: "component", 22: "feature", 25: "dimension", 31: "sketch"}  # swSelectType_e (subset)
ALLOWED_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Skill", "TodoWrite", "Bash(python:*)", "Bash(py:*)", "PowerShell(python:*)", "PowerShell(py:*)",
                 "Bash(ls:*)", "Bash(dir:*)", "Bash(mkdir:*)", "Bash(copy:*)", "Bash(cp:*)", "Bash(tasklist:*)"]
TXT = {                      # every line the tab itself shows; panel.html holds the static labels (same keys)
    "he": {
        "hello": "שלום. בחר משהו בסוליד וכתוב מה לעשות.",
        "new": "שיחה חדשה",
        "resumed": "ממשיך את השיחה הקודמת (שיחה חדשה - בכפתור למעלה)",
        "stopped": "נעצר.",
        "no_cli": "Claude Code לא נמצא במחשב (אפליקציית Claude מותקנת?)",
        "need_login": "כדי שאוכל לעבוד מכאן צריך להתחבר לחשבון Claude פעם אחת במחשב הזה.",
        "login_btn": "התחבר ל-Claude",
        "login_wait": "נפתח דפדפן להתחברות. אשר שם - הלשונית תזהה לבד כשסיימת.",
        "login_ok": "מחובר. אפשר לכתוב.",
        "busy": "Claude עדיין עובד על הבקשה הקודמת.",
        "dir": "תיקיית שמירה: {d}",
        "att": "מצורף: {n}",
        "done": "{s:.0f} שנ'",
        "denied": "{n} נחסמו",
        "approved": "אושר",
        "rejected": "נדחה",
        "approve_q": "לבצע?",
        "approve_btn": "אשר",
        "reject_btn": "דחה",
        "you": "אתה",
        "you_av": "א",
        "no_doc": "אין מסמך פעיל",
        "no_sw": "SolidWorks לא זמין",
        "pick_dir": "תיקיית שמירה",
        "pick_file": "צרף קובץ",
        "lang_set": "עברית",
        "trace": "{n} שלבים · {s:.0f} שנ'",
        "trace_tokens": " · {k:.0f}K טוקנים",
        "more": "+{n} שלבים קודמים",
        "plan_head": "תוכנית",
        "plan_all_btn": "בצע הכל",
        "plan_one_btn": "שלב אחד ועצור",
        "plan_edit_btn": "שנה",
        "plan_all_msg": "אושר - בצע את כל התוכנית.",
        "plan_one_msg": "בצע רק את השלב הבא ועצור לבדיקה.",
        "next_btn": "המשך",
        "halt_btn": "עצור כאן",
        "next_msg": "המשך לשלב הבא.",
        "halt_msg": "עצור כאן: סכם מה נעשה, מה נבדק ומה נשאר.",
    },
    "en": {
        "hello": "Hi. Select something in SolidWorks and tell me what to do.",
        "new": "New chat",
        "resumed": "Continuing the previous chat (new chat: the button at the top)",
        "stopped": "Stopped.",
        "no_cli": "Claude Code was not found on this PC (is the Claude app installed?)",
        "need_login": "To work from here, sign in to your Claude account once on this PC.",
        "login_btn": "Sign in to Claude",
        "login_wait": "A browser opens for sign-in. Confirm there - the tab notices by itself when you are done.",
        "login_ok": "Signed in. You can type now.",
        "busy": "Claude is still working on the previous request.",
        "dir": "Save folder: {d}",
        "att": "Attached: {n}",
        "done": "{s:.0f} s",
        "denied": "{n} blocked",
        "approved": "Approved",
        "rejected": "Rejected",
        "approve_q": "Go ahead?",
        "approve_btn": "Approve",
        "reject_btn": "Reject",
        "you": "You",
        "you_av": "Y",
        "no_doc": "no active document",
        "no_sw": "SolidWorks not available",
        "pick_dir": "Save folder",
        "pick_file": "Attach file",
        "lang_set": "English",
        "trace": "{n} steps · {s:.0f} s",
        "trace_tokens": " · {k:.0f}K tokens",
        "more": "+{n} earlier steps",
        "plan_head": "PLAN",
        "plan_all_btn": "Do it all",
        "plan_one_btn": "One step, then stop",
        "plan_edit_btn": "Change",
        "plan_all_msg": "Approved - carry out the whole plan.",
        "plan_one_msg": "Do only the next step, then stop for a check.",
        "next_btn": "Continue",
        "halt_btn": "Stop here",
        "next_msg": "Continue with the next step.",
        "halt_msg": "Stop here: sum up what was done, what was checked and what is left.",
    },
}
LANGS = tuple(TXT)


def default_lang():
    """Hebrew when Windows itself is in Hebrew, else English. The flag at the top of the tab overrides it."""
    try:
        import ctypes
        return "he" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x0D else "en"
    except Exception:
        return "he"


def ui_lang(settings):
    lang = (settings or {}).get("lang")
    return lang if lang in LANGS else default_lang()


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
    local = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")   # native Claude Code installer
    return shutil.which("claude") or (local if os.path.exists(local) else None)


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
                            self.out.put(("step", {"id": blk.get("id"), "tool": blk.get("name"),
                                                   "input": blk.get("input", {})}))
                elif t == "user":                       # tool results: mark the step done / failed
                    content = ev.get("message", {}).get("content", [])
                    for blk in content if isinstance(content, list) else []:
                        if blk.get("type") == "tool_result":
                            self.out.put(("step_done", {"id": blk.get("tool_use_id"),
                                                        "error": bool(blk.get("is_error"))}))
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
        self.lang = ui_lang(self.set)
        os.makedirs(self.set["save_dir"], exist_ok=True)
        self.exe = find_claude()
        self.pending_text = ""
        self.steps = []                 # this turn: [{"id", "label", "state": now / done / fail, "raw"}]
        self.last_request = ""
        self.last_reply = ""

    def t(self, key, **kw):
        s = TXT[self.lang].get(key) or TXT["he"][key]
        return s.format(**kw) if kw else s

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

    # engineering insight lines Claude starts with a tag (PANEL_PROMPT.md) -> coloured cards in panel.html
    INSIGHTS = {"ייצור": "mfg", "ייעול": "opt", "למה": "why", "שים לב": "warn", "הנחה": "asm",
                "Manufacturing": "mfg", "Optimise": "opt", "Why": "why", "Note": "warn", "Assumption": "asm"}
    UNITS = r"(?:mm³|mm²|mm|מ&quot;מ|ס&quot;מ|cm|m|kg|ק&quot;ג|gr|g|גרם|°|N·m|Nm|N|MPa|GPa|%|₪|\$|s|שנ'|min|דק')"

    @classmethod
    def rich(cls, text):
        """Escape, then the little markup the panel prompt allows: **bold**, numbers with units highlighted,
        '- ' bullets, and insight lines '[ייצור] ...' / '[ייעול] ...' / '[למה] ...' / '[שים לב] ...' / '[הנחה] ...'."""
        import re
        num = re.compile(r"(?<![\w&#.,])((?:Ø|R|M(?=\d))?\d+(?:[.,]\d+)?(?:\s?[x×]\s?\d+(?:[.,]\d+)?)*\s?" + cls.UNITS + r")(?![\w])")
        tag = re.compile(r"^\s*\[(" + "|".join(cls.INSIGHTS) + r")\]\s*(.*)$")
        out = []
        for line in (text or "").strip("\n").split("\n"):
            h = esc(line)
            h = num.sub(lambda m: '<span class="num%s">%s</span>' % (                   # Hebrew unit: keep RTL order
                " he" if re.search("[\u0590-\u05ff]", m.group(1)) else "", m.group(1)), h)
            h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h)
            m = tag.match(h)
            if m:
                out.append(f'<div class="ins {cls.INSIGHTS[m.group(1)]}"><span class="tag">{m.group(1)}</span>'
                           f'{m.group(2)}</div>')
            elif re.match(r"^\s*[-•]\s+", h):
                out.append('<div class="li">' + re.sub(r"^\s*[-•]\s+", "", h) + "</div>")
            else:
                out.append(f"<div>{h or '&nbsp;'}</div>")
        return "".join(out)

    def bubble(self, text, who="ai", t=None, card=""):
        """LEO-style message: avatar, name + time, soft bubble; `card` = buttons inside the bubble."""
        who_cls = who.split()[0]
        err = " err" if "err" in who else ""
        name, av = ("Claude", "C") if who_cls == "ai" else (self.t("you"), self.t("you_av"))
        role = ""
        tm = t or time.strftime("%H:%M")
        self.add(f'<div class="row {who_cls}"><div class="av">{av}</div><div class="body">'
                 f'<div class="who"><span class="nm">{esc(name)}</span>{role} <span class="tm">{esc(tm)}</span></div>'
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
            self.el("steps").innerHTML = ""

    def show_steps(self):
        """The live list under "Working...": the last 5 steps, each one line in plain words."""
        icon = {"now": '<span class="spin"></span>', "done": "&#10003;", "fail": "&#10007;"}
        rows = self.steps[-5:]
        html_ = ""
        if len(self.steps) > 5:
            html_ += f'<div class="st more">{esc(self.t("more", n=len(self.steps) - 5))}</div>'
        for st in rows:
            html_ += (f'<div class="st {st["state"]}"><span class="ico">{icon[st["state"]]}</span>'
                      f'{esc(st["label"])}</div>')
        self.el("steps").innerHTML = html_

    def trace(self, p):
        """Under the reply: "5 steps · 14 s · 12K tokens"; a click opens the steps."""
        u = p.get("usage") or {}
        k = (u.get("input_tokens", 0) + u.get("output_tokens", 0) + u.get("cache_creation_input_tokens", 0)) / 1000
        line = self.t("trace", n=len(self.steps), s=p["s"]) + (self.t("trace_tokens", k=k) if k >= 1 else "")
        if p.get("denied"):
            line += " · " + self.t("denied", n=p["denied"])
        mark = {"done": "&#10003;", "fail": "&#10007;", "now": "&#10003;"}
        items = "".join(f'<div class="st {"fail" if s["state"] == "fail" else "done"}"><span class="ico">'
                        f'{mark[s["state"]]}</span>{esc(s["label"])}</div>' for s in self.steps)
        self.add(f'<div class="trace" onclick="tog(this)">{esc(line)}</div>'
                 f'<div class="trace-list" style="display:none">{items}</div>')
        self.steps = []

    def plan_card(self, plan, buttons=True):
        import re
        rows = "".join(f'<div class="pi"><span class="pn">{n}.</span> '
                       f'{re.sub(r"^<div>|</div>$", "", self.rich(t))}</div>' for n, t in plan)
        box = f'<div class="plan"><div class="ph">{esc(self.t("plan_head"))}</div>{rows}</div>'
        if not buttons:
            return box
        return (box + self.card([("plan_all", self.t("plan_all_btn"), "ok"),
                             ("plan_one", self.t("plan_one_btn"), "no"),
                             ("plan_edit", self.t("plan_edit_btn"), "ghost")]))

    def show_info(self):
        self.el("dir").innerText = self.set["save_dir"]
        self.el("att").innerText = self.t("att", n=", ".join(os.path.basename(a) for a in self.attach)) \
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
                self.sel_info, self.sel_txt = None, self.t("no_doc")
                return
            sm = doc.SelectionManager
            n = sm.GetSelectedObjectCount2(-1)
            items = [SEL_TYPES.get(sm.GetSelectedObjectType3(i, -1), str(sm.GetSelectedObjectType3(i, -1)))
                     for i in range(1, n + 1)]
            title = _get(doc, "GetTitle")
            path = _get(doc, "GetPathName")
            self.sel_info = {"doc": title, "path": path, "n": n, "types": items}
            self.sel_txt = panel_steps.selection_text(title, items, self.lang)
        except Exception as e:
            self.sel_info, self.sel_txt = {"error": repr(e)[:100]}, self.t("no_sw")

    # ---- actions ----
    def send(self, text, echo=True):
        if self.run_ and self.run_.is_alive():
            self.sys(self.t("busy"))
            return
        if not self.exe:
            self.bubble(self.t("no_cli"), "ai err")
            return
        self.last_request = text
        if echo:
            self.bubble(text, "me")
        self.chatlog("user", text)
        ctx = {"solidworks_rev": _get(self.sw, "RevisionNumber"), "require_rev": REQUIRE,
               "active_document": self.sel_info, "save_folder": self.set["save_dir"],
               "attached_files": self.attach, "ui_language": self.lang}
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
        d = filedialog.askdirectory(parent=r, initialdir=self.set["save_dir"], title=self.t("pick_dir"))
        r.destroy()
        if d:
            self.set["save_dir"] = os.path.normpath(d)
            self.save_settings()
            self.show_info()
            self.sys(self.t("dir", d=self.set["save_dir"]))

    def pick_file(self):
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        fs = filedialog.askopenfilenames(parent=r, title=self.t("pick_file"))
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
            self.sys(self.t("stopped"))
            self.chatlog("system", "stopped")
        elif flag == "new":
            if self.run_ and self.run_.is_alive():
                self.run_.kill()
            self.set.pop("session", None)
            self.save_settings()
            self.el("chat").innerHTML = ""
            self.sys(self.t("new"))
        elif flag == "folder":
            self.pick_folder()
        elif flag == "file":
            self.pick_file()
        elif flag == "login":
            self.start_login()
        elif flag.startswith("lang:") and flag[5:] in LANGS:
            # the page already switched its own labels (panel.html setLang); new lines follow from here on
            self.lang = self.set["lang"] = flag[5:]
            self.save_settings()
            self.show_info()
            self.sel_txt = ""
            self.sys(self.t("lang_set"))
        elif flag in ("approve", "reject"):
            self.send(self.t("approved") if flag == "approve" else self.t("rejected"))
        elif flag in ("plan_all", "plan_one", "next", "halt"):
            self.send(self.t({"plan_all": "plan_all_msg", "plan_one": "plan_one_msg", "next": "next_msg",
                              "halt": "halt_msg"}[flag]))
        elif flag == "plan_edit":
            self.el("req").focus()

    def handle_event(self, kind, p):
        if kind == "session" and p:
            self.new_session = p          # kept only if the turn succeeds (see "result")
        elif kind == "text":
            if p.startswith("Not logged in"):
                return
            show, plan, _marker = panel_steps.parse_reply(p)
            if show or plan:
                self.bubble(show, card=self.plan_card(plan) if plan else "")
            self.last_reply = p
            self.chatlog("claude", p)
        elif kind == "step":
            for st in self.steps:
                if st["state"] == "now":
                    st["state"] = "done"
            self.steps.append({"id": p.get("id"), "state": "now",
                               "label": panel_steps.step_label(p.get("tool"), p.get("input"), self.lang)})
            self.show_steps()
        elif kind == "step_done":
            for st in self.steps:
                if st["id"] == p.get("id"):
                    st["state"] = "fail" if p.get("error") else "done"
            self.show_steps()
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
                show, plan, _m = panel_steps.parse_reply(txt)
                if show or plan:
                    self.bubble(show, card=self.plan_card(plan) if plan else "")
            self.trace(p)
            marker = panel_steps.parse_reply(txt + "\n" + self.last_reply)[2]
            if marker == "approve":
                self.bubble(self.t("approve_q"), card=self.card([("approve", self.t("approve_btn"), "ok"),
                                                                   ("reject", self.t("reject_btn"), "no")]))
            elif marker == "next":
                self.bubble("", card=self.card([("next", self.t("next_btn"), "ok"),
                                                ("halt", self.t("halt_btn"), "no")]))
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
        self.bubble(self.t("need_login"), card=self.card([("login", self.t("login_btn"), "ok")]))

    def start_login(self):
        # a small console window: the browser opens for the Anthropic sign-in; the window closes by itself
        subprocess.Popen([self.exe, "auth", "login"], cwd=AGENT, creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.sys(self.t("login_wait"))
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
            show, plan, _m = panel_steps.parse_reply(d["text"])
            self.bubble(show, "me" if d["who"] == "user" else "ai", t=d.get("t", "")[11:16],
                        card=self.plan_card(plan, buttons=False) if plan else "")
        if rows:
            self.sys(self.t("resumed"))
        return bool(rows)

    def loop(self):
        self.show_info()
        if not self.replay():
            self.bubble(self.t("hello"))
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
                    self.sys(self.t("login_ok"))
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
    old_swx = os.path.join(PANEL, "swx.py")     # before v2.5 a copy lived here; swx.py now needs contract.py beside it
    if os.path.exists(old_swx):
        os.remove(old_swx)
    with open(os.path.join(SRC, "PANEL_PROMPT.md"), encoding="utf-8") as f:
        prompt = f.read().replace("{SWX}", os.path.join(HERE, "swx.py")).replace("{SCRIPTS}", HERE) \
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
    # the page reads its language from the #fragment (IE11 in edge mode has no execScript to push it later)
    lang = ui_lang(read_json(SETTINGS, {}))
    ctl.Navigate2("file:///" + os.path.join(PANEL, "panel.html").replace("\\", "/") + "#" + lang)
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
