"""Stage-0 test of the Python panel window (swpanel_window.py) on SolidWorks 2019.

    python swpanel_window_test.py         open the panel if needed, run the checks, leave the panel open

Writes ~/.solidworks-api/swpanel/window_test_result.json. Uses a scratch part only (never saved).
"""
import json
import os
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
TITLE = "Claude - SolidWorks"
HEB = ["בדיקה 1: חור Ø11 עודכן", "שלב 2 — \"מרכאות\" ו-\\ לוכסן", "סיום: 65 מ\"מ, 0 בניות מחדש"]


def wjson(path, obj):
    with open(path + ".t", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(path + ".t", path)


def seen():
    try:
        with open(os.path.join(PANEL, "seen.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def wait_seen(pred, timeout=8):
    t = time.time()
    while time.time() - t < timeout:
        s = seen()
        if s and pred(s):
            return round(time.time() - t, 2), s
        time.sleep(0.1)
    return None, seen()


def sw_hwnd():
    r = []
    win32gui.EnumWindows(lambda h, _: r.append(h) if win32gui.IsWindowVisible(h) and
                         win32gui.GetWindowText(h).startswith("SOLIDWORKS") else None, None)
    return r[0] if r else 0


def com_ms(sw):
    t = time.time()
    sw.RevisionNumber()
    return round((time.time() - t) * 1000, 1)


def main():
    res = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    sw = c.connect()
    res["rev"] = sw.RevisionNumber()
    if not win32gui.FindWindow(None, TITLE):
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        subprocess.Popen([pyw, os.path.join(HERE, "swpanel_window.py")])
    t = time.time()
    while not win32gui.FindWindow(None, TITLE) and time.time() - t < 15:
        time.sleep(0.05)
    res["window_up_s"] = round(time.time() - t, 2)
    h = win32gui.FindWindow(None, TITLE)
    res["window_visible"] = bool(h and win32gui.IsWindowVisible(h))
    ex = win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE) if h else 0
    res["topmost"] = bool(ex & win32con.WS_EX_TOPMOST)

    # (b) 2 s refresh
    time.sleep(2.5)
    k0, t0 = seen().get("ticks", 0), time.time()
    time.sleep(12)
    k1 = seen().get("ticks", 0)
    res["ticks_12s"] = k1 - k0
    res["poll_period_s"] = round((time.time() - t0) / max(k1 - k0, 1), 2)

    # (c) Hebrew UTF-8 round trip status.json -> label -> seen.json
    ok, lat = [], []
    for txt in HEB:
        wjson(os.path.join(PANEL, "status.json"), {"schema": "swpanel.status/0", "text": txt})
        dt, _ = wait_seen(lambda s, x=txt: s.get("shown") == x)
        ok.append(dt is not None)
        lat.append(dt)
    res["hebrew_ok"], res["status_latency_s"] = ok, lat

    # (a) work while open: new part, select a plane -> panel must show the document and 1 selected
    res["com_ms_before"] = com_ms(sw)
    doc = c.new_doc(sw, "part")
    title = doc.GetTitle()
    doc.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, c.NOTHING, 0)
    dt, s = wait_seen(lambda s: (s.get("sw") or {}).get("doc") == title and s["sw"].get("n") == 1, 8)
    res["panel_sees_doc_and_selection_s"] = dt
    doc.SketchManager.InsertSketch(True)
    doc.SketchManager.CreateCircleByRadius(0, 0, 0, 0.0055)
    doc.SketchManager.InsertSketch(True)
    doc.FeatureManager.FeatureExtrusion2(True, False, False, 0, 0, 0.02, 0, False, False, False, False,
                                         0, 0, False, False, False, False, True, True, True, 0, 0, False)
    vol = doc.Extension.CreateMassProperty().Volume
    res["part_volume_mm3"] = round(vol * 1e9, 1)
    res["expected_mm3"] = round(3.14159265 * 5.5 ** 2 * 20, 1)

    # the action suspected in the VBA hang: minimise / restore / hide / show SolidWorks while the panel polls
    hw = sw_hwnd()
    k0 = seen().get("ticks", 0)
    ms = []
    for cmd in (win32con.SW_MINIMIZE, win32con.SW_RESTORE, win32con.SW_HIDE, win32con.SW_SHOW):
        win32gui.ShowWindow(hw, cmd)
        time.sleep(1.5)
        ms.append(com_ms(sw))
    time.sleep(2.5)
    res["sw_com_ms_after_min_restore_hide_show"] = ms
    res["ticks_during_window_games"] = seen().get("ticks", 0) - k0
    sw.CloseDoc(title)
    dt, s = wait_seen(lambda s: (s.get("sw") or {}).get("doc") is None, 8)
    res["panel_sees_close_s"] = dt
    res["panel_worker_call_s"] = (seen().get("sw") or {}).get("call_s")
    res["window_still_open"] = bool(win32gui.FindWindow(None, TITLE))
    wjson(os.path.join(PANEL, "window_test_result.json"), res)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
