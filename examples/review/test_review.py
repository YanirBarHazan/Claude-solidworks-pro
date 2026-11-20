"""Live test: a tiny project at two verification levels -> review log -> review PDF (Hebrew).
quick skips volume + sketches; standard runs them; a drawing adds its checks; the card's assumptions and open
questions appear in the report."""
import math
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "skill", "solidworks-api", "scripts"))
import time  # noqa: E402
PROJ = os.path.join(os.environ.get("TEMP", HERE), "sw_review_demo_" + time.strftime("%H%M%S"))
shutil.rmtree(PROJ, ignore_errors=True)
os.makedirs(os.path.join(PROJ, "cad"))
os.environ["SW_OUT"] = os.path.join(PROJ, "cad")
from sw_common import connect, close_out_docs  # noqa: E402
from swcad import PartBuilder  # noqa: E402
import review  # noqa: E402

open(os.path.join(PROJ, "PROJECT_CARD.md"), "w", encoding="utf-8").write("""# Project card - Demo bracket
## 5. Decisions
| # | Decision | Status | Date | Source |
|---|---|---|---|---|
| 1 | Plate 100 x 60 x 8, steel | CONFIRMED | 18/11 | user |
| 2 | Hole 10 mm clearance for M8 | ASSUMED | 18/11 | default |
## 6. Open questions (each blocks: ...)
| # | Question | Blocks | Recommendation |
|---|---|---|---|
| 1 | Surface finish? | drawing notes | galvanised |
""")


def part(name, lv, edit=None):
    os.environ["SW_VERIFY_LEVEL"] = lv
    P = dict(L=100.0, W=60.0, T=8.0, D=10.0)
    pb = PartBuilder(sw, P)
    with pb.sketch("Front Plane", "SK_PLATE") as s:
        s.rect("L/2", "W/2", "L", "W")
    pb.extrude("SK_PLATE", "T", "PLATE")
    with pb.sketch("Front Plane", "SK_HOLE") as s:
        s.circle("L/2", "W/2", "D")
    pb.cut("SK_HOLE", "T", "HOLE", reverse=False)
    pb.verify(lambda p: ((p["L"], p["W"], p["T"]), p["L"] * p["W"] * p["T"] - math.pi * p["D"] ** 2 / 4 * p["T"]),
              edit=edit)                            # before save(): the edit test needs the open builder
    path = pb.save(os.path.join(PROJ, "cad", name + ".sldprt"))
    sw.CloseDoc(pb.doc.GetTitle())
    return path


sw = connect()
close_out_docs(sw)
part("BRACKET_QUICK", "quick")
p2 = part("BRACKET_STD", "standard", edit=("D", 12.0))
from drawings import make_drawing  # noqa: E402
rep = make_drawing(sw, p2, os.path.join(PROJ, "out", "BRACKET_STD"), expect=[100, 60, 8, 10])
print(rep["line"])
out = review.build(PROJ, "he")
print("review:", out)
