"""What the Claude tab shows while Claude works, in plain words (no tool names, no paths, no JSON).
Pure functions - tested in tests/test_panel_steps.py.

    step_label(tool, input, lang) -> "Reading the model" / "Changing values: WALL, HOLE_D" ...
    parse_reply(text) -> (text to show, plan steps or None, marker)   markers: approve / plan / next
    selection_text(doc, types, lang) -> "bracket.SLDPRT · face ×2"
"""
import os
import re
import shlex

L = {
    "he": {"card": "קורא את המודל", "info": "בודק את מה שבחרת", "set": "משנה ערכים: {names}",
           "fillet": "מוסיף פילט R{r}", "save": "שומר את הקובץ", "run": "מבצע פעולה בסולידוורקס",
           "ping": "בודק חיבור לסולידוורקס", "read_doc": "מעיין בהנחיות: {name}", "read": "קורא {name}",
           "write": "כותב {name}", "edit": "מעדכן {name}", "search": "מחפש בתיעוד", "drawing": "קורא שרטוט {name}",
           "python": "מחשב", "skill": "טוען ידע מקצועי", "todo": "מסדר את השלבים", "other": "עובד",
           "dir": "בודק את התיקייה"},
    "en": {"card": "Reading the model", "info": "Looking at your selection", "set": "Changing values: {names}",
           "fillet": "Adding a fillet R{r}", "save": "Saving the file", "run": "Working in SolidWorks",
           "ping": "Checking the SolidWorks link", "read_doc": "Reading the guide: {name}", "read": "Reading {name}",
           "write": "Writing {name}", "edit": "Updating {name}", "search": "Searching the guide",
           "drawing": "Reading drawing {name}", "python": "Calculating", "skill": "Loading know-how",
           "todo": "Organising the steps", "other": "Working", "dir": "Checking the folder"},
}
SEL = {"he": {"edge": "קצה", "face": "פאה", "vertex": "נקודה", "plane": "מישור", "axis": "ציר", "component": "רכיב",
              "feature": "פיצ'ר", "dimension": "מידה", "sketch": "סקיצה", "sketch segment": "קטע בסקיצה",
              "sketch point": "נקודה בסקיצה"},
       "en": {}}
GUIDE_NAMES = {"he": {"SKILL": "שיטת העבודה", "pitfalls": "מלכודות API", "manufacturing": "ייצור",
                      "verification": "בדיקות", "assemblies": "הרכבות", "drawings": "שרטוטים",
                      "sheet_metal": "פח", "drawing_to_part": "משרטוט לחלק", "engineering": "חישובים הנדסיים",
                      "fdm_printing": "הדפסת תלת-ממד"},
               "en": {"SKILL": "the method", "pitfalls": "API pitfalls", "drawing_to_part": "drawing to part",
                      "sheet_metal": "sheet metal", "fdm_printing": "3D printing"}}


def _base(path):
    return os.path.basename(str(path).replace("\\", "/").rstrip("/")) or str(path)


def _guide(path, lang):
    name = os.path.splitext(_base(path))[0]
    return GUIDE_NAMES.get(lang, {}).get(name, name.replace("_", " "))


def step_label(tool, inp, lang="he"):
    t = L.get(lang, L["he"])
    inp = inp or {}
    if tool == "Bash":
        cmd = inp.get("command", "")
        try:
            words = shlex.split(cmd, posix=True)
        except ValueError:
            words = cmd.split()
        names = [w for w in words if w.lower().endswith(".py")]
        script = _base(names[0]).lower() if names else ""
        if script == "swx.py":
            i = next(i for i, w in enumerate(words) if w.lower().endswith("swx.py"))
            sub = words[i + 1] if len(words) > i + 1 else ""
            rest = words[i + 2:]
            if sub == "set":
                ns = [a.split("=")[0] for a in rest if "=" in a]
                return t["set"].format(names=", ".join(ns[:4]) + (" ..." if len(ns) > 4 else ""))
            if sub == "fillet":
                return t["fillet"].format(r=rest[0] if rest else "")
            return t.get(sub, t["run"])
        if script == "drawing_read.py":
            arg = words[words.index(names[0]) + 1] if len(words) > words.index(names[0]) + 1 else ""
            return t["drawing"].format(name=_base(arg))
        if script:
            return t["python"] if script.startswith(("calc", "check")) else t["run"]
        if words and words[0] in ("ls", "dir", "mkdir", "tasklist"):
            return t["dir"]
        return t["other"]
    if tool == "Read":
        p = inp.get("file_path", "")
        low = p.replace("\\", "/").lower()
        if "/references/" in low or low.endswith("skill.md") or low.endswith("panel_prompt.md"):
            return t["read_doc"].format(name=_guide(p, lang))
        return t["read"].format(name=_base(p))
    if tool in ("Write",):
        return t["write"].format(name=_base(inp.get("file_path", "")))
    if tool in ("Edit", "MultiEdit"):
        return t["edit"].format(name=_base(inp.get("file_path", "")))
    if tool in ("Grep", "Glob"):
        return t["search"]
    if tool == "Skill":
        return t["skill"]
    if tool == "TodoWrite":
        return t["todo"]
    return t["other"]


PLAN_LINE = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")


def parse_reply(text):
    """-> (text without markers, plan steps [(n, text)] or None, marker or None).
    [[PLAN]]: the numbered lines of the reply are a plan waiting for approval; [[NEXT]]: one step was done and
    Claude waits before the next; [[APPROVE]]: an irreversible action waits for a yes / no."""
    text = text or ""
    marker = None
    for m in ("PLAN", "NEXT", "APPROVE"):
        if f"[[{m}]]" in text:
            marker = marker or m.lower()
            text = text.replace(f"[[{m}]]", "")
    text = text.strip()
    plan = None
    if marker == "plan":
        keep, plan = [], []
        for line in text.split("\n"):
            m = PLAN_LINE.match(line)
            if m:
                plan.append((int(m.group(1)), m.group(2).strip()))
            else:
                keep.append(line)
        text = "\n".join(keep).strip()
        plan = plan or None
    return text, plan, marker


def selection_text(doc, types, lang="he"):
    if not types:
        return doc
    names = SEL.get(lang, {})
    counts = {}
    for x in types:
        counts[x] = counts.get(x, 0) + 1
    parts = [names.get(k, k) + (f" ({n})" if n > 1 else "") for k, n in counts.items()]
    return f"{doc} · " + ", ".join(parts[:3]) + (" ..." if len(parts) > 3 else "")
