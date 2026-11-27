"""Build a part from a drawing plan (drawing_read.plan_sheet_metal) and prove it against the drawing.

    python drawing_build.py part.dxf OUT.SLDPRT [--thickness 2]      read, plan, build, verify, save

What it builds today
  flat part (laser / waterjet / plate): the outline and holes of the drawing, extruded by the thickness.
     Globals: T (thickness) and HOLE_D<n> for each distinct hole diameter - the values a user changes.
     The outline itself is fixed geometry from the drawing (the drawing is its source).
  bends: refused for now with a clear message - the sheet-metal API calls are checked on a live SolidWorks
     first (probe_api.py), then added here. Nothing is built by guessing an API signature.
Proof: before building, the expected volume = flat area x T and the flat bounding box come from the drawing;
after building, PartBuilder.verify measures both, plus an edit test on T. A weight in the title block is
compared too when the material's density is known. UNTESTED on SolidWorks until the live check."""
import math
import os
import sys

import drawing_read


def hole_globals(holes):
    """Distinct circle diameters -> {HOLE_D1: 6.6, ...} and each hole's global name (profiles get None)."""
    names, out = {}, []
    for h in holes:
        if h["kind"] != "circle":
            out.append(None)
            continue
        d = round(h["d"], 4)
        if d not in names:
            names[d] = f"HOLE_D{len(names) + 1}"
        out.append(names[d])
    return {v: k for k, v in names.items()}, out


def expect_for(plan):
    """The hand calculation from the drawing: (bbox sizes, volume) as a function of the parameters."""
    w, h = plan["expect"]["flat_bbox_mm"]
    outer = plan["outline"]["area"] if plan["outline"]["kind"] == "profile" else math.pi * plan["outline"]["d"] ** 2 / 4
    profiles = sum(x["area"] for x in plan["holes"] if x["kind"] == "profile")
    circles = [x for x in plan["holes"] if x["kind"] == "circle"]
    gl, per = hole_globals(plan["holes"])

    def expect(p):
        area = outer - profiles - sum(math.pi * p[g] ** 2 / 4 for g, x in zip(per, plan["holes"]) if g)
        return [w, h, p["T"]], area * p["T"]
    return expect, gl, circles


def build_flat(sw, plan, out_path, name="PLATE"):
    import swcad
    if plan["bends"]:
        raise NotImplementedError("bends: the sheet-metal build waits for the live API check (probe_api.py)")
    expect, holes_gl, _ = expect_for(plan)
    params = {"T": plan["thickness"], **holes_gl}
    pb = swcad.PartBuilder(sw, params)
    gl, per = hole_globals(plan["holes"])
    with pb.sketch("Front Plane", f"SK_{name}") as sk:
        if plan["outline"]["kind"] == "circle":
            c = plan["outline"]
            sk.circle(c["center"][0], c["center"][1], c["d"])
        else:
            sk.profile(plan["outline"]["segments"])
        for g, hole in zip(per, plan["holes"]):
            if g:
                sk.circle(hole["center"][0], hole["center"][1], g)
            else:
                sk.profile(hole["segments"])
    pb.extrude(f"SK_{name}", "T", name)
    res = pb.verify(expect, edit=("T", round(plan["thickness"] * 1.5, 4)))
    pb.save(out_path)
    return {"path": out_path, "params": params, **res}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    src, out = sys.argv[1], os.path.abspath(sys.argv[2])
    t = float(sys.argv[sys.argv.index("--thickness") + 1]) if "--thickness" in sys.argv else None
    a = drawing_read.analyze(src)
    plan = drawing_read.plan_sheet_metal(a, thickness=t)
    print(drawing_read.summary(a, plan))
    if plan["verdict"] != "DIRECT":
        print("not built: the drawing does not fix the part by itself (see the reasons above)")
        sys.exit(1)
    import sw_common as c
    sw = c.connect()
    print(build_flat(sw, plan, out))
