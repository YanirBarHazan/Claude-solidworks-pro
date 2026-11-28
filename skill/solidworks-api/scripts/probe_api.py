"""Print the exact signatures of SolidWorks API methods from this machine's type library (early binding),
so a new recipe is written against the real call, not a remembered one. Read-only: opens no document.

    python probe_api.py IFeatureManager FeatureExtrusion3 FeatureCut4 ...
"""
import inspect
import sys

def signatures(iface, names):
    import sw_common as c
    cls = getattr(c.swmod, iface)
    out = {}
    for n in names:
        f = getattr(cls, n, None)
        out[n] = "MISSING in this version" if f is None else str(inspect.signature(f))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    want = {sys.argv[1]: sys.argv[2:]}
    for iface, names in want.items():
        for n, sig in signatures(iface, names).items():
            print(f"{iface}.{n}{sig}")
