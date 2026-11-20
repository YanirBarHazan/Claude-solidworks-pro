"""Live test of scripts/drawings.py.
  python test_drawing.py <part.sldprt> <out folder> [expected values mm ...]
  python test_drawing.py <assembly.sldasm> <out folder>
Prints one line; the PNG is for a human look (overlaps cannot be measured)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "skill", "solidworks-api", "scripts"))
from sw_common import connect  # noqa: E402
from drawings import make_drawing  # noqa: E402

model, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
os.makedirs(out, exist_ok=True)
os.environ.setdefault("SW_BACKUP_DIR", os.path.join(out, "_backup"))
std = "--standard" in sys.argv                                # SolidWorks' own template + ISO A3 sheet format
expect = [float(v) for v in sys.argv[3:] if not v.startswith("--")]
sw = connect()
rep = make_drawing(sw, model, os.path.join(out, os.path.splitext(os.path.basename(model))[0]), expect=expect,
                   exports=("pdf", "png", "dxf"), template="standard" if std else None,
                   sheet_format="iso" if std else None, section="--section" in sys.argv,
                   tolerances={"D1@SK_BORE": (0, 0.05)} if "--section" in sys.argv else None)
print(rep["line"])
if rep.get("bom"):
    for row in rep["bom"]:
        print("   ", row)
