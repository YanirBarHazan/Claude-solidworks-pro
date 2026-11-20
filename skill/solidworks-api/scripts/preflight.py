"""Start-of-work check, sized to what is already known about the running SolidWorks version.

    python preflight.py            QUICK (seconds, no documents created): connect, version, version guard, templates,
                                   open documents. If this SolidWorks major version was never tested - not in the
                                   skill's table and not on this machine - the FULL suite runs automatically.
    python preflight.py --full     force the full suite (e.g. after a SolidWorks service pack)
    python preflight.py --quick    never run the full suite (an untested version is reported, not tested)

FULL suite: every capability the skill relies on, one line each (OK / FAIL / SKIP + seconds), in a temporary folder:
parts (sketch / extrude / cut / equations / edit test / save + reopen), update in place, Hole Wizard + feature pattern
+ mirror, material + mass, fully defined sketches, skeleton assembly with mates and equation-driven patterns, a
component equation edited from the assembly, drawings with model dimensions + BOM (when drawings.py is present),
audit, file safety, parameter file. The report goes to ~/.solidworks-api/version_<year>.md and .json on THIS machine.
Nothing is uploaded: to add the version to the skill's "tested on" table, the user sends that report (issue / PR).
A FAIL is the start of a version note (`references/version_notes.md`), not a reason to stop all work: say which
capability is unavailable on this version and continue with the rest."""
import collections
import datetime
import glob
import json
import math
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SUITE = "2.1"                                          # bump when the suite gains a capability
# major revision -> what the skill was tested on (major + 1992 = year: 27 = 2019, 33 = 2025)
TESTED = {27: "SolidWorks 2019 SP3: field project (770 components) + full suite 2.1, 2026-11"}
LOCAL = os.path.join(os.path.expanduser("~"), ".solidworks-api")
MM = 1e-3


def year_of(major):
    return major + 1992


def local_record(major):
    try:
        return json.load(open(os.path.join(LOCAL, f"version_{year_of(major)}.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def open_titles(sw, T):
    out, d = set(), sw.GetFirstDocument()
    while d is not None:
        d = T(d, "IModelDoc2")                              # late-bound: GetNext exists only on the typed object
        out.add(d.GetTitle())
        d = d.GetNext()
    return out


def quick(sw, C):
    from sw_common import default_template
    t0 = time.time()
    rev = sw.RevisionNumber()
    major = int(rev.split(".")[0])
    tpl = {}
    for kind in ("part", "asm"):
        try:
            tpl[kind] = os.path.exists(default_template(sw, kind))
        except Exception:
            tpl[kind] = False
    drw = sw.GetUserPreferenceStringValue(getattr(C, "swDefaultTemplateDrawing", 10)) or ""
    tpl["drw"] = os.path.exists(drw)
    from sw_common import T
    n = len(open_titles(sw, T))
    rec = local_record(major)
    known = major in TESTED or bool(rec and rec.get("suite") == SUITE and rec.get("failed") == 0)
    need = os.environ.get("SW_REQUIRE_REV", "")
    return dict(revision=rev, major=major, year=year_of(major), templates=tpl, open_docs=n, known=known,
                tested=TESTED.get(major) or (f"this machine, suite {rec['suite']} {rec['date']}" if rec else None),
                guard=need or "off", seconds=round(time.time() - t0, 1))


class Suite:
    def __init__(self, sw=None, keep=()):
        self.rows, self.sw, self.keep = [], sw, set(keep)

    def cleanup(self):
        """After a FAIL: close every document the suite left open (never the ones open before it started)."""
        from sw_common import T
        for t in open_titles(self.sw, T) - self.keep:
            self.sw.CloseDoc(t)

    def run(self, name, fn):
        t = time.time()
        try:
            r = fn()
            status, note = ("SKIP", r[5:]) if isinstance(r, str) and r.startswith("SKIP:") else ("OK", r or "")
        except Exception as ex:
            status, note = "FAIL", f"{type(ex).__name__}: {str(ex)[:160]}"
            traceback.print_exc(file=open(os.path.join(OUT, "preflight_trace.log"), "a", encoding="utf-8"))
            if self.sw is not None:
                self.cleanup()
        self.rows.append(dict(item=name, status=status, seconds=round(time.time() - t, 1), note=str(note)[:200]))
        print(f"  {status:4} {name:42} {self.rows[-1]['seconds']:6.1f} s  {note}", flush=True)


OUT = tempfile.mkdtemp(prefix="sw_preflight_")


def full(sw, C, info):
    os.environ["SW_OUT"] = OUT
    os.environ.setdefault("SW_BACKUP_DIR", os.path.join(OUT, "_backup"))
    import runpy
    from sw_common import close_out_docs, new_doc, save_as, T
    from swcad import PartBuilder
    S = Suite(sw, open_titles(sw, T))
    st = {}

    def runpy_main(script):
        old = sys.argv
        sys.argv = [script]
        try:
            runpy.run_path(os.path.join(HERE, script), run_name="__main__")
        except SystemExit as ex:
            if ex.code not in (0, None):
                raise RuntimeError(f"{script} exited {ex.code}")
        finally:
            sys.argv = old
        close_out_docs(sw)

    # ---- library self tests that need no SolidWorks
    def no_sw():
        import filesafe
        import paramfile
        filesafe.self_test()
        paramfile.self_test()
        return "filesafe + paramfile"
    S.run("file safety + parameter file", no_sw)
    S.run("v1 smoke test (part, edit, reopen, interference, STL)", lambda: runpy_main("smoke_test.py") or "SMOKE TEST OK")
    S.run("update in place + hand-edit protection (sync_test)", lambda: runpy_main("sync_test.py") or "SYNC TEST OK")

    # ---- v2 part features on one plate
    P = dict(W=120.0, T=12.0, R=14.0, BOLT_D=9.0, ROW_Y=44.0, N_ROW=3.0, PITCH=36.0)

    def vol(p):
        return (p["W"] ** 2 - (4 - math.pi) * p["R"] ** 2) * p["T"] - 2 * round(p["N_ROW"]) * math.pi * \
            (p["BOLT_D"] / 2) ** 2 * p["T"]

    def expect(p):
        return (p["W"], p["W"], p["T"]), vol(p)

    def plate():
        pb = PartBuilder(sw, P)
        st["pb"] = pb
        with pb.sketch("Front Plane", "SK_PLATE") as s:
            s.rrect(0, 0, "W", "W", "R")
        pb.extrude("SK_PLATE", "T", "PLATE")
        with pb.sketch("Front Plane", "SK_HOLE_POS") as s:
            s.point("PITCH*(N_ROW-1)/2", "ROW_Y")
        return "rounded plate + position sketch"
    S.run("part: rounded sketch, extrude, sketch point", plate)

    def need(key):
        if key not in st:
            raise RuntimeError(f"skipped: depends on a failed step ({key})")
        return st[key]

    S.run("Hole Wizard hole tied to a driven point",
          lambda: need("pb").hole_wizard("HOLE_M8", "SK_HOLE_POS", ("PITCH*(N_ROW-1)/2", "ROW_Y", "T"), "M8",
                                         "BOLT_D", kind="clearance") and "ISO M8 clearance, d 9")
    S.run("feature linear pattern, linked count",
          lambda: need("pb").pattern_linear("PAT_ROW", ["HOLE_M8"], "Right Plane", "N_ROW", "PITCH", flip=True)
          and "3 holes, count = N_ROW")
    S.run("mirror feature", lambda: need("pb").mirror("MIR_ROW", ["HOLE_M8", "PAT_ROW"], "Top Plane") and "2 rows")

    def mat():
        pb = need("pb")
        pb.material("Plain Carbon Steel")
        m, want = pb.check_mass(7800.0)
        return f"mass {m:.4f} kg = volume x 7800"
    S.run("material + mass check", mat)

    def verify():
        pb = need("pb")
        res = pb.verify(expect, edit=("N_ROW", 2.0))
        path = os.path.join(OUT, "PF_PLATE.sldprt")
        pb.save(path)
        st["plate"] = path
        return f"volume {res['volume']:.1f}, edit N_ROW 3->2, 0 open sketches, saved + reopened"
    S.run("verify: volume, edit test, sketch gate, reopen", verify)

    # ---- skeleton assembly
    G = dict(SPAN_X=4200.0, SPAN_Z=3100.0, N_X=3, N_Z=2, H=2500.0)

    def skeleton():
        import pythoncom
        from win32com.client import VARIANT
        from asmtools import (_mate, mate_errors, linear_pattern, set_equation, drive_pattern, edit_component_equation,
                              fix_only)
        close_out_docs(sw)
        files = {}
        pb = PartBuilder(sw, {"H": G["H"], "SPAN_X": G["SPAN_X"], "SPAN_Z": G["SPAN_Z"]})
        pb.plane("PL_TOP", "H", base="Top Plane")
        pb.plane("PL_X1", "SPAN_X", base="Right Plane")
        pb.plane("PL_Z1", "SPAN_Z", base="Front Plane")
        files["SKEL"] = pb.save(os.path.join(OUT, "SKEL.sldprt"))
        sw.CloseDoc(pb.doc.GetTitle())
        pb = PartBuilder(sw, {"H": G["H"], "D": 80.0})
        with pb.sketch("Front Plane", "SK_POST") as s:
            s.circle(0, 0, "D")
        pb.extrude("SK_POST", "H", "POST_BODY")
        files["POST"] = pb.save(os.path.join(OUT, "POST.sldprt"))
        sw.CloseDoc(pb.doc.GetTitle())
        pb = PartBuilder(sw, {"L": G["SPAN_X"], "B": 60.0})
        with pb.sketch("Front Plane", "SK_BEAM") as s:
            s.rect(0, 0, "B", "B")
        pb.extrude("SK_BEAM", "L", "BEAM_BODY")
        files["BEAM"] = pb.save(os.path.join(OUT, "BEAM.sldprt"))
        sw.CloseDoc(pb.doc.GetTitle())
        for f in files.values():
            sw.OpenDoc6(f, C.swDocPART, C.swOpenDocOptions_Silent, "", 0, 0)
        doc = new_doc(sw, "asm")
        asm = T(doc, "IAssemblyDoc")
        sw.ActivateDoc3(doc.GetTitle(), False, 0, 0)
        mu = T(sw.GetMathUtility(), "IMathUtility")

        def add(f, axes, o):
            c = T(asm.AddComponent5(f, 0, "", False, "", 0, 0, 0), "IComponent2")
            xf = [v for a in axes for v in a] + [v * MM for v in o] + [1.0, 0.0, 0.0, 0.0]
            c.Transform2 = mu.CreateTransform(VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, xf))
            return c
        skel = add(files["SKEL"], ((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0, 0, 0))
        fix_only(doc, skel)
        post = add(files["POST"], ((1, 0, 0), (0, 0, -1), (0, 1, 0)), (0, 0, 0))
        beam = add(files["BEAM"], ((0, 1, 0), (0, 0, 1), (1, 0, 0)), (0, G["H"], 0))
        path = os.path.join(OUT, "PF_GRID.sldasm")
        save_as(doc, path)
        A, sk, po, be = "PF_GRID", skel.Name2, post.Name2, beam.Name2
        coinc, closest = C.swMateCOINCIDENT, C.swMateAlignCLOSEST
        for a, b in ((f"Front Plane@{po}@{A}", f"Top Plane@{sk}@{A}"), (f"Right Plane@{po}@{A}", f"Right Plane@{sk}@{A}"),
                     (f"Top Plane@{po}@{A}", f"Front Plane@{sk}@{A}"), (f"Front Plane@{be}@{A}", f"Right Plane@{sk}@{A}"),
                     (f"Top Plane@{be}@{A}", f"Front Plane@{sk}@{A}"), (f"Right Plane@{be}@{A}", f"PL_TOP@{sk}@{A}")):
            _mate(doc, coinc, closest, [(a, "PLANE"), (b, "PLANE")])

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
        sx, sz, nx, nz, h = G["SPAN_X"], G["SPAN_Z"], G["N_X"], G["N_Z"], G["H"]
        pp = linear_pattern(doc, [post], ax, nx + 1, sx, az, nz + 1, sz, flip1=True, flip2=False, name="PAT_POSTS")
        pm = linear_pattern(doc, [beam], ax, nx, sx, az, nz + 1, sz, flip1=True, flip2=False, name="PAT_BEAMS")
        for k in ("SPAN_X", "SPAN_Z", "N_X", "N_Z"):
            set_equation(doc, k, f"{G[k]:g}")
        drive_pattern(doc, pp, n1='"N_X" + 1', s1='"SPAN_X"', n2='"N_Z" + 1', s2='"SPAN_Z"')
        drive_pattern(doc, pm, n1='"N_X"', s1='"SPAN_X"', n2='"N_Z" + 1', s2='"SPAN_Z"')
        doc.ForceRebuild3(False)

        def check(tag, sx, sz, nx, nz, h):
            have = collections.Counter()
            for c in asm.GetComponents(True) or ():
                c = T(c, "IComponent2")
                d = list(T(c.Transform2, "IMathTransform").ArrayData)
                have[(os.path.splitext(os.path.basename(c.GetPathName()))[0],)
                     + tuple(round(v / MM, 1) for v in d[9:12])] += 1
            want = collections.Counter({("SKEL", 0.0, 0.0, 0.0): 1})
            for i in range(nx + 1):
                for j in range(nz + 1):
                    want[("POST", round(i * sx, 1), 0.0, round(j * sz, 1))] += 1
            for i in range(nx):
                for j in range(nz + 1):
                    want[("BEAM", round(i * sx, 1), round(h, 1), round(j * sz, 1))] += 1
            if have != want:
                raise AssertionError(f"{tag}: missing {sum((want - have).values())}, extra {sum((have - want).values())}")
            return sum(have.values())
        n0 = check("built", sx, sz, nx, nz, h)
        if mate_errors(doc):
            raise AssertionError(f"mate errors {mate_errors(doc)}")
        set_equation(doc, "SPAN_X", "5000")
        doc.ForceRebuild3(False)
        check("SPAN_X in the assembly equations", 5000, sz, nx, nz, h)
        set_equation(doc, "N_X", "5")
        doc.ForceRebuild3(False)
        n1 = check("N_X in the assembly equations", 5000, sz, 5, nz, h)
        edit_component_equation(sw, doc, skel, "H", "3000")
        check("H in the skeleton part", 5000, sz, 5, nz, 3000)
        save_as(doc, path)
        st["asm"] = path
        sw.CloseDoc(doc.GetTitle())
        close_out_docs(sw)
        return f"skeleton fixed only, 6 mates; span / count / skeleton height edits followed ({n0} -> {n1} components)"
    S.run("skeleton assembly, mates, equation-driven patterns", skeleton)

    # ---- drawings (only when the module is part of this skill version)
    def drawings_part():
        if not os.path.exists(os.path.join(HERE, "drawings.py")):
            return "SKIP: drawings.py not in this skill version"
        from drawings import make_drawing
        rep = make_drawing(sw, need("plate"), os.path.join(OUT, "PF_PLATE"), expect=[120, 14, 12, 36, 44, 9],
                           exports=("pdf",))
        if not rep["ok"]:
            raise AssertionError(rep["line"])
        return f"{rep['dims']} model dimensions, scale {rep['scale']}, PDF"
    S.run("drawing of a part (model dimensions, PDF)", drawings_part)

    def drawings_asm():
        if not os.path.exists(os.path.join(HERE, "drawings.py")):
            return "SKIP: drawings.py not in this skill version"
        from drawings import make_drawing
        rep = make_drawing(sw, need("asm"), os.path.join(OUT, "PF_GRID"), exports=("pdf",))
        if not rep["ok"] or not rep["bom_ok"]:
            raise AssertionError(rep["line"])
        return f"BOM = assembly counts, {rep['balloons']} balloons"
    S.run("drawing of an assembly (BOM, balloons)", drawings_asm)

    def audit():
        import audit as A
        r = A.audit(sw, need("plate"), ["PartNo"])
        if r.get("score") is None:
            raise AssertionError(r.get("line"))
        return f"score {r['score']}/100"
    S.run("audit of an existing part (read-only)", audit)
    S.cleanup()                                          # leave SolidWorks as it was found
    return S.rows


def write_report(info, rows):
    os.makedirs(LOCAL, exist_ok=True)
    failed = sum(r["status"] == "FAIL" for r in rows)
    rec = dict(suite=SUITE, date=datetime.date.today().isoformat(), revision=info["revision"], year=info["year"],
               failed=failed, rows=rows)
    base = os.path.join(LOCAL, f"version_{info['year']}")
    json.dump(rec, open(base + ".json", "w", encoding="utf-8"), indent=1)
    lines = [f"# SolidWorks {info['year']} ({info['revision']}) - solidworks-api suite {SUITE}, {rec['date']}", "",
             "| Capability | Result | Seconds | Note |", "|---|---|---|---|"]
    lines += [f"| {r['item']} | {r['status']} | {r['seconds']} | {r['note'].replace('|', '/')} |" for r in rows]
    lines += ["", "Generated by scripts/preflight.py. Contains no file names or paths of the user's projects.",
              "To add this version to the skill's tested table: open an issue / pull request with this file."]
    open(base + ".md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return base + ".md", failed


def main():
    from sw_common import connect, swconst
    C = swconst.constants
    t0 = time.time()
    sw = connect()
    info = quick(sw, C)
    tpl = ", ".join(f"{k} {'ok' if v else 'MISSING'}" for k, v in info["templates"].items())
    print(f"PREFLIGHT SolidWorks {info['year']} ({info['revision']}): tested: {info['tested'] or 'NO'}; templates {tpl}; "
          f"open documents {info['open_docs']}; version guard {info['guard']}; {info['seconds']} s", flush=True)
    if not all(info["templates"].values()):
        print("  note: a missing template stops new documents of that kind - set it in Tools > Options > Default Templates")
    run_full = "--full" in sys.argv or (not info["known"] and "--quick" not in sys.argv)
    if not run_full:
        if not info["known"]:
            print("PREFLIGHT QUICK OK - this version is UNTESTED (run with --full once to test it)")
        else:
            print("PREFLIGHT QUICK OK")
        return 0
    print(f"FULL SUITE {SUITE} ({'forced' if '--full' in sys.argv else 'first use of this version'}), "
          f"working folder {OUT}", flush=True)
    rows = full(sw, C, info)
    path, failed = write_report(info, rows)
    print(f"PREFLIGHT FULL {'OK' if not failed else f'{failed} FAILED'}: {len(rows)} capabilities, "
          f"{time.time() - t0:.0f} s; report {path}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
