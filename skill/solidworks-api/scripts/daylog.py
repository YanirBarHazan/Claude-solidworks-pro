"""Day log: what Claude did in SolidWorks today, recorded automatically, read in one page.

Recording (automatic, no code needed): sw_common.connect() starts it once per script, the warm worker once per swx
command. One JSON line per run goes to ~/.solidworks-api/daylog/<YYYY-MM-DD>.jsonl:
    script + args, start time, seconds, ok / the error line,
    files opened by the run (every OpenDoc6 / OpenDoc7 through the early-bound wrapper) and windows left open,
    for every open assembly: top-level components, Fixed, floating (no mates), mated, pattern instances, mates.
It never stops a script: any failure inside the log is swallowed. SW_DAYLOG=0 turns it off;
SW_DAYLOG_DIR moves it.

Report (run at the end of the day, or when the user says "something went wrong today"):
    python daylog.py [YYYY-MM-DD] [--claude-dir DIR]
writes <daylog dir>/<date>.md and prints a few summary lines. It merges three sources by time:
    the SolidWorks runs above,
    Claude Code conversations of that day (~/.claude/projects/*/*.jsonl: requests, tool calls, scripts run, tokens),
    the Claude tab inside SolidWorks (~/.solidworks-api/swpanel/chat.log.jsonl + tokens.csv).
"Warnings" checks the runs against the skill's rules: assemblies placed by Fix instead of mates, floating
components, runs that opened many files, failed runs. Local only: it holds the user's requests and file names -
anonymise before anything goes to the skill repository.
Standard library only for the report; the recorder needs no import of win32 either (it gets sw and T passed in)."""
import atexit
import collections
import csv
import datetime
import glob
import json
import os
import sys
import time

HOME = os.path.expanduser("~")
DIR = os.environ.get("SW_DAYLOG_DIR") or os.path.join(HOME, ".solidworks-api", "daylog")
PANEL = os.path.join(HOME, ".solidworks-api", "swpanel")
ON = os.environ.get("SW_DAYLOG", "1") != "0"
MANY_OPENS = 8          # a run that opens more files than this is listed as a warning
MAX_ASM = 4             # assemblies measured per run (the visible ones, active first)
MAX_COMPS = 5000        # above this the component walk is skipped (cost)

_S = {"started": False, "done": False, "opened": [], "error": None, "hooked": False}


# ---------------------------------------------------------------- recording
def hook_open(swmod):
    """Count every OpenDoc6 / OpenDoc7 made through the early-bound ISldWorks class (all scripts use it)."""
    if _S["hooked"] or not ON:
        return
    cls = swmod.ISldWorks
    for name in ("OpenDoc6", "OpenDoc7"):
        orig = getattr(cls, name, None)
        if orig is None:
            continue

        def wrap(self, *a, _orig=orig, _name=name, **k):
            try:
                p = a[0] if a else k.get("FileName", "")
                if _name == "OpenDoc7" and not isinstance(p, str):
                    p = getattr(p, "FileName", "") or ""
                _S["opened"].append(os.path.basename(str(p)))
            except Exception:
                pass
            return _orig(self, *a, **k)
        setattr(cls, name, wrap)
    _S["hooked"] = True


def visible_docs(sw, T):
    """{title: (kind, path)} of the documents with a window (components loaded by an assembly are not)."""
    out = {}
    d = sw.GetFirstDocument()
    while d is not None:
        d = T(d, "IModelDoc2")
        try:
            if d.Visible:
                out[d.GetTitle()] = (d.GetType(), d.GetPathName())
        except Exception:
            pass
        d = d.GetNext()
    return out


def asm_stats(doc, T):
    """Top-level placement of one assembly: how it is held (mates / Fix / nothing) and how many mates it has."""
    asm = T(doc, "IAssemblyDoc")
    comps = asm.GetComponents(True) or []
    r = {"name": doc.GetTitle(), "components": len(comps)}
    if len(comps) > MAX_COMPS:
        r["skipped"] = "too many components"
        return r
    fixed = floating = mated = inst = supp = 0
    for c in comps:
        c = T(c, "IComponent2")
        if c.GetSuppression2() == 0:
            supp += 1
        elif c.IsPatternInstance():
            inst += 1
        elif c.IsFixed():
            fixed += 1
        elif not c.GetMates():
            floating += 1
        else:
            mated += 1
    mates = 0
    f = doc.FirstFeature()
    while f is not None:
        f = T(f, "IFeature")
        if f.GetTypeName2() == "MateGroup":
            s = f.GetFirstSubFeature()
            while s is not None:
                s = T(s, "IFeature")
                if s.GetTypeName2().startswith("Mate"):
                    mates += 1
                s = s.GetNextSubFeature()
            break
        f = f.GetNextFeature()
    r.update(fixed=fixed, floating=floating, mated=mated, pattern_instances=inst, suppressed=supp, mates=mates)
    return r


def begin(sw, T, name=None, args=None, once=True):
    """Start recording one run. once=True (scripts): only the first call per process counts."""
    if not ON or (once and _S["started"]):
        return
    _S.update(started=True, done=False, opened=[], error=None, t0=time.time(),
              name=name or os.path.basename(sys.argv[0] or "python"),
              args=args if args is not None else sys.argv[1:], cwd=os.getcwd())
    try:
        _S["before"] = visible_docs(sw, T)
    except Exception:
        _S["before"] = {}
    if once:
        prev = sys.excepthook

        def hook(tp, val, tb):
            _S["error"] = f"{tp.__name__}: {val}"[:300]
            prev(tp, val, tb)
        sys.excepthook = hook
        atexit.register(end, sw, T)


def end(sw, T, ok=None, error=None):
    """Write the run's line. Called by atexit for scripts, by the worker after each command."""
    if not ON or _S["done"] or not _S["started"]:
        return
    _S["done"] = True
    err = error or _S["error"]
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_S["t0"])),
           "s": round(time.time() - _S["t0"], 1), "script": _S["name"], "args": [str(a)[:80] for a in _S["args"]][:8],
           "cwd": _S["cwd"], "ok": (err is None) if ok is None else ok, "error": err,
           "opened": _S["opened"][:60], "opened_n": len(_S["opened"])}
    try:
        after = visible_docs(sw, T)
        before = _S.get("before", {})
        rec["left_open"] = sorted(set(after) - set(before))[:30]
        rec["closed"] = sorted(set(before) - set(after))[:30]
        active = sw.ActiveDoc
        active = T(active, "IModelDoc2").GetTitle() if active is not None else None
        asms = sorted((t for t, (k, _) in after.items() if k == 2), key=lambda t: t != active)[:MAX_ASM]
        rec["assemblies"] = []
        for t in asms:
            try:
                d = T(sw.GetOpenDocumentByName(after[t][1] or t), "IModelDoc2")
                rec["assemblies"].append(asm_stats(d, T))
            except Exception as e:
                rec["assemblies"].append({"name": t, "skipped": str(e)[:80]})
    except Exception as e:
        rec["log_error"] = str(e)[:120]
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(os.path.join(DIR, rec["t"][:10] + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- report
def _local(ts):
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except Exception:
        return None


def _jsonl(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def read_runs(date):
    return list(_jsonl(os.path.join(DIR, date + ".jsonl")))


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
            return None
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return None


def read_claude(date, claude_dir=None):
    """Claude Code conversations of the day: one dict per session."""
    base = claude_dir or os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude"), "projects")
    day0 = datetime.datetime.fromisoformat(date)
    sessions = []
    for path in glob.glob(os.path.join(base, "*", "*.jsonl")):
        if datetime.datetime.fromtimestamp(os.path.getmtime(path)) < day0:
            continue
        s = {"file": path, "project": os.path.basename(os.path.dirname(path)), "prompts": [], "tools": collections.Counter(),
             "scripts": collections.Counter(), "first": None, "last": None}
        usage = {}
        for e in _jsonl(path):
            t = _local(e.get("timestamp", ""))
            if t is None or t.date().isoformat() != date:
                continue
            s["first"] = s["first"] or t
            s["last"] = t
            msg = e.get("message") or {}
            if e.get("type") == "user" and not e.get("isMeta"):
                txt = _text(msg.get("content"))
                if txt and not txt.lstrip().startswith("<"):
                    s["prompts"].append((t, " ".join(txt.split())[:140]))
            elif e.get("type") == "assistant":
                for c in msg.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        s["tools"][c.get("name", "?")] += 1
                        cmd = (c.get("input") or {}).get("command", "")
                        for w in str(cmd).replace("\\", "/").split():
                            if w.endswith(".py"):
                                s["scripts"][w.split("/")[-1]] += 1
                if msg.get("usage"):
                    usage[msg.get("id") or len(usage)] = msg["usage"]
        if s["first"] is None:
            continue
        s["tokens"] = {k: sum(u.get(k, 0) or 0 for u in usage.values())
                       for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")}
        sessions.append(s)
    return sorted(sessions, key=lambda s: s["first"])


def read_panel(date):
    chat = [e for e in _jsonl(os.path.join(PANEL, "chat.log.jsonl")) if str(e.get("t", "")).startswith(date)]
    rows = []
    try:
        with open(os.path.join(PANEL, "tokens.csv"), encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("time", "").startswith(date)]
    except OSError:
        pass
    return chat, rows


def warnings(runs):
    out = []
    for r in runs:
        when = r["t"][11:16]
        if not r.get("ok"):
            out.append(f"{when} `{r['script']}` נכשל: {r.get('error') or '?'}")
        if r.get("opened_n", 0) > MANY_OPENS:
            out.append(f"{when} `{r['script']}` פתח {r['opened_n']} קבצים - היה צריך את כולם? (כלל 4: פותחים רק מה שמשנים)")
    last = {}
    for r in runs:                      # each assembly: its state after the day's last run that saw it
        for a in r.get("assemblies") or []:
            if "fixed" in a:
                last[a["name"]] = (r["t"][11:16], a)
    for name, (when, a) in last.items():
        held = a["components"] - a.get("pattern_instances", 0) - a.get("suppressed", 0)
        if a["fixed"] > 1:
            out.append(f"{when} `{name}`: {a['fixed']} מתוך {held} רכיבים ב-Fix, {a['mates']} מייטים "
                       f"(כלל 3: רק השלד / רכיב הבסיס ב-Fix, השאר במייטים)")
        if a.get("floating"):
            out.append(f"{when} `{name}`: {a['floating']} רכיבים צפים (בלי Fix ובלי מייטים)")
    return out


def report(date, claude_dir=None):
    runs = read_runs(date)
    sessions = read_claude(date, claude_dir)
    chat, tok = read_panel(date)
    warn = warnings(runs)
    L = [f"# יומן יום - {date}", ""]
    opened = sum(r.get("opened_n", 0) for r in runs)
    fails = sum(1 for r in runs if not r.get("ok"))
    tk = collections.Counter()
    for s in sessions:
        tk.update(s["tokens"])
    for r in tok:
        for k, c in (("input", "input_tokens"), ("cache_read", "cache_read_input_tokens"), ("output", "output_tokens")):
            try:
                tk[c] += int(float(r.get(k) or 0))
            except ValueError:
                pass
    L += ["## במספרים", "",
          f"- הרצות ב-SolidWorks: {len(runs)} (נכשלו {fails}), {round(sum(r.get('s', 0) for r in runs) / 60, 1)} דק'",
          f"- קבצים שנפתחו: {opened}",
          f"- שיחות Claude Code: {len(sessions)}, בקשות: {sum(len(s['prompts']) for s in sessions)}, "
          f"קריאות לכלים: {sum(sum(s['tools'].values()) for s in sessions)}",
          f"- הטאב בתוך SolidWorks: {sum(1 for e in chat if e.get('who') == 'user')} בקשות",
          f"- טוקנים: קלט {tk['input_tokens']:,}, מהמטמון {tk['cache_read_input_tokens']:,}, פלט {tk['output_tokens']:,}",
          "", "## אזהרות (מול כללי הסקיל)", ""]
    L += [f"- {w}" for w in warn] or ["- אין"]
    L += ["", "## ציר זמן", ""]
    ev = []
    for s in sessions:
        for t, p in s["prompts"]:
            ev.append((t.strftime("%H:%M"), f"**בקשה:** {p}"))
    for e in chat:
        if e.get("who") == "user":
            ev.append((str(e["t"])[11:16], f"**בקשה (טאב):** {' '.join(str(e.get('text', '')).split())[:140]}"))
    for r in runs:
        mark = "OK" if r.get("ok") else "FAIL"
        extra = f", פתח {r['opened_n']}" if r.get("opened_n") else ""
        for a in r.get("assemblies") or []:
            if "fixed" in a:
                extra += f", `{a['name']}`: {a['components']} רכיבים / {a['fixed']} Fix / {a['mates']} מייטים"
        ev.append((r["t"][11:16], f"`{r['script']} {' '.join(r.get('args') or [])[:60]}` {mark} {r.get('s', 0)} ש'{extra}"))
    L += [f"- {t} {x}" for t, x in sorted(ev, key=lambda e: e[0])] or ["- אין"]
    if sessions:
        L += ["", "## שיחות Claude Code", ""]
        for s in sessions:
            tools = ", ".join(f"{k} {v}" for k, v in s["tools"].most_common(6))
            scripts = ", ".join(f"{k} {v}" for k, v in s["scripts"].most_common(8))
            L += [f"- {s['first']:%H:%M}-{s['last']:%H:%M} `{s['project']}`: {len(s['prompts'])} בקשות; כלים: {tools or '-'}; "
                  f"סקריפטים: {scripts or '-'}; פלט {s['tokens']['output_tokens']:,} טוקנים", f"  קובץ: `{s['file']}`"]
    L += ["", "## איך משתמשים בזה", "",
          "- כשמשהו השתבש: פתח את הקובץ של השיחה (למעלה) ותן ל-Claude לקרוא אותו יחד עם הדף הזה.",
          "- כל אזהרה = כלל שהסקיל עבר עליו. אם חוזרת על עצמה, זה תיקון לסקיל (SKILL.md / pitfalls.md / audit.py)."]
    os.makedirs(DIR, exist_ok=True)
    out = os.path.join(DIR, date + ".md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return out, runs, sessions, warn


if __name__ == "__main__":
    a = sys.argv[1:]
    cdir = None
    if "--claude-dir" in a:
        i = a.index("--claude-dir")
        cdir = a[i + 1]
        del a[i:i + 2]
    day = a[0] if a else datetime.date.today().isoformat()
    path, runs, sessions, warn = report(day, cdir)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(f"DAYLOG {day}: {len(runs)} SolidWorks runs ({sum(1 for r in runs if not r.get('ok'))} failed), "
          f"{len(sessions)} Claude sessions, {len(warn)} warnings -> {path}")
    for w in warn[:10]:
        print("  WARN " + w)
