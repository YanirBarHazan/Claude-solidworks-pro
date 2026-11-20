"""Stage-1 test of the panel's selection reader (swpanel_worker `info`) inside nested assemblies.

Model, built by the skill's rules in a temporary folder: PLATE (60x60x6, Ø11 hole off centre, globals HOLE_X/HOLE_Z/
HOLE_D) -> SUB.sldasm (plate placed by 3 plane mates, one distance mate 100) -> TOP.sldasm (SUB placed by 3 plane
mates, distance mates 250 and 40). Checks, each against SolidWorks' own Measure tool (independent of the worker):
  1. hole's circular edge: radius 5.5 +-0.001, centre in TOP coordinates = Measure centre +-0.001
  2. hole's cylindrical face: radius 5.5, axis direction in TOP coordinates parallel to the plate normal
  3. HOLE feature: name, component chain SUB-1/PLATE-1
  4. PLATE component: chain, and the part's globals offered for `set --selected`
Needs the warm worker (started by the tab; or run swpanel_worker.py). Closes its documents at the end.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(tempfile.gettempdir(), "swpanel_seltest")
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
os.environ["SW_OUT"] = OUT
sys.path.insert(0, HERE)
import sw_common as c  # noqa: E402
from sw_common import T, new_doc, save_as, close_out_docs  # noqa: E402
from swcad import PartBuilder  # noqa: E402
from asmtools import _mate, mate_errors, fix_only  # noqa: E402

C, MM = c.swconst.constants, 1e-3
TOL = 1e-3


def swx(*args):
    r = subprocess.run([sys.executable, os.path.join(HERE, "swx.py")] + list(args), capture_output=True,
                       encoding="utf-8")
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    return json.loads(lines[-1]) if lines else {"raw": r.stdout[-800:]}


def asm_with(sw, child, name, mates):
    sw.OpenDoc6(child, C.swDocASSEMBLY if child.lower().endswith(".sldasm") else C.swDocPART,
                C.swOpenDocOptions_Silent, "", 0, 0)
    doc = new_doc(sw, "asm")
    asm = T(doc, "IAssemblyDoc")
    sw.ActivateDoc3(doc.GetTitle(), False, 0, 0)
    cm = T(asm.AddComponent5(child, 0, "", False, "", 0.05, 0.02, 0.03), "IComponent2")
    path = os.path.join(OUT, name + ".sldasm")
    save_as(doc, path)
    doc.ClearSelection2(True)               # the first component comes in fixed: float it, the mates place it
    cm.Select4(False, None, False)
    asm.UnfixComponent()
    doc.ClearSelection2(True)
    for (pc, pa, kind, dist) in mates:
        a, b = f"{pc}@{cm.Name2}@{name}", f"{pa}"
        _mate(doc, kind, C.swMateAlignALIGNED, [(a, "PLANE"), (b, "PLANE")], dist=dist)
    doc.ForceRebuild3(False)
    save_as(doc, path)
    return doc, asm, cm, path


def main():
    sw = c.connect()
    pb = PartBuilder(sw, {"PLATE_W": 60, "PLATE_D": 60, "PLATE_T": 6, "HOLE_X": 10, "HOLE_Z": 15, "HOLE_D": 11})
    with pb.sketch("Top Plane", "SK_PLATE") as s:
        s.rect(0, 0, "PLATE_W", "PLATE_D")
    pb.extrude("SK_PLATE", "PLATE_T", "PLATE")
    with pb.sketch("Top Plane", "SK_HOLE") as s:
        s.circle("HOLE_X", "HOLE_Z", "HOLE_D")
    pb.cut("SK_HOLE", 0, "HOLE", mode="through")
    plate = pb.save(os.path.join(OUT, "PLATE.sldprt"))
    sw.CloseDoc(pb.doc.GetTitle())
    D, Co = C.swMateDISTANCE, C.swMateCOINCIDENT
    sdoc, _, _, sub = asm_with(sw, plate, "SUB", [("Right Plane", "Right Plane", D, 100.0),
                                                   ("Top Plane", "Top Plane", Co, 0.0),
                                                   ("Front Plane", "Front Plane", Co, 0.0)])
    se = mate_errors(sdoc)
    sw.CloseDoc(sdoc.GetTitle())
    doc, asm, subc, top = asm_with(sw, sub, "TOP", [("Right Plane", "Right Plane", D, 250.0),
                                                     ("Top Plane", "Top Plane", D, 40.0),
                                                     ("Front Plane", "Front Plane", Co, 0.0)])
    res = {"mate_errors": {"SUB": se, "TOP": mate_errors(doc)}}
    plc = next(T(x, "IComponent2") for x in asm.GetComponents(False) if T(x, "IComponent2").Name2.endswith("PLATE-1"))
    body = T(plc.GetBody(), "IBody2")

    def select(ent):
        doc.ClearSelection2(True)
        T(ent, "IEntity").Select4(False, None)

    def measure():
        m = T(doc.Extension.CreateMeasure(), "IMeasure")
        m.ArcOption = 0           # 0 = arc centre (1 = minimum distance, 2 = maximum)
        m.Calculate(None)
        return m

    checks = []
    # 1. circular edge of the hole (top rim)
    edge = next(T(e, "IEdge") for e in body.GetEdges() if T(T(e, "IEdge").GetCurve(), "ICurve").IsCircle())
    select(edge)
    s = swx("info")["selection"][0]
    # Measure from the arc centre to TOP's origin: |DeltaX/Y/Z| = |centre| in TOP coordinates
    doc.Extension.SelectByID2("Point1@Origin", "EXTSKETCHPOINT", 0, 0, 0, True, 0, None, 0)
    m = measure()
    want = [abs(m.DeltaX) / MM, abs(m.DeltaY) / MM, abs(m.DeltaZ) / MM]
    got = s.get("in_assembly", {}).get("center")
    ok = abs(s.get("radius", 0) - 5.5) <= TOL and got and all(abs(abs(a) - b) <= TOL for a, b in zip(got, want))
    checks.append(("edge: radius 5.5, centre in TOP = Measure", ok,
                   f"r {s.get('radius')} | centre {got} vs Measure {[round(v, 4) for v in want]}"))
    # 2. cylindrical face
    face = next(T(f, "IFace2") for f in body.GetFaces() if T(T(f, "IFace2").GetSurface(), "ISurface").IsCylinder())
    select(face)
    s = swx("info")["selection"][0]
    ax = s.get("in_assembly", {}).get("axis", [0, 0, 0])
    ok = abs(s.get("radius", 0) - 5.5) <= TOL and abs(abs(ax[1]) - 1) <= TOL
    checks.append(("face: radius 5.5, axis in TOP along Y (plate normal)", ok,
                   f"r {s.get('radius')} axis {ax} feature {s.get('feature')}"))
    # 3. HOLE feature inside the nested part
    f = T(plc.FeatureByName("HOLE"), "IFeature")
    doc.ClearSelection2(True)
    f.Select2(False, 0)
    s = swx("info")["selection"][0]
    ok = s.get("name") == "HOLE" and s.get("component") == "SUB-1/PLATE-1"
    checks.append(("feature: name + chain", ok, f"{s.get('name')} | {s.get('component')}"))
    # 4. the PLATE component itself
    doc.ClearSelection2(True)
    plc.Select4(False, None, False)
    s = swx("info")["selection"][0]
    g = s.get("component_globals", {})
    ok = s.get("component") == "SUB-1/PLATE-1" and g.get("HOLE_D") == 11.0
    checks.append(("component: chain + part globals for set --selected", ok,
                   f"{s.get('component')} | globals {g}"))
    # 5. the acceptance-test path: component selected in the nested assembly -> set in place -> measure from TOP
    r = swx("set", "HOLE_D=12", "--selected")
    body = T(plc.GetBody(), "IBody2")
    edge = next(T(e, "IEdge") for e in body.GetEdges() if T(T(e, "IEdge").GetCurve(), "ICurve").IsCircle())
    select(edge)
    s = swx("info")["selection"][0]
    nf = len(swx("info", "--full")["features"])
    plc.Select4(False, None, False)
    back = swx("set", "HOLE_D=11", "--selected")
    ok = r.get("changed", [{}])[0].get("new") == 12.0 and abs(s.get("radius", 0) - 6.0) <= TOL \
        and not r.get("rebuild_errors") and not r.get("top_errors") and back.get("changed", [{}])[0].get("new") == 11.0
    checks.append(("set HOLE_D=12 --selected in place, measured from TOP, back to 11", ok,
                   f"{r.get('doc')}: {r.get('changed')} | edge r {s.get('radius')} | errors {r.get('rebuild_errors')}"
                   f"/{r.get('top_errors')} | TOP features {nf} | back {back.get('changed')}"))
    doc.ClearSelection2(True)
    sw.CloseDoc(doc.GetTitle())
    close_out_docs(sw)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ->  {detail}")
    print("mate errors:", res["mate_errors"])
    shutil.rmtree(OUT, ignore_errors=True)
    sys.exit(0 if all(ok for _, ok, _ in checks) else 1)


if __name__ == "__main__":
    main()
