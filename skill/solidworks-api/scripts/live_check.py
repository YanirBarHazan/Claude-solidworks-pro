"""Live check of v2.5 on a real SolidWorks: everything the CI cannot test. New files only in one folder:
~/Documents/Claude SolidWorks/live_check_<date-time>/ (a test plate appears in SolidWorks while it runs).

    python live_check.py            all steps, one line each, stops at the first failure

Steps: 1 worker + contract (a command outside the contract is refused by the worker itself)
       2 a test plate built with PartBuilder, then card / info / set / fillet / save through the worker
       3 background work: a part built hidden (run --background) and read with --doc while the user's document
         stays active; a snapshot PNG of it
       4 the tab: a checklist for the user (language flag, plan card, steps line) - eyes, not code"""
import json
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(os.path.expanduser("~"), "Documents", "Claude SolidWorks", "live_check_" + time.strftime("%Y%m%d-%H%M%S"))


def step(n, text, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {n}. {text}" + (f" - {detail}" if detail else ""), flush=True)
    if not ok:
        sys.exit(1)


def raw_worker(cmd, args):
    """Talk to the worker directly (skipping swx's own contract check) to prove the worker refuses by itself."""
    w = json.load(open(os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel", "worker.json")))
    with socket.create_connection(("127.0.0.1", w["port"]), timeout=30) as s:
        s.sendall((json.dumps({"token": w["token"], "cmd": cmd, "args": args}) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            data += s.recv(65536)
    return json.loads(data)


def main():
    os.makedirs(OUT, exist_ok=True)
    print(f"test files go to {OUT}; a test plate will appear in SolidWorks")
    import swx
    step(1, "worker started", swx.ensure_worker())
    r = raw_worker("active", [])
    step(1, "worker refuses a command outside the contract", not r["ok"] and "unknown command" in r["result"])

    # 2. a test plate, then the worker commands on it
    import sw_common as c
    import swcad
    sw = c.connect()
    pb = swcad.PartBuilder(sw, {"W": 80, "H": 50, "T": 4})
    with pb.sketch("Front Plane", "SK_PLATE") as sk:
        sk.rect(0, 0, "W", "H")
    pb.extrude("SK_PLATE", "T", "PLATE")
    plate = pb.save(os.path.join(OUT, "live_plate.SLDPRT"))
    step(2, "test plate built and saved", os.path.exists(plate), plate)
    r = swx.call("info", [])
    step(2, "info on the plate", r["ok"] and r["result"]["kind"] == "part", r["result"]["size"] if r["ok"] else r)
    r = swx.call("card", [])
    step(2, "card on the plate", r["ok"] and "globals:" in (r.get("printed") or ""))
    r = swx.call("set", ["T=6"])
    vol = r["result"]["size_after"]["volume_mm3"] if r["ok"] else None
    step(2, "set T=6 in place", r["ok"] and abs(vol - 80 * 50 * 6) < 0.01, f"volume {vol}")
    r = swx.call("fillet", ["2", "--edges", "z"])
    step(2, "fillet R2 driven by a new global", r["ok"] and r["result"]["global"] and not r["result"]["rebuild_errors"],
         r["result"] if r["ok"] else r["result"][-300:])
    r = swx.call("save", [])
    step(2, "save", r["ok"] and r["result"]["saved"])

    # 3. background work: hidden build, --doc, snapshot - the user's document stays the active one
    script = os.path.join(OUT, "bg_part.py")
    target = os.path.join(OUT, "live_bg.SLDPRT")
    with open(script, "w", encoding="utf-8") as f:
        f.write("pb = PartBuilder(sw, {'D': 30, 'L': 40})\n"
                "with pb.sketch('Front Plane', 'SK_ROD') as sk:\n    sk.circle(0, 0, 'D')\n"
                "pb.extrude('SK_ROD', 'L', 'ROD')\n"
                f"pb.save({target!r})\n")
    active_before = swx.call("info", [])["result"]["doc"]
    r = swx.call("run", [script, "--background"])
    step(3, "a part built in the background", r["ok"] and os.path.exists(target), "" if r["ok"] else r["result"][-300:])
    r = swx.call("info", [])
    step(3, "the user's document is still the active one", r["ok"] and r["result"]["doc"] == active_before,
         r["result"]["doc"] if r["ok"] else r)
    r = swx.call("set", ["L=50", "--doc", target])
    vol = r["result"]["size_after"]["volume_mm3"] if r["ok"] else None
    step(3, "set --doc on the hidden part", r["ok"] and abs(vol - 3.14159265 * 15 ** 2 * 50) < 1, f"volume {vol}")
    r = swx.call("snapshot", ["--doc", target, "--out", os.path.join(OUT, "live_bg.png")])
    step(3, "snapshot PNG", r["ok"] and os.path.exists(os.path.join(OUT, "live_bg.png")), r["result"])
    r = swx.call("info", [])
    step(3, "the user's document is active again after the snapshot", r["ok"] and r["result"]["doc"] == active_before)

    print("\n4. The tab - check by eye in SolidWorks:\n"
          "   a. the two flags at the top switch Hebrew / English; the choice survives closing SolidWorks\n"
          "   b. under the title: the open document and what you selected, in words (no SEL / DIR strip)\n"
          "   c. while Claude works: a short list of steps in plain words, the current one spinning\n"
          "   d. under each reply: 'N steps · seconds · tokens' - a click opens the steps\n"
          "   e. ask for something bigger (a new part): a plan card with Do it all / One step, then stop / Change\n"
          "   f. the ... menu: save folder, attach file, new chat, agents at a time, and where files are saved\n"
          "   g. ask for an assembly of three separate parts: the plan offers agents; after 'Do it all' a strip with a\n"
          "      flow chart and one card per agent appears, each with its step and, at the end, a picture")


if __name__ == "__main__":
    main()
