"""Stage-0 spike of the SolidWorks Claude panel: modeless form, 2 s status polling, Hebrew + UTF-8 JSON.

    python swpanel_spike.py run      deploy + launch the spike form, run the automatic checks, leave the form open
    python swpanel_spike.py close    close the form (WM_CLOSE), check the timer stopped

Results: ~/.solidworks-api/swpanel/spike_result.json. Refuses any SolidWorks other than 2019 (rev 27.x)
unless SW_REQUIRE_REV is set to another prefix.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("SW_REQUIRE_REV", "27.")
os.environ.setdefault("SW_OUT", os.path.join(tempfile.gettempdir(), "swpanel_scratch"))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sw_common as c  # noqa: E402
import win32con  # noqa: E402
import win32gui  # noqa: E402

PANEL = os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel")
SRC = os.path.join(HERE, "..", "swpanel", "vba", "swpanel_spike.swb")
CAPTION = "Claude - SolidWorks panel (spike)"
HEB_STATUS = ["בדיקה 1: חור Ø11 ← עודכן", "שלב 2 — \"מרכאות\" ו-\\ לוכסן", "סיום ✓ 65 מ\"מ"]


def wjson(path, obj):
    tmp = path + ".py.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def rjson(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def hwnd():
    return win32gui.FindWindow("ThunderDFrame", CAPTION)


def ticks():
    s = rjson(os.path.join(PANEL, "seen.json"))
    return s["ticks"] if s else -1


def run():
    res = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    os.makedirs(PANEL, exist_ok=True)
    for n in ("status.json", "seen.json", "request.json"):
        if os.path.exists(os.path.join(PANEL, n)):
            os.remove(os.path.join(PANEL, n))
    shutil.copyfile(SRC, os.path.join(PANEL, "swpanel_spike.swb"))
    sw = c.connect()
    res["rev"] = sw.RevisionNumber()

    # (a) launch: the macro keeps running (message loop) while the form is open, so RunMacro2 blocks;
    # it runs in a separate process, like the user's toolbar button would
    t = time.time()
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "launch"],
                     creationflags=subprocess.CREATE_NO_WINDOW)
    while not hwnd() and time.time() - t < 20:
        time.sleep(0.05)
    res["form_up_s"] = round(time.time() - t, 2)
    h = hwnd()
    res["form_window"] = bool(h) and bool(win32gui.IsWindowVisible(h))
    if not h:
        print(json.dumps(res, ensure_ascii=False))
        return

    # (b) timer: count ticks over 12 s with SolidWorks idle
    time.sleep(1)
    t0, k0 = time.time(), ticks()
    time.sleep(12)
    k1 = ticks()
    res["timer_ticks_12s"] = k1 - k0
    res["timer_period_s"] = round((time.time() - t0) / max(k1 - k0, 1), 2)

    # (c) Hebrew UTF-8 status -> label -> echoed back; latency
    lat = []
    ok = []
    for txt in HEB_STATUS:
        wjson(os.path.join(PANEL, "status.json"), {"schema": "swpanel.status/0", "text": txt})
        t = time.time()
        seen = None
        while time.time() - t < 8:
            s = rjson(os.path.join(PANEL, "seen.json"))
            if s and s.get("shown") == txt:
                seen = s
                break
            time.sleep(0.1)
        lat.append(round(time.time() - t, 2))
        ok.append(seen is not None)
        time.sleep(1.2)  # FileDateTime has 1 s resolution in the spike
    res["hebrew_roundtrip_ok"] = ok
    res["status_latency_s"] = lat

    # (a) work while the form is open: new part, sketch, extrude, read volume, close - timer must keep ticking
    k0 = ticks()
    t = time.time()
    doc = c.new_doc(sw, "part")
    doc.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, c.NOTHING, 0)
    doc.SketchManager.InsertSketch(True)
    doc.SketchManager.CreateCircleByRadius(0, 0, 0, 0.0055)
    doc.SketchManager.InsertSketch(True)
    feat = doc.FeatureManager.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0, False, False, False, False,
                                                0, 0, False, False, False, False, True, True, True, 0, 0, False)
    mp = c.T(doc, "IModelDoc2").Extension.CreateMassProperty()
    vol = mp.Volume if mp else None
    title = doc.GetTitle()
    sw.CloseDoc(title)
    res["work_while_open"] = {"feature": feat is not None, "volume_mm3": round(vol * 1e9, 1) if vol else None,
                              "expected_mm3": round(3.14159265 * 5.5 ** 2 * 20, 1),
                              "seconds": round(time.time() - t, 2)}
    time.sleep(4.5)
    res["ticks_during_work"] = ticks() - k0
    res["form_still_open"] = bool(hwnd())
    out = os.path.join(PANEL, "spike_result.json")
    wjson(out, res)
    print(json.dumps(res, ensure_ascii=False, indent=1))


def launch():
    sw = c.connect()
    t = time.time()
    r = sw.RunMacro2(os.path.join(PANEL, "swpanel_spike.swb"), "swpanel_spike", "main", 0)
    wjson(os.path.join(PANEL, "launch_result.json"),
          {"ok": bool(r[0] if isinstance(r, tuple) else r), "macro_ran_s": round(time.time() - t, 1)})


def close():
    h = hwnd()
    if not h:
        print("form not open")
        return
    win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
    time.sleep(1.5)
    k0 = ticks()
    time.sleep(5)
    print(json.dumps({"window_gone": not hwnd(), "ticks_after_close": ticks() - k0}))


if __name__ == "__main__":
    {"run": run, "launch": launch, "close": close}[sys.argv[1] if len(sys.argv) > 1 else "run"]()
