"""PLAN_EQUATIONS phase 0 (2019): can ASSEMBLY equations drive dimensions inside component parts, and does it
survive save + close + reopen? Model built by the skill's rules in a temporary folder (parts by PartBuilder, every
component placed by plane mates, the first one floated):
  ROD_A.sldprt  rod, length = PLAIN dimension D1@ROD (its own link equation removed): to be driven from outside
  ROD_B.sldprt  rod, length = part global LEN (normal PartBuilder part)
  SUB.sldasm    2 x ROD_A (same file, two instances) + global SPAN
  TOP.sldasm    SUB + ROD_B + global SPAN_X
Cases (each: equation accepted? value after rebuild? after SPAN_X edit? after save + reopen? errors?)
  A  SUB equation drives a part dimension:        "D1@ROD@ROD_A<1>.Part" = "SPAN" - 100
  B  TOP equation drives a part GLOBAL:           "LEN@ROD_B<1>.Part" = "SPAN_X" / 2
  C  TOP equation drives a SUB global:            "SPAN@SUB<1>.Assembly" = "SPAN_X"
  D  both ROD_A instances follow (same file)
  E  atn units in an assembly equation:           "D2@SK_ROD@ROD_B<1>.Part" = 20 * atn(1)  (rod diameter)
Prints one PASS / FAIL line per case. Closes and deletes everything it made.
"""
import math
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(tempfile.gettempdir(), "spike_asm_eq")
shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
os.environ["SW_OUT"] = OUT
sys.path.insert(0, HERE)
import sw_common as c  # noqa: E402
from sw_common import T, new_doc, save_as, close_out_docs  # noqa: E402
from swcad import PartBuilder  # noqa: E402
from asmtools import _mate, mate_errors  # noqa: E402

C = c.swconst.constants
RES = []


def rod(name, plain):
    pb = PartBuilder(sw, {"LEN": 1000, "D": 20})
    with pb.sketch("Right Plane", "SK_ROD") as s:
        s.circle(0, 0, "D")
    pb.extrude("SK_ROD", "LEN", "ROD")
    if plain:                      # remove LEN and its link: D1@ROD becomes a plain dimension
        eq = T(pb.doc.GetEquationMgr(), "IEquationMgr")
        for i in reversed(range(eq.GetCount())):
            e = eq.Equation(i).replace(" ", "")
            if e.split("=")[0] in ('"LEN"', '"D"', '"D1@ROD"', '"D1@SK_ROD"'):
                eq.Delete(i)
        eq.EvaluateAll()
        pb.doc.ForceRebuild3(False)
        pb.globals.difference_update({"LEN", "D"})
        pb.links = []
    path = os.path.join(OUT, name + ".sldprt")
    pb.save(path)
    sw.CloseDoc(pb.doc.GetTitle())
    return path


def assembly(name, children):
    """children: [(path, [(child plane, assembly plane, kind, dist)])] - each child floated, then mated."""
    for p, _ in children:
        sw.OpenDoc6(p, C.swDocASSEMBLY if p.lower().endswith(".sldasm") else C.swDocPART,
                    C.swOpenDocOptions_Silent, "", 0, 0)
    doc = new_doc(sw, "asm")
    asm = T(doc, "IAssemblyDoc")
    sw.ActivateDoc3(doc.GetTitle(), False, 0, 0)
    path = os.path.join(OUT, name + ".sldasm")
    comps = []
    for k, (p, _) in enumerate(children):
        cm = T(asm.AddComponent5(p, 0, "", False, "", 0.01 * k, 0.02, 0.03 * k), "IComponent2")
        comps.append(cm)
    save_as(doc, path)
    for cm, (_, mates) in zip(comps, children):
        doc.ClearSelection2(True)
        cm.Select4(False, None, False)
        asm.UnfixComponent()
        for cp, ap, kind, dist in mates:
            _mate(doc, kind, C.swMateAlignALIGNED, [(f"{cp}@{cm.Name2}@{name}", "PLANE"), (ap, "PLANE")], dist=dist)
    doc.ForceRebuild3(False)
    save_as(doc, path)
    return doc, comps, path


def add_eq(doc, text):
    eq = T(doc.GetEquationMgr(), "IEquationMgr")
    i = eq.Add2(-1, text, True)
    eq.EvaluateAll()
    return i


def dim_value(comp, dim="D1@ROD"):
    md = T(comp.GetModelDoc2(), "IModelDoc2")
    p = md.Parameter(dim)
    return round(T(p, "IDimension").SystemValue * 1000, 3) if p is not None else None


def eq_errors(doc):
    out, f = [], doc.FirstFeature()
    while f is not None:
        f = T(f, "IFeature")
        code = f.GetErrorCode2()[0]
        if code:
            out.append(f"{f.Name}:{code}")
        f = f.GetNextFeature()
    return out


def check(tag, ok, detail):
    RES.append((tag, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {tag}  ->  {detail}", flush=True)


sw = c.connect()
A, B, Cr = rod("ROD_A", True), rod("ROD_B", False), rod("ROD_C", True)
F, Tp, R = "Front Plane", "Top Plane", "Right Plane"
D, Co = C.swMateDISTANCE, C.swMateCOINCIDENT
sub, (a1, a2), sub_path = assembly("SUB", [(A, [(F, F, Co, 0), (Tp, Tp, Co, 0), (R, R, Co, 0)]),
                                           (A, [(F, F, D, 4000), (Tp, Tp, Co, 0), (R, R, Co, 0)])])
check("SUB mates", not mate_errors(sub), f"errors {mate_errors(sub)}")
i_span = add_eq(sub, '"SPAN" = "D1@Distance1"')
i_a = add_eq(sub, '"D1@ROD@ROD_A<1>.Part" = "SPAN" - 100')
sub.ForceRebuild3(False)
check("A  SUB equation drives a part dimension", i_a >= 0 and dim_value(a1) == 3900.0,
      f"Add2 -> {i_a}; ROD_A<1> length {dim_value(a1)} (want 3900)")
check("D  both instances of ROD_A follow", dim_value(a2) == 3900.0, f"ROD_A<2> length {dim_value(a2)}")
save_as(sub, sub_path)
sw.CloseDoc(sub.GetTitle())

top, (sc, rb, rc), top_path = assembly("TOP", [(sub_path, [(F, F, Co, 0), (Tp, Tp, Co, 0), (R, R, Co, 0)]),
                                            (B, [(F, F, D, 300), (Tp, Tp, Co, 0), (R, R, Co, 0)]),
                                            (Cr, [(F, F, D, 600), (Tp, Tp, Co, 0), (R, R, Co, 0)])])
check("TOP mates", not mate_errors(top), f"errors {mate_errors(top)}")
add_eq(top, '"SPAN_X" = 4000')
i_b = add_eq(top, '"LEN@ROD_B<1>.Part" = "SPAN_X" / 2')
i_c = add_eq(top, '"SPAN@SUB<1>.Assembly" = "SPAN_X"')
i_c2 = add_eq(top, '"D1@Distance1@SUB<1>.Assembly" = "SPAN_X"')
i_l = add_eq(top, '"D1@ROD@ROD_C<1>.Part" = "SPAN_X" / 2')
i_e = add_eq(top, '"D1@SK_ROD@ROD_C<1>.Part" = 20 * atn(1)')
top.ForceRebuild3(False)
print("TOP equations:", [T(top.GetEquationMgr(), "IEquationMgr").Equation(i)
                         for i in range(T(top.GetEquationMgr(), "IEquationMgr").GetCount())], flush=True)
check("A2 TOP equation drives a plain part dimension", i_l >= 0 and dim_value(rc) == 2000.0,
      f"Add2 -> {i_l}; ROD_C length {dim_value(rc)} (want 2000)")
check("B  TOP equation drives a part GLOBAL (expected: rejected)", i_b < 0,
      f"Add2 -> {i_b}; ROD_B length {dim_value(rb)} (want 2000)")
sa1 = next(T(x, "IComponent2") for x in T(top, "IAssemblyDoc").GetComponents(False)
           if T(x, "IComponent2").Name2.endswith("ROD_A-1"))
check("C  TOP drives SUB mate dimension -> SUB global -> part", i_c2 >= 0 and dim_value(sa1) == 3900.0,
      f"global Add2 {i_c} (rejected expected), mate dim Add2 {i_c2}; ROD_A in SUB {dim_value(sa1)} (want 3900)")
dia = dim_value(rc, "D1@SK_ROD")
check("E  atn units", i_e >= 0 and dia is not None, f"Add2 -> {i_e}; diameter {dia} "
      f"(20*atn(1): {20 * 45:.3f} if degrees, {20 * math.pi / 4:.3f} if radians)")

eq = T(top.GetEquationMgr(), "IEquationMgr")
for i in range(eq.GetCount()):
    if eq.Equation(i).replace(" ", "").startswith('"SPAN_X"='):
        eq.SetEquation(i, '"SPAN_X" = 5000')
eq.EvaluateAll()
top.EditRebuild3()
top.ForceRebuild3(False)
check("edit SPAN_X 4000 -> 5000 follows", dim_value(rc) == 2500.0 and dim_value(sa1) == 4900.0,
      f"ROD_C {dim_value(rc)} (2500), ROD_A in SUB {dim_value(sa1)} (4900); errors {eq_errors(top)}")

r = top.Save3(1 | 4, 0, 0)          # silent + save referenced documents
check("save top + referenced", bool(r[0] if isinstance(r, tuple) else r), f"Save3 -> {r}")
close_out_docs(sw)
r = sw.OpenDoc6(top_path, C.swDocASSEMBLY, C.swOpenDocOptions_Silent, "", 0, 0)
top = T(r[0], "IModelDoc2")
sw.ActivateDoc3(top.GetTitle(), False, 0, 0)
top.ForceRebuild3(False)
asm = T(top, "IAssemblyDoc")
asm.ResolveAllLightWeightComponents(False)
rc = next(T(x, "IComponent2") for x in asm.GetComponents(True) if "ROD_C" in T(x, "IComponent2").Name2)
sa1 = next(T(x, "IComponent2") for x in asm.GetComponents(False) if T(x, "IComponent2").Name2.endswith("ROD_A-1"))
check("after save + close + reopen", dim_value(rc) == 2500.0 and dim_value(sa1) == 4900.0 and not eq_errors(top),
      f"open {r[1:]}; ROD_C {dim_value(rc)}, ROD_A {dim_value(sa1)}; errors {eq_errors(top)}; "
      f"mates {mate_errors(top)}")
close_out_docs(sw)
shutil.rmtree(OUT, ignore_errors=True)
print(f"SPIKE {'PASS' if all(ok for _, ok, _ in RES) else 'PARTIAL'}: "
      f"{sum(ok for _, ok, _ in RES)}/{len(RES)}")
