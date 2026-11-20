"""Speed benchmark of fast mode (version note 45) on an assembly built BY THE SKILL'S RECIPE (same as the
capability suite's skeleton assembly, scaled up): skeleton part with named reference planes, one post and one beam
mated to it (6 coincident mates on planes), named axes, two linear patterns whose counts and spacings are driven by
assembly equations. N_X=20, N_Z=17 -> 378 posts + 360 beams + skeleton = 739 components. Every component position
is checked against the expected transform, then a design change (SPAN_X 4000 -> 5000) is made in the assembly
equations and checked again. Everything in a temporary folder; documents are closed at the end.

    python bench_asm.py         both modes (SW_FAST=0, then 1) in separate processes, table at the end
"""
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
G = {"H": 2500.0, "SPAN_X": 4000.0, "SPAN_Z": 4000.0, "N_X": 20, "N_Z": 17}


def one():
    out = os.path.join(tempfile.gettempdir(), "swbench_asm_" + os.environ.get("SW_FAST", "1"))
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    os.environ["SW_OUT"] = out
    sys.path.insert(0, HERE)
    import pythoncom
    from win32com.client import VARIANT
    import sw_common as c
    from sw_common import T, new_doc, save_as, close_out_docs
    from swcad import PartBuilder
    from asmtools import _mate, mate_errors, linear_pattern, set_equation, drive_pattern, fix_only
    C, MM = c.swconst.constants, 1e-3
    sw = c.connect()
    res, t = {"fast": os.environ.get("SW_FAST", "1")}, time.time()

    files = {}
    pb = PartBuilder(sw, {"H": G["H"], "SPAN_X": G["SPAN_X"], "SPAN_Z": G["SPAN_Z"]})
    pb.plane("PL_TOP", "H", base="Top Plane")
    pb.plane("PL_X1", "SPAN_X", base="Right Plane")
    pb.plane("PL_Z1", "SPAN_Z", base="Front Plane")
    files["SKEL"] = pb.save(os.path.join(out, "SKEL.sldprt"))
    sw.CloseDoc(pb.doc.GetTitle())
    pb = PartBuilder(sw, {"H": G["H"], "D": 80.0})
    with pb.sketch("Front Plane", "SK_POST") as s:
        s.circle(0, 0, "D")
    pb.extrude("SK_POST", "H", "POST_BODY")
    files["POST"] = pb.save(os.path.join(out, "POST.sldprt"))
    sw.CloseDoc(pb.doc.GetTitle())
    pb = PartBuilder(sw, {"L": G["SPAN_X"], "B": 60.0})
    with pb.sketch("Front Plane", "SK_BEAM") as s:
        s.rect(0, 0, "B", "B")
    pb.extrude("SK_BEAM", "L", "BEAM_BODY")
    files["BEAM"] = pb.save(os.path.join(out, "BEAM.sldprt"))
    sw.CloseDoc(pb.doc.GetTitle())
    res["parts_s"] = round(time.time() - t, 1)

    t = time.time()
    for f in files.values():
        sw.OpenDoc6(f, C.swDocPART, C.swOpenDocOptions_Silent, "", 0, 0)
    doc = new_doc(sw, "asm")
    asm = T(doc, "IAssemblyDoc")
    sw.ActivateDoc3(doc.GetTitle(), False, 0, 0)
    mu = T(sw.GetMathUtility(), "IMathUtility")

    def add(f, axes, o):
        cm = T(asm.AddComponent5(f, 0, "", False, "", 0, 0, 0), "IComponent2")
        xf = [v for a in axes for v in a] + [v * MM for v in o] + [1.0, 0.0, 0.0, 0.0]
        cm.Transform2 = mu.CreateTransform(VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, xf))
        return cm
    skel = add(files["SKEL"], ((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0, 0, 0))
    fix_only(doc, skel)
    post = add(files["POST"], ((1, 0, 0), (0, 0, -1), (0, 1, 0)), (0, 0, 0))
    beam = add(files["BEAM"], ((0, 1, 0), (0, 0, 1), (1, 0, 0)), (0, G["H"], 0))
    path = os.path.join(out, "GRID.sldasm")
    save_as(doc, path)
    A, sk, po, be = "GRID", skel.Name2, post.Name2, beam.Name2
    for a, b in ((f"Front Plane@{po}@{A}", f"Top Plane@{sk}@{A}"), (f"Right Plane@{po}@{A}", f"Right Plane@{sk}@{A}"),
                 (f"Top Plane@{po}@{A}", f"Front Plane@{sk}@{A}"), (f"Front Plane@{be}@{A}", f"Right Plane@{sk}@{A}"),
                 (f"Top Plane@{be}@{A}", f"Front Plane@{sk}@{A}"), (f"Right Plane@{be}@{A}", f"PL_TOP@{sk}@{A}")):
        _mate(doc, C.swMateCOINCIDENT, C.swMateAlignCLOSEST, [(a, "PLANE"), (b, "PLANE")])

    def axis(a, b, name):
        doc.ClearSelection2(True)
        doc.Extension.SelectByID2(a, "PLANE", 0, 0, 0, False, 0, None, 0)
        doc.Extension.SelectByID2(b, "PLANE", 0, 0, 0, True, 0, None, 0)
        doc.InsertAxis2(True)
        last, f = None, doc.FirstFeature()
        while f is not None:
            f = T(f, "IFeature")
            last = f if f.GetTypeName2() == "RefAxis" else last
            f = f.GetNextFeature()
        last.Name = name
        doc.ClearSelection2(True)
        return last
    ax, az = axis("Top Plane", "Front Plane", "AX_X"), axis("Top Plane", "Right Plane", "AX_Z")
    sx, sz, nx, nz = G["SPAN_X"], G["SPAN_Z"], G["N_X"], G["N_Z"]
    pp = linear_pattern(doc, [post], ax, nx + 1, sx, az, nz + 1, sz, flip1=True, flip2=False, name="PAT_POSTS")
    pm = linear_pattern(doc, [beam], ax, nx, sx, az, nz + 1, sz, flip1=True, flip2=False, name="PAT_BEAMS")
    for k in ("SPAN_X", "SPAN_Z", "N_X", "N_Z"):
        set_equation(doc, k, f"{G[k]:g}")
    drive_pattern(doc, pp, n1='"N_X" + 1', s1='"SPAN_X"', n2='"N_Z" + 1', s2='"SPAN_Z"')
    drive_pattern(doc, pm, n1='"N_X"', s1='"SPAN_X"', n2='"N_Z" + 1', s2='"SPAN_Z"')
    doc.ForceRebuild3(False)
    save_as(doc, path)
    res["assemble_mate_pattern_s"] = round(time.time() - t, 1)

    def check(sx, sz, nx, nz, h):
        have = collections.Counter()
        for cm in asm.GetComponents(True) or ():
            cm = T(cm, "IComponent2")
            d = list(T(cm.Transform2, "IMathTransform").ArrayData)
            have[(os.path.splitext(os.path.basename(cm.GetPathName()))[0],)
                 + tuple(round(v / MM, 1) for v in d[9:12])] += 1
        want = collections.Counter({("SKEL", 0.0, 0.0, 0.0): 1})
        for i in range(nx + 1):
            for j in range(nz + 1):
                want[("POST", round(i * sx, 1), 0.0, round(j * sz, 1))] += 1
        for i in range(nx):
            for j in range(nz + 1):
                want[("BEAM", round(i * sx, 1), round(h, 1), round(j * sz, 1))] += 1
        if have != want:
            raise AssertionError(f"missing {sum((want - have).values())}, extra {sum((have - want).values())}")
        return sum(have.values())

    t = time.time()
    res["components"] = check(sx, sz, nx, nz, G["H"])
    res["mate_errors"] = len(mate_errors(doc))
    res["check_positions_s"] = round(time.time() - t, 1)
    t = time.time()
    n, f = 0, doc.FirstFeature()
    while f is not None:
        f = T(f, "IFeature")
        f.Name
        f = f.GetNextFeature()
        n += 1
    res["tree_features"], res["tree_walk_s"] = n, round(time.time() - t, 1)
    t = time.time()
    set_equation(doc, "SPAN_X", "5000")
    doc.ForceRebuild3(False)
    check(5000, sz, nx, nz, G["H"])
    res["edit_span_and_recheck_s"] = round(time.time() - t, 1)
    sw.CloseDoc(doc.GetTitle())
    close_out_docs(sw)
    print("RESULT " + json.dumps(res))


def main():
    rows = []
    for mode in ("0", "1"):
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "one"], env=dict(os.environ, SW_FAST=mode),
                           capture_output=True, encoding="utf-8", errors="replace")
        line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
        if not line:
            print(f"mode {mode} failed:\n{(r.stdout + r.stderr)[-2000:]}")
            return
        rows.append(json.loads(line[7:]))
        print(rows[-1], flush=True)
        shutil.rmtree(os.path.join(tempfile.gettempdir(), "swbench_asm_" + mode), ignore_errors=True)
    print(f"{'':26s}{'normal':>9s}{'fast':>9s}{'x':>6s}")
    for k in ("parts_s", "assemble_mate_pattern_s", "check_positions_s", "tree_walk_s", "edit_span_and_recheck_s"):
        a, b = rows[0][k], rows[1][k]
        print(f"{k:26s}{a:>9}{b:>9}{(a / b if b else 0):>6.1f}")


if __name__ == "__main__":
    one() if len(sys.argv) > 1 and sys.argv[1] == "one" else main()
