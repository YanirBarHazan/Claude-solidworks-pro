"""Token / time benchmark of the Claude tab: 5 fixed requests on a fresh test plate, each result checked by
measurement (not by Claude's word). Needs the tab running (watcher or swpanel_taskpane.py) and SolidWorks 2019.

    python swpanel_bench.py [label]

Plate: 60 x 60 x 6 mm, centred Ø11 through hole (globals PLATE_W/D/T, HOLE_D), saved in the panel scratch folder.
Writes one row per request to ~/.solidworks-api/swpanel/bench.csv (tokens from tokens.csv, written by the tab).
"""
import csv
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel")
SCR = os.path.join(PANEL, "scratch")
PLATE = os.path.join(SCR, "bench_plate.SLDPRT")
SWX = [sys.executable, os.path.join(HERE, "swx.py")]

V0 = 60 * 60 * 6
HOLE = lambda d: math.pi * d * d / 4 * 6           # noqa: E731
CORNERS = 4 * (9 - math.pi * 9 / 4) * 6            # four R3 vertical-edge fillets on a 6 mm plate
STEPS = [  # (request, check(info) -> (ok, measured))
    ("מה הקוטר של החור בפלטה?", None),
    ("תשנה את קוטר החור ל-12 ממ", ("HOLE_D", 12, V0 - HOLE(12))),
    ("תוסיף פילט 3 ממ לארבע הפינות האנכיות של הפלטה", (None, None, V0 - HOLE(12) - CORNERS)),
    ("תחזיר את קוטר החור ל-11", ("HOLE_D", 11, V0 - HOLE(11) - CORNERS)),
    ("select-hole", None),
    ("מה בחרתי? תן קוטר ומיקום", None),
]


def swx(*args):
    r = subprocess.run(SWX + list(args), capture_output=True, encoding="utf-8")
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    return json.loads(lines[-1]) if lines else {"raw": r.stdout[-500:]}


def build_plate():
    os.makedirs(SCR, exist_ok=True)
    script = os.path.join(SCR, "_bench_build.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(f'''import os
for d in [sw.ActiveDoc]:
    pass
t = sw.GetOpenDocumentByName({PLATE!r})
if t is not None:
    sw.CloseDoc(T(t, "IModelDoc2").GetTitle())
pb = PartBuilder(sw, {{"PLATE_W": 60, "PLATE_D": 60, "PLATE_T": 6, "HOLE_D": 11}})
with pb.sketch("Top Plane", "SK_PLATE") as s:
    s.rect(0, 0, "PLATE_W", "PLATE_D")
pb.extrude("SK_PLATE", "PLATE_T", "PLATE")
with pb.sketch("Top Plane", "SK_HOLE") as s:
    s.circle(0, 0, "HOLE_D")
pb.cut("SK_HOLE", 0, "HOLE", mode="through")
pb.save({PLATE!r})
''')
    return swx("run", script)


def select_hole():
    script = os.path.join(SCR, "_bench_select.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write('''doc.ClearSelection2(True)
body = T(T(doc, "IPartDoc").GetBodies2(0, True)[0], "IBody2")
for fc in body.GetFaces():
    fc = T(fc, "IFace2")
    if T(fc.GetSurface(), "ISurface").IsCylinder():
        T(fc, "IEntity").Select4(False, None)
        break
print("selected", doc.SelectionManager.GetSelectedObjectCount2(-1))
''')
    return swx("run", script)


def inject(obj):
    tmp = os.path.join(PANEL, "inject.json.t")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(PANEL, "inject.json"))


def token_rows():
    try:
        with open(os.path.join(PANEL, "tokens.csv"), encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def ask(text, timeout=300):
    n = len(token_rows())
    t = time.time()
    inject({"text": text})
    while time.time() - t < timeout:
        rows = token_rows()
        if len(rows) > n:
            return rows[-1], round(time.time() - t, 1)
        time.sleep(0.3)
    return None, None


def last_reply():
    with open(os.path.join(PANEL, "chat.log.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(l) for l in f]
    return next((r["text"] for r in reversed(rows) if r["who"] == "claude"), "")


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "run"
    b = build_plate()
    info = swx("info")
    print("plate:", info.get("size"), "doc:", info.get("doc"))
    inject({"flag": "new"})
    time.sleep(1.5)
    out = []
    for req, check in STEPS:
        if req == "select-hole":
            select_hole()
            continue
        row, wall = ask(req)
        info = swx("info", "--full")
        vol = (info.get("size") or {}).get("volume_mm3")
        eqs = {e["eq"].split("=")[0].strip().strip('"'): e["value"] for e in info.get("equations", [])}
        verdict = ""
        if check:
            name, want, vexp = check
            okv = vol is not None and abs(vol - vexp) < 0.05
            okp = name is None or abs(eqs.get(name, -1) - want) < 1e-6
            verdict = f"{'PASS' if okv and okp else 'FAIL'} vol {vol} vs {vexp:.3f}"
        else:
            rep = last_reply()
            verdict = "reply: " + rep[:90].replace("\n", " ")
        r = row or {}
        tot_in = sum(int(r.get(k, 0) or 0) for k in ("input", "cache_write", "cache_read"))
        out.append({"label": label, "request": req, "wall_s": wall, "turns": r.get("turns"),
                    "input": r.get("input"), "cache_write": r.get("cache_write"),
                    "cache_read": r.get("cache_read"), "output": r.get("output"), "total_in": tot_in,
                    "check": verdict})
        print(f"{wall:>6} s  turns {r.get('turns')}  in {tot_in:>7} (new {int(r.get('input', 0) or 0) + int(r.get('cache_write', 0) or 0):>6})"
              f"  out {r.get('output'):>5}  | {req} | {verdict}")
    f = os.path.join(PANEL, "bench.csv")
    new = not os.path.exists(f)
    with open(f, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        if new:
            w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
