"""Background agents for the Claude tab: the main chat hands independent sub-tasks to helpers that work at the same
time, each a one-shot headless Claude Code with its own folder. At most MAX_PARALLEL run together (many at once is
what crashed the tab before: every Claude process and every visible SolidWorks document costs memory; the user sets 2-8 in
the tab's menu); the rest
wait in a queue. All of them reach SolidWorks through the one warm worker, which runs one command at a time, and
they work on their own documents (`--doc`, `run --background`), so the document the user looks at never changes.

    m = AgentManager(launch, out_queue, max_parallel=3)
    m.add("bracket", "Build the wall bracket ...")     -> agent id; started now or when a slot frees
    m.stop_all()
Events on out_queue (kind, payload):
    ("agent", {id, name, state, step, text, images, need, s})     state: queued / running / done / failed / stopped
    ("agents_done", [agent dicts])                                  every agent of the batch has finished
`launch(agent)` returns a Popen-like object: .stdout yields stream-json lines, .poll(), .kill(), .pid.
Pure Python (no SolidWorks, no Windows): tests/test_agents.py drives it with fake processes."""
import json
import re
import threading
import time

import panel_steps

MAX_PARALLEL = 3      # default; the tab's menu sets 2 to MAX_LIMIT (settings.json "max_agents")
MAX_LIMIT = 8         # each agent is a Claude process plus its documents in the same SolidWorks
IMAGE = re.compile(r"\[\[IMAGE\s+(.+?)\]\]")
NEED = re.compile(r"\[\[NEED\]\]\s*(.+)", re.S)


class Agent:
    def __init__(self, aid, name, task):
        self.id, self.name, self.task = aid, name, task
        self.state, self.step, self.text, self.images, self.need = "queued", "", "", [], None
        self.steps, self.t0, self.t1, self.proc = [], None, None, None
        self.usage = {}

    def as_dict(self):
        return {"id": self.id, "name": self.name, "task": self.task, "state": self.state, "step": self.step,
                "steps": list(self.steps), "text": self.text, "images": list(self.images), "need": self.need,
                "s": round((self.t1 or time.time()) - self.t0, 1) if self.t0 else 0.0}


class AgentManager:
    def __init__(self, launch, out, max_parallel=MAX_PARALLEL, lang="he"):
        self.launch, self.out, self.max = launch, out, max(1, int(max_parallel))
        self.lang = lang
        self.agents, self.lock, self.n = [], threading.RLock(), 0

    # ---- queue
    def add(self, name, task):
        with self.lock:
            self.n += 1
            a = Agent(f"a{self.n}", name.strip() or f"agent {self.n}", task.strip())
            self.agents.append(a)
            self._emit(a)
            self._schedule()
            return a.id

    def running(self):
        return [a for a in self.agents if a.state == "running"]

    def active(self):
        return any(a.state in ("queued", "running") for a in self.agents)

    def _schedule(self):
        with self.lock:
            for a in self.agents:
                if len(self.running()) >= self.max:
                    break
                if a.state == "queued":
                    self._start(a)

    def _start(self, a):
        a.state, a.t0 = "running", time.time()
        try:
            a.proc = self.launch(a)
        except Exception as e:
            a.state, a.text, a.t1 = "failed", f"could not start: {e}", time.time()
            self._emit(a)
            return
        self._emit(a)
        threading.Thread(target=self._read, args=(a,), daemon=True).start()

    # ---- one agent's stream
    def _read(self, a):
        final = None
        try:
            for line in a.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                t = ev.get("type")
                if t == "assistant":
                    for blk in ev.get("message", {}).get("content", []):
                        if blk.get("type") == "tool_use":
                            a.step = panel_steps.step_label(blk.get("name"), blk.get("input"), self.lang)
                            a.steps.append(a.step)
                            self._emit(a)
                        elif blk.get("type") == "text" and blk.get("text", "").strip():
                            a.text = blk["text"].strip()
                elif t == "result":
                    final = ev
        except Exception as e:                       # a broken pipe is a failed agent, never a dead tab
            a.text = (a.text + f"\n(stream error: {e})").strip()
        with self.lock:
            if a.state == "stopped":
                pass
            elif final is not None and not final.get("is_error"):
                a.state = "done"
                a.text = (final.get("result") or a.text or "").strip()
            else:
                a.state = "failed"
                if final is not None and final.get("result"):
                    a.text = final["result"].strip()
            if final is not None:
                a.usage = final.get("usage") or {}
            a.images = [p.strip().strip('"') for p in IMAGE.findall(a.text)]
            m = NEED.search(a.text)
            a.need = m.group(1).strip() if m else None
            a.text = NEED.sub("", IMAGE.sub("", a.text)).strip()
            a.step, a.t1 = "", time.time()
            self._emit(a)
            self._schedule()
            if not self.active():
                self.out.put(("agents_done", [x.as_dict() for x in self.agents]))

    def stop_all(self):
        with self.lock:
            for a in self.agents:
                if a.state == "queued":
                    a.state = "stopped"
                    self._emit(a)
                elif a.state == "running":
                    a.state = "stopped"
                    try:
                        a.proc.kill()
                    except Exception:
                        pass
                    self._emit(a)

    def clear_finished(self):
        with self.lock:
            self.agents = [a for a in self.agents if a.state in ("queued", "running")]

    def _emit(self, a):
        self.out.put(("agent", a.as_dict()))


# ---------------------------------------------------------------- what the tab draws
COLORS = {"queued": "#5d6b7c", "running": "#38c8f0", "done": "#34d399", "failed": "#f87171", "stopped": "#7d8b9c"}
WORDS = {"he": {"queued": "בתור", "running": "עובד", "done": "סיים", "failed": "נכשל", "stopped": "נעצר",
                "main": "ראשי", "merge": "איחוד"},
         "en": {"queued": "queued", "running": "working", "done": "done", "failed": "failed", "stopped": "stopped",
                "main": "Main", "merge": "Merge"}}


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def flow_svg(agents, lang="he", width=280):
    """The work as a small flow chart: main -> each agent -> merge, every node coloured by its state; in Hebrew it
    runs right to left. Plain SVG 1.1 (the tab runs in the IE11 engine)."""
    w = WORDS.get(lang, WORDS["he"])
    rtl = lang == "he"

    def X(x):                                  # mirror for right-to-left
        return width - x if rtl else x

    def box(x, wd):                            # left edge of a box that spans x .. x + wd before mirroring
        return width - x - wd if rtl else x
    n = max(1, len(agents))
    row, top = 26, 8
    h = top * 2 + n * row
    mid = top + n * row / 2
    xm, xa, xg = 6, width * 0.30, width - 62
    aw = xg - xa - 18
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h:.0f}" '
             f'viewBox="0 0 {width} {h:.0f}">']
    done = bool(agents) and all(a["state"] in ("done", "failed", "stopped") for a in agents)
    font = 'font-family="Segoe UI, Arial" text-anchor="middle"'
    for i, a in enumerate(agents):
        y = top + i * row + row / 2
        col = COLORS.get(a["state"], "#5d6b7c")
        parts.append(f'<path d="M{X(xm + 52):.1f},{mid:.1f} C{X(xa - 20):.1f},{mid:.1f} {X(xm + 60):.1f},{y:.1f} '
                     f'{X(xa):.1f},{y:.1f}" stroke="{col}" stroke-width="1.5" fill="none" opacity="0.8"/>')
        parts.append(f'<path d="M{X(xa + aw):.1f},{y:.1f} C{X(xg - 10):.1f},{y:.1f} {X(xa + aw + 10):.1f},{mid:.1f} '
                     f'{X(xg):.1f},{mid:.1f}" stroke="{col}" stroke-width="1.5" fill="none" opacity="0.5"/>')
        parts.append(f'<rect x="{box(xa, aw):.1f}" y="{y - 10:.1f}" width="{aw:.0f}" height="20" rx="5" '
                     f'fill="#141b24" stroke="{col}" stroke-width="1.5"/>')
        label = a["name"] if len(a["name"]) <= 16 else a["name"][:15] + "…"
        parts.append(f'<text x="{X(xa + aw / 2):.1f}" y="{y + 4:.1f}" font-size="10" fill="#d7e0ea" {font}>'
                     f'{_esc(label)}</text>')
    parts.append(f'<rect x="{box(xm, 52):.1f}" y="{mid - 11:.1f}" width="52" height="22" rx="6" fill="#0f1a24" '
                 f'stroke="#38c8f0" stroke-width="1.5"/>')
    parts.append(f'<text x="{X(xm + 26):.1f}" y="{mid + 4:.1f}" font-size="10" fill="#38c8f0" {font}>'
                 f'{_esc(w["main"])}</text>')
    gcol = "#34d399" if done else "#5d6b7c"
    parts.append(f'<rect x="{box(xg, 56):.1f}" y="{mid - 11:.1f}" width="56" height="22" rx="6" fill="#0f1a24" '
                 f'stroke="{gcol}" stroke-width="1.5"/>')
    parts.append(f'<text x="{X(xg + 28):.1f}" y="{mid + 4:.1f}" font-size="10" fill="{gcol}" {font}>'
                 f'{_esc(w["merge"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def agent_card(a, lang="he"):
    """One agent in the strip: a coloured dot, the name, what it does right now, and its picture when it has one."""
    w = WORDS.get(lang, WORDS["he"])
    col = COLORS.get(a["state"], "#5d6b7c")
    now = a["step"] if a["state"] == "running" and a["step"] else w.get(a["state"], a["state"])
    pulse = " pulse" if a["state"] == "running" else ""
    img = ""
    if a.get("images"):
        img = f'<img class="ath" src="file:///{_esc(a["images"][-1].replace(chr(92), "/"))}">'
    secs = (f' · {a["s"]:.0f} ' + ("שנ'" if lang == "he" else "s")) if a.get("s") else ""
    return (f'<div class="ag {a["state"]}" onclick="act(\'agent:{a["id"]}\')">{img}'
            f'<span class="dot2{pulse}" style="background:{col}"></span>'
            f'<span class="an">{_esc(a["name"])}</span>'
            f'<div class="ast">{_esc(now)}{secs}</div></div>')


def results_message(agents, lang="he"):
    """What the main Claude is told when the batch has finished: each agent's report, its pictures and questions."""
    head = "הסוכנים סיימו. בדוק כל תוצאה במדידה, אחד אותן והשב לי:" if lang == "he" else \
        "The agents have finished. Check each result with a measurement, bring them together and report to me:"
    lines = [head]
    for a in agents:
        lines.append(f"\n## {a['name']} ({a['state']}, {a['s']:.0f} s)\ntask: {a['task']}\n{a['text'] or '-'}")
        for p in a["images"]:
            lines.append(f"image: {p}")
        if a["need"]:
            lines.append(f"NEEDS THE USER: {a['need']}")
    return "\n".join(lines)
