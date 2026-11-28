"""Warm SolidWorks worker for the Claude panel: one long-lived Python process that keeps the SolidWorks COM
connection and the skill's modules loaded, so each command costs milliseconds instead of ~2 s of start-up.
Started by swpanel_taskpane.py; commands come from swx.py over 127.0.0.1 (token in the panel folder).

Commands: contracts/worker_commands.json (ping, card, info, set, fillet, save, snapshot, run). The dispatch below accepts
only those; tests/test_contracts.py keeps this file, swx.py, the MCP server and the tab's prompt in step with it.
"""
import contextlib
import io
import json
import os
import secrets
import socket
import sys
import threading
import time
import traceback

PANEL = os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("SW_OUT", os.path.join(PANEL, "scratch"))
os.environ.setdefault("SW_REQUIRE_REV", "")   # any version unless the user locked one (setup.md)
os.environ["SW_DAYLOG_MODE"] = "worker"   # day log: one line per changing command (serve), not per process
os.environ["SW_FAST"] = "0"   # long-lived: fast mode only around each command (serve), never for the whole session
import pythoncom  # noqa: E402
import contract  # noqa: E402
import daylog  # noqa: E402
import sw_common as c  # noqa: E402
import swcad  # noqa: E402
from sw_common import T  # noqa: E402

MM = 1000.0
SEL = {1: "edge", 2: "face", 3: "vertex", 4: "plane", 5: "axis", 9: "sketch segment", 11: "sketch point",
       20: "component", 22: "feature", 25: "dimension", 31: "sketch"}
DOC_TYPES = {1: "part", 2: "assembly", 3: "drawing"}
# commands that change something go to the day log (read-only ones not); both come from the contract
LOGGED = {n for n, spec in contract.COMMANDS.items() if spec["changes_model"]}


def r3(v, k=MM):
    return [round(x * k, 4) for x in v]


class Worker:
    def __init__(self):
        self.sw = c.connect()

    def target(self, args):
        """--doc PATH: that document (opened hidden when it is not open, never made active); else the active one.
        -> (IModelDoc2, args without --doc PATH)."""
        args = list(args or [])
        if "--doc" not in args:
            return self.active(), args
        i = args.index("--doc")
        path = os.path.abspath(args[i + 1])
        rest = args[:i] + args[i + 2:]
        d = self.sw.GetOpenDocumentByName(path)
        if d is None:
            dtype = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3}.get(os.path.splitext(path)[1].lower())
            if dtype is None:
                raise ValueError(f"--doc: not a SolidWorks file: {path}")
            self.sw.DocumentVisible(False, dtype)
            try:
                r = self.sw.OpenDoc6(path, dtype, 1, "", 0, 0)        # swOpenDocOptions_Silent
            finally:
                self.sw.DocumentVisible(True, dtype)
            d = r[0] if isinstance(r, tuple) else r
            if d is None:
                raise RuntimeError(f"--doc: cannot open {path}: {r[1:] if isinstance(r, tuple) else r}")
        return T(d, "IModelDoc2"), rest

    def active(self):
        d = self.sw.ActiveDoc
        if d is None:
            raise RuntimeError("no active document")
        return T(d, "IModelDoc2")

    # ---------- info ----------
    def selection(self, doc):
        sm = T(doc.SelectionManager, "ISelectionMgr")
        out = []
        for i in range(1, sm.GetSelectedObjectCount2(-1) + 1):
            t = sm.GetSelectedObjectType3(i, -1)
            o = sm.GetSelectedObject6(i, -1)
            it = {"type": SEL.get(t, t)}
            comp = None
            try:
                comp = sm.GetSelectedObjectsComponent4(i, -1)
                if comp is not None:
                    comp = T(comp, "IComponent2")
                    chain, p = [], comp
                    while p is not None:
                        chain.append(p.Name2.split("/")[-1])   # Name2 of a nested component is already a path
                        p = p.GetParent()
                        p = T(p, "IComponent2") if p is not None else None
                    it["component"] = "/".join(reversed(chain))
                    it["component_file"] = comp.GetPathName()
                    md = comp.GetModelDoc2()
                    if md is not None:            # the globals that drive the selected part (for set --selected)
                        it["component_globals"] = {e["eq"].split("=")[0].strip().strip('"'): e["value"]
                                                   for e in self.equations(T(md, "IModelDoc2")) if e["global"]}
                if t == 2:
                    f = T(o, "IFace2")
                    s = T(f.GetSurface(), "ISurface")
                    it["area_mm2"] = round(f.GetArea() * MM * MM, 3)
                    feat = f.GetFeature()
                    if feat is not None:
                        it["feature"] = T(feat, "IFeature").Name
                    if s.IsPlane():
                        pp = s.PlaneParams
                        it.update(surface="plane", normal=r3(pp[0:3], 1), point=r3(pp[3:6]))
                    elif s.IsCylinder():
                        cp = s.CylinderParams
                        it.update(surface="cylinder", origin=r3(cp[0:3]), axis=r3(cp[3:6], 1),
                                  radius=round(cp[6] * MM, 4), diameter=round(2 * cp[6] * MM, 4))
                    else:
                        it["surface"] = "other"
                elif t == 1:
                    e = T(o, "IEdge")
                    cv = T(e.GetCurve(), "ICurve")
                    prm = e.GetCurveParams2()
                    it["length"] = round(cv.GetLength3(prm[6], prm[7]) * MM, 4)
                    it["start"], it["end"] = r3(prm[0:3]), r3(prm[3:6])
                    if cv.IsCircle():
                        cp = cv.CircleParams
                        it.update(curve="circle", center=r3(cp[0:3]), axis=r3(cp[3:6], 1),
                                  radius=round(cp[6] * MM, 4), diameter=round(2 * cp[6] * MM, 4))
                    elif cv.IsLine():
                        it["curve"] = "line"
                elif t == 3:
                    it["point"] = r3(T(o, "IVertex").GetPoint())
                elif t in (22, 4, 5):
                    f = T(o, "IFeature")
                    it.update(name=f.Name, feature_type=f.GetTypeName2())
                elif t == 20:
                    cm = T(o, "IComponent2")
                    it.update(name=cm.Name2, file=cm.GetPathName())
                elif t == 9:
                    sg = T(o, "ISketchSegment")
                    kind = {0: "line", 1: "arc", 2: "ellipse", 3: "spline", 4: "text", 5: "parabola"}
                    it.update(segment=kind.get(sg.GetType(), sg.GetType()), length=round(sg.GetLength() * MM, 4),
                              sketch=T(sg.GetSketch(), "IFeature").Name)
                    if sg.GetType() == 1:
                        it["radius"] = round(T(o, "ISketchArc").GetRadius() * MM, 4)
                if comp is not None:
                    self.to_assembly(it, comp)
            except Exception as ex:     # report what could be read, never fail the whole info
                it["read_error"] = repr(ex)[:120]
            out.append(it)
        return out

    def to_assembly(self, it, comp):
        """Geometry read from a component is in the PART's coordinates; add the same in the open assembly's
        coordinates (component Transform2 = part -> top assembly, also through sub-assemblies)."""
        from win32com.client import VARIANT
        mu = T(self.sw.GetMathUtility(), "IMathUtility")
        xf = T(comp.Transform2, "IMathTransform")

        def arr(v):
            return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [float(x) for x in v])

        def pt(p_mm):
            m = T(mu.CreatePoint(arr([x / MM for x in p_mm])), "IMathPoint")
            return r3(T(m.MultiplyTransform(xf), "IMathPoint").ArrayData)

        def vec(v):
            m = T(mu.CreateVector(arr(v)), "IMathVector")
            return r3(T(m.MultiplyTransform(xf), "IMathVector").ArrayData, 1)
        a = {}
        for k in ("point", "origin", "center", "start", "end"):
            if k in it:
                a[k] = pt(it[k])
        for k in ("normal", "axis"):
            if k in it:
                a[k] = vec(it[k])
        if a:
            it["in_assembly"] = a
            it["frame"] = "part coordinates; in_assembly = top assembly coordinates"

    def equations(self, doc):
        eq = T(doc.GetEquationMgr(), "IEquationMgr")
        return [{"eq": eq.Equation(i), "value": round(eq.Value(i), 6), "global": bool(eq.GlobalVariable(i))}
                for i in range(eq.GetCount())]

    def features(self, doc, limit=80):
        out, f = [], doc.FirstFeature()
        skip = {"HistoryFolder", "SensorFolder", "DocsFolder", "DetailCabinet", "SurfaceBodyFolder",
                "SolidBodyFolder", "InkMarkupFolder", "EnvFolder", "CommentsFolder", "MaterialFolder",
                "OriginProfileFeature", "SelectionSetFolder", "FavoriteFolder", "BlockFolder", "EqnFolder"}
        while f is not None and len(out) < limit:
            f = T(f, "IFeature")
            tn = f.GetTypeName2()
            if tn not in skip:
                code, _warn = f.GetErrorCode2()
                row = {"name": f.Name, "type": tn}
                if code:
                    row["error"] = code
                if f.IsSuppressed():
                    row["suppressed"] = True
                out.append(row)
            f = f.GetNextFeature()
        return out

    def size(self, doc):
        if doc.GetType() != 1:
            return None
        bodies = T(doc, "IPartDoc").GetBodies2(0, True) or ()
        if not bodies:
            return {"bodies": 0}
        boxes = [T(b, "IBody2").GetBodyBox() for b in bodies]
        lo = [min(b[i] for b in boxes) for i in range(3)]
        hi = [max(b[i + 3] for b in boxes) for i in range(3)]
        vol = sum(T(b, "IBody2").GetMassProperties(1000)[3] for b in bodies)
        return {"bodies": len(bodies), "bbox_mm": r3([h - l for l, h in zip(lo, hi)]),
                "volume_mm3": round(vol * 1e9, 3)}

    def info(self, args):
        """info [--full]: document + selection with geometry + size; --full adds equations and the feature list
        (the model itself is summarised by `card`)."""
        doc, args = self.target(args)
        r = {"doc": doc.GetTitle(), "path": doc.GetPathName(), "kind": DOC_TYPES.get(doc.GetType()),
             "unsaved_changes": bool(doc.GetSaveFlag()),
             "config": doc.ConfigurationManager.ActiveConfiguration.Name,
             "selection": self.selection(doc), "size": self.size(doc)}
        if "--full" in (args or []):
            r.update(equations=self.equations(doc), features=self.features(doc))
        return r

    # ---------- card: compact model summary + changes since the last card of the same file ----------
    AUTO = ("Sketch", "Plane", "Axis", "Point", "Boss-Extrude", "Cut-Extrude", "Fillet", "Chamfer", "Coincident",
            "Distance", "Concentric", "Parallel", "Perpendicular", "LocalLPattern", "Mirror")
    PATTERN_TYPES = {"LocalLPattern", "LocalCirPattern", "LPattern", "CirPattern", "MirrorPattern",
                     "MirrorCompFeat", "DerivedLPattern", "TablePattern", "SketchPattern"}

    def state(self, doc):
        """Everything the card shows, as plain data (also what the next card is compared against)."""
        st = {"kind": DOC_TYPES.get(doc.GetType()), "globals": {}, "eqs": [], "feats": [], "patterns": [],
              "configs": list(doc.GetConfigurationNames() or ()), "comps": {}, "suppressed": 0, "mates": 0,
              "mate_errors": 0, "errors": []}
        for e in self.equations(doc):
            name = e["eq"].split("=")[0].strip().strip('"')
            if e["global"]:
                st["globals"][name] = e["value"]
            else:
                st["eqs"].append(e["eq"].replace(" ", ""))
        f = doc.FirstFeature()
        while f is not None:
            f = T(f, "IFeature")
            tn, nm = f.GetTypeName2(), f.Name
            if tn == "MateGroup":
                s = f.GetFirstSubFeature()
                while s is not None:
                    s = T(s, "IFeature")
                    st["mates"] += 1
                    if s.GetErrorCode2()[0]:
                        st["mate_errors"] += 1
                    s = s.GetNextSubFeature()
            elif tn in self.PATTERN_TYPES:
                st["patterns"].append(nm)
            code = f.GetErrorCode2()[0]
            if code and not (nm == "Equations" and code == 51):
                st["errors"].append(f"{nm}:{code}")
            if tn not in ("HistoryFolder", "SensorFolder", "DocsFolder", "DetailCabinet", "SurfaceBodyFolder",
                          "SolidBodyFolder", "InkMarkupFolder", "EnvFolder", "CommentsFolder", "MaterialFolder",
                          "OriginProfileFeature", "SelectionSetFolder", "FavoriteFolder", "BlockFolder", "EqnFolder",
                          "MateGroup", "Reference", "RefPlane" if nm in ("Front Plane", "Top Plane", "Right Plane")
                          else "-"):
                st["feats"].append(f"{nm}({tn})" + ("[s]" if f.IsSuppressed() else ""))
            f = f.GetNextFeature()
        if doc.GetType() == 2:
            for cm in T(doc, "IAssemblyDoc").GetComponents(True) or ():
                cm = T(cm, "IComponent2")
                k = os.path.basename(cm.GetPathName())
                st["comps"][k] = st["comps"].get(k, 0) + 1
                if cm.GetSuppression2() == 0:     # swComponentSuppressed; IsSuppressed() lies after a silent open (note 27)
                    st["suppressed"] += 1
            st["feats"] = [x for x in st["feats"] if "(Reference)" not in x]
        sz = self.size(doc)
        if sz:
            st["size"] = sz
        else:
            b = T(doc, "IAssemblyDoc").GetBox(0) if doc.GetType() == 2 else None
            if b:
                st["size"] = {"bbox_mm": r3([b[3] - b[0], b[4] - b[1], b[5] - b[2]])}
        return st

    @staticmethod
    def delta(old, new):
        out = []
        for k in sorted(set(old["globals"]) | set(new["globals"])):
            a, b = old["globals"].get(k), new["globals"].get(k)
            if a != b:
                out.append(f"{k} {a} -> {b}" if a is not None and b is not None else f"{'+' if b is not None else '-'}{k}")
        fo, fn = set(old["feats"]), set(new["feats"])
        out += [f"+{x}" for x in sorted(fn - fo)[:15]] + [f"-{x}" for x in sorted(fo - fn)[:15]]
        eo, en = set(old["eqs"]), set(new["eqs"])
        out += [f"+eq {x}" for x in sorted(en - eo)[:10]] + [f"-eq {x}" for x in sorted(eo - en)[:10]]
        for k in sorted(set(old["comps"]) | set(new["comps"])):
            a, b = old["comps"].get(k, 0), new["comps"].get(k, 0)
            if a != b:
                out.append(f"{k} x{a} -> x{b}")
        if old["configs"] != new["configs"]:
            out.append(f"configs {old['configs']} -> {new['configs']}")
        for k in ("mates", "mate_errors", "suppressed"):
            if old.get(k) != new.get(k):
                out.append(f"{k} {old.get(k)} -> {new.get(k)}")
        if old.get("size") != new.get("size"):
            out.append(f"size {old.get('size')} -> {new.get('size')}")
        return out

    def card(self, args):
        """card [--full]: compact model summary; after the first time also what changed since the last card."""
        import hashlib
        doc, args = self.target(args)
        path = doc.GetPathName() or doc.GetTitle()
        cdir = os.path.join(os.path.dirname(PANEL), "cards")
        os.makedirs(cdir, exist_ok=True)
        cf = os.path.join(cdir, hashlib.sha1(path.lower().encode("utf-8")).hexdigest()[:16] + ".json")
        st = self.state(doc)
        old = None
        if os.path.exists(cf):
            with open(cf, encoding="utf-8") as fh:
                old = json.load(fh)
        lim = 10 ** 6 if "--full" in args else 40
        L = [f"CARD {doc.GetTitle()} ({st['kind']}) config={doc.ConfigurationManager.ActiveConfiguration.Name}"
             f" of {st['configs']} unsaved={'yes' if doc.GetSaveFlag() else 'no'}",
             f"path {path}"]
        if st["globals"]:
            L.append("globals: " + ", ".join(f"{k}={v:g}" for k, v in list(st["globals"].items())[:lim]))
        if st["eqs"]:
            groups = {}                      # right-hand side -> driven dimensions (142 lines -> a few)
            for e in st["eqs"]:
                lhs, _, rhs = e.partition("=")
                groups.setdefault(rhs, []).append(lhs.strip('"'))
            items = sorted(groups.items(), key=lambda kv: -len(kv[1]))
            L.append(f"driven dimensions ({len(st['eqs'])}): " + "; ".join(
                f"{rhs} -> {len(ls)}x ({', '.join(ls[:3])}{', ...' if len(ls) > 3 else ''})"
                for rhs, ls in items[:min(lim, 12)]) + (f"; +{len(items) - 12} more" if len(items) > 12 and lim == 40 else ""))
        if st["comps"]:
            top = sorted(st["comps"].items(), key=lambda kv: -kv[1])
            L.append(f"top-level components {sum(st['comps'].values())} (suppressed {st['suppressed']}): "
                     + ", ".join(f"{k} x{v}" for k, v in top[:min(lim, 20)])
                     + (f" +{len(top) - 20} files" if len(top) > 20 and lim == 40 else ""))
            L.append(f"mates {st['mates']} (errors {st['mate_errors']}); patterns: {', '.join(st['patterns']) or '-'}")
        named = [x for x in st["feats"] if not x.split("(")[0].rstrip("0123456789").startswith(self.AUTO)
                 or "[s]" in x]
        auto = len(st["feats"]) - len(named)
        L.append(f"features {len(st['feats'])} ({auto} auto-named): " + " ".join(named[:lim])
                 + (f" +{len(named) - lim} more (--full)" if len(named) > lim else ""))
        if st.get("size"):
            L.append("size " + ", ".join(f"{k} {v}" for k, v in st["size"].items()))
        if st["errors"]:
            L.append("REBUILD ERRORS: " + ", ".join(st["errors"][:20]))
        if old is None:
            L.append("first card of this file")
        else:
            d = self.delta(old["state"], st)
            L.append(f"changes since {old['time']}: " + ("; ".join(d) if d else "none"))
        with open(cf + ".tmp", "w", encoding="utf-8") as fh:
            json.dump({"path": path, "time": time.strftime("%Y-%m-%d %H:%M"), "state": st}, fh, ensure_ascii=False)
        os.replace(cf + ".tmp", cf)
        print("\n".join(L))
        return None

    # ---------- set ----------
    def errors(self, doc):
        bad, f = [], doc.FirstFeature()
        while f is not None:
            f = T(f, "IFeature")
            code, _w = f.GetErrorCode2()
            if code and not (f.Name == "Equations" and code == 51):
                bad.append([f.Name, code])
            f = f.GetNextFeature()
        return bad

    def set(self, args):
        top, args = self.target(args)
        target = top
        if "--selected" in args:
            args = [a for a in args if a != "--selected"]
            sm = T(top.SelectionManager, "ISelectionMgr")
            comp = sm.GetSelectedObjectsComponent4(1, -1) if sm.GetSelectedObjectCount2(-1) else None
            if comp is None:
                raise RuntimeError("--selected: nothing selected inside a component")
            target = T(T(comp, "IComponent2").GetModelDoc2(), "IModelDoc2")
        if target is not top:
            # 2019: an equation change inside a component is silently ignored unless its document is active
            # (asmtools.edit_component_equation); the top document is re-activated in the finally below
            self.sw.ActivateDoc3(target.GetTitle(), False, 0, 0)
        hidden = not target.Visible     # a background agent's part (--doc): its equation manager ignores changes
        user = c.active_title(self.sw) if hidden else None      # while hidden, so show it for the moment
        if hidden:
            target.Visible = True
        try:
            return self._set(top, target, args)
        finally:
            if hidden:
                c.hide_for_background(self.sw, target, user)
            if target is not top:
                self.sw.ActivateDoc3(top.GetTitle(), False, 0, 0)
                top.ForceRebuild3(False)

    def _set(self, top, target, args):
        eq = T(target.GetEquationMgr(), "IEquationMgr")
        names = {}
        for i in range(eq.GetCount()):
            if eq.GlobalVariable(i):
                names[eq.Equation(i).split("=")[0].strip().strip('"')] = i
        before = self.size(target)
        changed = []
        for a in args:
            name, _, val = a.partition("=")
            name, val = name.strip(), val.strip()
            if name not in names:
                raise KeyError(f"{name} is not a global variable of {target.GetTitle()}; globals: {sorted(names)}")
            i = names[name]
            old = eq.Value(i)
            eq.SetEquation(i, f'"{name}" = {val}')
            changed.append([name, round(old, 6), val])
        eq.EvaluateAll()
        if target is not top:
            target.EditRebuild3()
        else:
            target.ForceRebuild3(False)
        for row in changed:
            row.append(round(eq.Value(names[row[0]]), 6))
        return {"doc": target.GetTitle(), "changed": [{"name": n, "old": o, "expr": e, "new": v}
                                                      for n, o, e, v in changed],
                "rebuild_errors": self.errors(target), "size_before": before, "size_after": self.size(target),
                "top_errors": self.errors(top) if target is not top else None, "saved": False}

    # ---------- fillet ----------
    def link_new_global(self, doc, feat, var, value):
        """Drive the feature's first dimension by a new global variable (as the skill does for its own parts)."""
        eq = T(doc.GetEquationMgr(), "IEquationMgr")
        d = feat.GetFirstDisplayDimension()
        dim = T(T(d, "IDisplayDimension").GetDimension2(0), "IDimension")
        dname = "@".join(dim.FullName.split("@")[:2])
        if eq.Add2(-1, f'"{var}"= {value}', False) < 0 or eq.Add2(-1, f'"{dname}" = "{var}"', False) < 0:
            raise RuntimeError(f"could not add equations for {var} / {dname}")
        eq.EvaluateAll()
        return dname

    def fillet(self, args):
        """fillet R [--edges selected|x|y|z] [--name NAME] [--var VAR]
        x|y|z: every straight edge of the part parallel to that axis (e.g. the vertical corners of a plate)."""
        r = float(args[0])
        opt = dict(zip(args[1::2], args[2::2]))
        spec = opt.get("--edges", "selected").lower()
        doc = self.active()
        if doc.GetType() != 1:
            raise RuntimeError("fillet: active document must be a part")
        n = 0
        if spec == "selected":
            sm = T(doc.SelectionManager, "ISelectionMgr")
            n = sum(1 for i in range(1, sm.GetSelectedObjectCount2(-1) + 1) if sm.GetSelectedObjectType3(i, -1) == 1)
            if n == 0:
                raise RuntimeError("fillet --edges selected: no edges selected")
        else:
            k = "xyz".index(spec)
            doc.ClearSelection2(True)
            for b in T(doc, "IPartDoc").GetBodies2(0, True) or ():
                for e in T(b, "IBody2").GetEdges() or ():
                    e = T(e, "IEdge")
                    if not T(e.GetCurve(), "ICurve").IsLine():
                        continue
                    ps = T(e.GetStartVertex(), "IVertex").GetPoint()
                    pe = T(e.GetEndVertex(), "IVertex").GetPoint()
                    d = [pe[i] - ps[i] for i in range(3)]
                    ln = sum(x * x for x in d) ** 0.5
                    if ln > 1e-9 and abs(abs(d[k]) / ln - 1) < 1e-6:
                        T(e, "IEntity").Select4(True, None)
                        n += 1
            if n == 0:
                raise RuntimeError(f"fillet: no straight edges parallel to {spec}")
        before = self.size(doc)
        f = doc.FeatureManager.FeatureFillet3(2, r / MM, 0, 0, 0, 0, 0, None, None, None, None, None, None, None)
        if f is None:
            raise RuntimeError(f"FeatureFillet3 failed on {n} edges (radius too large?)")
        f = T(f, "IFeature")
        existing = {x["name"] for x in self.features(doc, 500)}
        name = opt.get("--name") or next(f"FILLET{i}" for i in range(1, 999) if f"FILLET{i}" not in existing)
        f.Name = name
        var = opt.get("--var") or f"{name}_R"
        dname = self.link_new_global(doc, f, var, r)
        doc.ClearSelection2(True)
        doc.ForceRebuild3(False)
        return {"feature": f.Name, "edges": n, "radius_mm": r, "global": var, "dimension": dname,
                "rebuild_errors": self.errors(doc), "size_before": before, "size_after": self.size(doc),
                "saved": False}

    def save(self, args):
        doc, _ = self.target(args)
        if not doc.GetPathName():
            raise RuntimeError("document was never saved: use a script with save_as into the save folder")
        r = doc.Save3(1, 0, 0)      # swSaveAsOptions_Silent
        ok = r[0] if isinstance(r, tuple) else r
        return {"doc": doc.GetTitle(), "saved": bool(ok), "path": doc.GetPathName(), "result": str(r)}

    def snapshot(self, args):
        """snapshot [--doc PATH] [--out PNG] [--view iso|front|top|right]: a PNG of the document. SolidWorks saves
        pictures of the active document only, so the document is shown for a moment and the user's comes back."""
        doc, rest = self.target(args)
        opt = dict(zip(rest[0::2], rest[1::2]))
        src = doc.GetPathName() or os.path.join(PANEL, "scratch", doc.GetTitle())
        out = os.path.abspath(opt.get("--out") or os.path.splitext(src)[0] + ".png")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        view = {"iso": "*Isometric", "front": "*Front", "top": "*Top", "right": "*Right"}[opt.get("--view", "iso")]
        before = self.sw.ActiveDoc
        before_title = T(before, "IModelDoc2").GetTitle() if before is not None else None
        try:
            self.sw.ActivateDoc3(doc.GetTitle(), False, 0, 0)
            doc.ShowNamedView2(view, -1)
            doc.ViewZoomtofit2()
            r = doc.Extension.SaveAs(out, 0, 1, None, 0, 0)
            ok = r[0] if isinstance(r, tuple) else r
            if not ok or not os.path.exists(out):
                raise RuntimeError(f"PNG not written: {r}")
        finally:
            if before_title and before_title != doc.GetTitle():
                self.sw.ActivateDoc3(before_title, False, 0, 0)
        return {"doc": doc.GetTitle(), "png": out}

    def run(self, args):
        background = "--background" in args
        args = [a for a in args if a != "--background"]
        path = args[0]
        ns = {"__name__": "__main__", "__file__": path, "sw": self.sw, "c": c, "swcad": swcad,
              "PartBuilder": swcad.PartBuilder, "T": T}
        try:
            ns["doc"] = self.active()
        except RuntimeError:
            ns["doc"] = None
        with open(path, encoding="utf-8") as f:
            code = compile(f.read(), path, "exec")
        old_bg = c.BACKGROUND
        c.BACKGROUND = background
        try:
            exec(code, ns)
        except SystemExit as e:
            if e.code not in (None, 0):
                raise RuntimeError(f"script exit {e.code}")
        finally:
            c.BACKGROUND = old_bg
        return None


def serve():
    os.makedirs(PANEL, exist_ok=True)
    pythoncom.CoInitialize()
    w = Worker()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(64)       # background agents queue here while one command runs (swx.connect retries too)
    token = secrets.token_hex(16)
    with open(os.path.join(PANEL, "worker.json.tmp"), "w") as f:
        json.dump({"port": srv.getsockname()[1], "token": token, "pid": os.getpid()}, f)
    os.replace(os.path.join(PANEL, "worker.json.tmp"), os.path.join(PANEL, "worker.json"))
    lock = threading.Lock()
    while True:
        conn, _ = srv.accept()
        with conn, lock:            # one command at a time; COM stays on this thread
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            t0 = time.time()
            buf = io.StringIO()
            try:
                req = json.loads(data.decode("utf-8"))
                if req.get("token") != token:
                    raise PermissionError("bad token")
                cmd, args = req["cmd"], req.get("args", [])
                contract.check(cmd, args)        # only the contract's commands: never an arbitrary method
                if cmd == "ping":
                    res, ok = {"rev": w.sw.RevisionNumber()}, True
                else:
                    # CommandInProgress: out-of-process calls 0.15 ms instead of ~15 ms on 2019 (version note 45);
                    # always reset, or the user's SolidWorks stays in "command" mode
                    w.sw.CommandInProgress = True
                    logged = cmd in LOGGED
                    if logged:
                        daylog.begin(w.sw, T, name=f"swx {cmd}", args=args, once=False)
                    try:
                        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                            res = getattr(w, cmd)(args)
                    except Exception as e:
                        if logged:
                            daylog.end(w.sw, T, ok=False, error=f"{type(e).__name__}: {e}"[:300])
                        raise
                    finally:
                        w.sw.CommandInProgress = False
                    if logged:
                        daylog.end(w.sw, T, ok=True)
                    ok = True
            except Exception:
                res, ok = traceback.format_exc(limit=6)[-2500:], False
            out = {"ok": ok, "result": res, "printed": buf.getvalue()[-6000:], "s": round(time.time() - t0, 3)}
            conn.sendall((json.dumps(out, ensure_ascii=False, default=str) + "\n").encode("utf-8"))


if __name__ == "__main__":
    serve()
