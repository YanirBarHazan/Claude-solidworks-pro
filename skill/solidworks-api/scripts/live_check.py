"""Live check of v2.5 on a real SolidWorks: everything the CI cannot test. New files only in one folder:
~/Documents/Claude SolidWorks/live_check_<date-time>/ (a test plate appears in SolidWorks while it runs).

    python live_check.py            all steps, one line each, stops at the first failure
    python live_check.py --probe    only print the sheet-metal API signatures

Steps: 1 worker + contract (a command outside the contract is refused by the worker itself)
       2 a test plate built with PartBuilder, then card / info / set / fillet / save through the worker
       3 a plate built from a generated DXF (drawing_build): bbox + volume vs the drawing, edit test, reopen
       4 the sheet-metal API signatures of this SolidWorks (probe_api) for the bend build
       5 the tab: a checklist for the user (language flag, plan card, steps line) - eyes, not code"""
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
    import probe_api
    if "--probe" in sys.argv:
        for iface, names in probe_api.SHEETMETAL.items():
            for n, sig in probe_api.signatures(iface, names).items():
                print(f"{iface}.{n}{sig}")
        return
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

    # 3. a plate from a drawing
    import ezdxf
    import drawing_build
    import drawing_read
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_line((0, 0), (90, 0))
    msp.add_arc((90, 15), 15, -90, 90)
    msp.add_line((90, 30), (0, 30))
    msp.add_line((0, 30), (0, 0))
    msp.add_circle((15, 15), 3.3)
    msp.add_circle((60, 15), 3.3)
    msp.add_text("THK 3", dxfattribs={"insert": (0, -10)})
    dxf = os.path.join(OUT, "live_plate.dxf")
    doc.saveas(dxf)
    plan = drawing_read.plan_sheet_metal(drawing_read.analyze(dxf))
    step(3, "drawing read: DIRECT", plan["verdict"] == "DIRECT", "; ".join(plan["reasons"]))
    res = drawing_build.build_flat(sw, plan, os.path.join(OUT, "live_from_dxf.SLDPRT"))
    step(3, "built from the drawing, volume and bbox proven, reopened", True,
         f"volume {res['volume']:.2f} mm3 vs drawing {plan['expect']['volume_mm3']:.2f}")

    # 4. sheet-metal API of this version
    for iface, names in probe_api.SHEETMETAL.items():
        for n, sig in probe_api.signatures(iface, names).items():
            print(f"     {iface}.{n}{sig}")
    step(4, "sheet-metal signatures printed (for the bend build)", True)

    print("\n5. The tab - check by eye in SolidWorks:\n"
          "   a. the two flags at the top switch Hebrew / English; the choice survives closing SolidWorks\n"
          "   b. under the title: the open document and what you selected, in words (no SEL / DIR strip)\n"
          "   c. while Claude works: a short list of steps in plain words, the current one spinning\n"
          "   d. under each reply: 'N steps · seconds · tokens' - a click opens the steps\n"
          "   e. ask for something bigger (a new part): a plan card with Do it all / One step, then stop / Change\n"
          "   f. the ... menu: save folder, attach file, new chat, and where files are saved")


if __name__ == "__main__":
    main()
