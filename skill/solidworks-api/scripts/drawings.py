"""One call from a model to a checked drawing: standard views + isometric, the MODEL's own dimensions (so the
drawing follows the model), centre marks, for assemblies a bill of materials with balloons, then SLDDRW + PDF / DXF /
PNG. Returns a report and checks what can be checked with numbers:
  - every imported dimension is attached (not dangling) and lies on the sheet
  - every value the caller expects to see is on the drawing (`expect=[120, 12, 64, ...]`, mm)
  - the BOM quantities equal the components counted in the assembly
  - the exported files exist
What numbers cannot see: overlapping text, a crowded view. Export the PNG and LOOK at it once per drawing type.

    from drawings import make_drawing
    rep = make_drawing(sw, r"...\\FLANGE.sldprt", r"...\\out\\FLANGE", expect=[120, 12, 64], exports=("pdf", "png"))
    print(rep["line"])

Tested on SolidWorks 2019 with the default drawing template. `drawtools.Dimensioner` remains for extra dimensions
picked on edges (tolerances, prefixes); `references/drawings.md` for sections, notes and title-block fields."""
import collections
import glob
import os

from sw_common import T, swconst, save_as

C = swconst.constants
MM = 1e-3
PAPER = {"A4": ("swDwgPaperA4size", 0.297, 0.210), "A3": ("swDwgPaperA3size", 0.420, 0.297),
         "A2": ("swDwgPaperA2size", 0.594, 0.420), "A1": ("swDwgPaperA1size", 0.841, 0.594),
         "A0": ("swDwgPaperA0size", 1.189, 0.841)}
SCALES = [(10, 1), (5, 1), (2, 1), (1, 1), (1, 2), (1, 5), (1, 10), (1, 20), (1, 25), (1, 50), (1, 100), (1, 200),
          (1, 500)]


def _const(name, default=0):
    return getattr(C, name, default)


def drawing_template(sw):
    tpl = sw.GetUserPreferenceStringValue(_const("swDefaultTemplateDrawing", 10))
    if tpl and os.path.exists(tpl):
        return tpl
    hits = sorted(glob.glob(os.path.join(r"C:\ProgramData\SOLIDWORKS", "SOLIDWORKS *", "templates", "*.drwdot")))
    if not hits:
        raise RuntimeError("no drawing template found: pass template=")
    return hits[-1]


def standard_template(sw):
    """SolidWorks' own Drawing.drwdot (no company title block)."""
    hits = sorted(glob.glob(os.path.join(r"C:\ProgramData\SOLIDWORKS", "SOLIDWORKS *", "templates", "Drawing.drwdot")))
    cur = os.path.join(os.path.dirname(drawing_template(sw)), "Drawing.drwdot")
    if os.path.exists(cur):
        return cur
    if not hits:
        raise RuntimeError("standard Drawing.drwdot not found: pass template=<path>")
    return hits[-1]


def sheet_format_file(sw, paper, style="iso"):
    """<install>\lang\english\sheetformat\a3 - iso.slddrt (style: iso, din, jis, bsi, gb ...)."""
    name = f"{paper.lower()} - {style}.slddrt"
    for folder in (sw.GetUserPreferenceStringValue(_const("swFileLocationsSheetFormat", 0)) or "").split(";"):
        hit = os.path.join(folder.strip(), name)
        if os.path.exists(hit):
            return hit
    hits = glob.glob(os.path.join(r"C:\Program Files\SOLIDWORKS Corp*", "**", "sheetformat", name), recursive=True)
    if not hits:
        raise RuntimeError(f"sheet format {name!r} not found: pass sheet_format=<path>")
    return hits[0]


def bom_template(sw):
    for folder in (sw.GetUserPreferenceStringValue(_const("swFileLocationsBOMTemplates", 0)) or "").split(";"):
        hit = os.path.join(folder.strip(), "bom-standard.sldbomtbt")
        if os.path.exists(hit):
            return hit
    hits = glob.glob(os.path.join(r"C:\Program Files\SOLIDWORKS Corp*", "**", "lang", "*", "bom-standard.sldbomtbt"),
                     recursive=True)
    return hits[0] if hits else ""


def model_box(model, is_asm):
    """(dx, dy, dz) metres."""
    b = T(model, "IAssemblyDoc").GetBox(0) if is_asm else T(model, "IPartDoc").GetPartBox(True)
    return b[3] - b[0], b[4] - b[1], b[5] - b[2]


def pick_scale(size, w, h, iso, reserve=0.0):
    """Largest standard scale at which the three views with their gaps stay clear of the isometric view (right)
    and of a title block along the bottom (the lowest ~24 % of the sheet height is kept free). reserve: a band
    kept free at the top (the bill of materials of an assembly drawing)."""
    dx, dy, dz = size
    for a, b in SCALES:
        k = a / b
        wide = 0.07 * w + 0.03 + (dx + dz) * k + 0.04
        tall = reserve + 0.05 * h + 0.025 + (dy + dz) * k + 0.04
        if wide <= (0.58 if iso else 0.80) * w and tall <= 0.76 * h:
            return a, b
    return SCALES[-1]


def _pick(doc, annotation):
    """Add an annotation to the selection. IAnnotation.Select3 returns False for drawing dimensions on 2019;
    ISelectionMgr.AddSelectionListObject works (so does SelectByID2 at the annotation's position)."""
    try:
        return bool(T(doc.SelectionManager, "ISelectionMgr").AddSelectionListObject(annotation, None))
    except Exception:
        pos = annotation.GetPosition() or (0, 0, 0)
        return bool(doc.Extension.SelectByID2("", "DIMENSION", pos[0], pos[1], 0, True, 0, None, 0))


def _dedupe(doc, drw):
    """Keep the first display dimension of every model dimension, remove the repeats in other views."""
    seen, n = set(), 0
    for v in views_of(drw):
        drw.ActivateView(v.GetName2())
        for dd in (v.GetDisplayDimensions() or ()):
            dd = T(dd, "IDisplayDimension")
            name = T(dd.GetDimension2(0), "IDimension").FullName
            if name not in seen:
                seen.add(name)
                continue
            ann = T(dd.GetAnnotation(), "IAnnotation")
            doc.ClearSelection2(True)
            if not (_pick(doc, ann) and doc.Extension.DeleteSelection2(0)):
                ann.Visible = _const("swAnnotationHidden", 3)          # could not delete: hidden, not printed
            n += 1
    doc.ClearSelection2(True)
    return n


def _tidy_radial(view):
    """Diameter / radius dimensions come in with long leaders fanned into one corner (one landed off the sheet).
    Put each text just outside the view outline, each on its own direction."""
    import math
    ol = view.GetOutline()                                   # xmin, ymin, xmax, ymax (sheet, m)
    cx, cy = (ol[0] + ol[2]) / 2, (ol[1] + ol[3]) / 2
    kinds = (_const("swDiameterDimension", -1), _const("swRadialDimension", -1))
    rad = []
    for dd in (view.GetDisplayDimensions() or ()):
        dd = T(dd, "IDisplayDimension")
        if dd.Type2 in kinds:
            ann = T(dd.GetAnnotation(), "IAnnotation")
            pos = ann.GetPosition() or (cx + 1, cy + 1, 0)
            rad.append((math.atan2(pos[1] - cy, pos[0] - cx), ann))
    rad.sort(key=lambda r: r[0])
    # fanned out on the LEFT of the view, 22 degrees apart: the auto-arranged linear dimensions take the top and
    # the right, and texts on one ray collide (seen on the first test drawing)
    for i, (_, ann) in enumerate(rad):
        ang = math.pi + (i - (len(rad) - 1) / 2) * math.radians(22)
        ux, uy = math.cos(ang), math.sin(ang)
        tx = (ol[2] - cx) / ux if ux > 1e-9 else (ol[0] - cx) / ux if ux < -1e-9 else 1e9
        ty = (ol[3] - cy) / uy if uy > 1e-9 else (ol[1] - cy) / uy if uy < -1e-9 else 1e9
        t = min(tx, ty) + 0.010
        ann.SetPosition2(cx + ux * t, cy + uy * t, 0)


def views_of(drw):
    out, v = [], T(drw.GetFirstView(), "IView")            # the first "view" is the sheet itself
    v = v.GetNextView()
    while v is not None:
        v = T(v, "IView")
        out.append(v)
        v = v.GetNextView()
    return out


def dims_of(view):
    """[(value mm, dangling, (x, y) sheet metres, full name)] of a view's display dimensions."""
    out = []
    for dd in (view.GetDisplayDimensions() or ()):
        dd = T(dd, "IDisplayDimension")
        ann = T(dd.GetAnnotation(), "IAnnotation")
        dim = T(dd.GetDimension2(0), "IDimension")
        pos = ann.GetPosition() or (0.0, 0.0, 0.0)
        out.append((dim.SystemValue / MM, bool(ann.IsDangling()), (pos[0], pos[1]), dim.FullName))
    return out


def expected_bom(asm_doc):
    """{file name without extension: quantity} of the resolved top-level components."""
    out = collections.Counter()
    for c in (T(asm_doc, "IAssemblyDoc").GetComponents(True) or ()):
        c = T(c, "IComponent2")
        if c.GetSuppression2() != 0 and not c.ExcludeFromBOM:
            out[os.path.splitext(os.path.basename(c.GetPathName()))[0]] += 1
    return dict(out)


def read_table(table):
    t = T(table, "ITableAnnotation")
    return [[t.Text(r, c) for c in range(t.ColumnCount)] for r in range(t.RowCount)]


def pdf_preview(pdf_path, png_path, dpi=110):
    """Render page 1 of the exported PDF to a PNG for the human look. Needs PyMuPDF (`pip install pymupdf`);
    without it the SolidWorks PNG stays (a screen capture: title-block text and backgrounds can look wrong)."""
    try:
        import fitz
    except ImportError:
        return None
    with fitz.open(pdf_path) as d:
        d[0].get_pixmap(dpi=dpi).save(png_path)
    return png_path


def _section(sw, doc, drw, parent, cx, cy, width, px, py):
    """Full section A-A: a horizontal cut line through (cx, cy) across the parent view, drawn in the view's own sketch
    space (sheet coordinates put the line outside the part on 2019 -> a section without hatching), view at (px, py)."""
    import pythoncom
    from win32com.client import VARIANT
    mu = T(sw.GetMathUtility(), "IMathUtility")
    drw.ActivateView(parent.GetName2())
    tr = T(T(parent.GetSketch(), "ISketch").ModelToSketchTransform, "IMathTransform")
    pts = []
    for x in (cx - width / 2 - 0.006, cx + width / 2 + 0.006):
        p = T(mu.CreatePoint(VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [x, cy, 0.0])), "IMathPoint")
        pts.append(T(p.MultiplyTransform(tr), "IMathPoint").ArrayData)
    doc.ClearSelection2(True)
    line = doc.SketchManager.CreateLine(pts[0][0], pts[0][1], 0, pts[1][0], pts[1][1], 0)
    if line is None:
        return None
    doc.ClearSelection2(True)
    T(line, "ISketchSegment").Select4(False, None)
    v = drw.CreateSectionViewAt5(px, py, 0, "A", 0, None, 0)
    doc.ClearSelection2(True)
    return T(v, "IView") if v is not None else None


def _tolerances(drw, tolerances, problems):
    """Bilateral tolerances on imported model dimensions, read back. -> {name: (min, max)} as set."""
    done = {}
    for v in views_of(drw):
        for dd in (v.GetDisplayDimensions() or ()):
            dd = T(dd, "IDisplayDimension")
            dim = T(dd.GetDimension2(0), "IDimension")
            key = next((n for n in tolerances if dim.FullName.startswith(n + "@")), None)
            if key is None or key in done:
                continue
            lo, hi = tolerances[key]
            t = T(dim.Tolerance, "IDimensionTolerance")
            t.Type = _const("swTolBILAT", 2)
            t.SetValues(-abs(lo) * MM, abs(hi) * MM)
            got = (t.GetMinValue() / MM, t.GetMaxValue() / MM)
            done[key] = tuple(round(g, 4) for g in got)
            if abs(got[0] + abs(lo)) > 1e-6 or abs(got[1] - abs(hi)) > 1e-6:
                problems.append(f"tolerance {key} not set: {got}")
    for n in tolerances:
        if n not in done:
            problems.append(f"tolerance {n}: dimension not on the drawing")
    return done


def make_drawing(sw, model_path, out_base, paper="A3", first_angle=True, scale=None, iso=True, dims="auto",
                 centre_marks=True, bom="auto", balloons=True, expect=None, exports=("pdf",), template=None,
                 sheet_format=None, props=None, close=True, section=False, tolerances=None):
    """Build, check and export a drawing of a part or an assembly. out_base: path without extension.
    template: None = the user's default drawing template (their title block), "standard" = SolidWorks'
    Drawing.drwdot, or a path. sheet_format: None = the template's own sheet, "iso" / "din" ... = the standard
    format of that style for `paper`, or a path (.slddrt). Without sheet_format the TEMPLATE decides the sheet size.
    section: True = the view below the front view is a full section A-A through the middle of the front view
    (parts); checked: hatched section view of the expected size. tolerances: {"D1@SK_BORE": (minus, plus)} mm, set on
    the imported model dimensions as bilateral tolerances and read back.
    dims: "auto" (parts only), True, False. bom: "auto" (assemblies only), True, False.
    expect: values (mm) that must appear as dimensions (also drives the import retry).
    Returns a dict: ok, line, scale, views, dims, dangling, off_sheet, missing, bom, bom_ok, balloons, files."""
    model_path = os.path.abspath(model_path)
    is_asm = model_path.lower().endswith(".sldasm")
    if dims == "auto":                                       # an assembly drawing carries a BOM, not part dimensions
        dims = not is_asm
    was_open = sw.GetOpenDocumentByName(model_path) is not None
    model = sw.GetOpenDocumentByName(model_path)
    if model is None:
        model = sw.OpenDoc6(model_path, C.swDocASSEMBLY if is_asm else C.swDocPART, C.swOpenDocOptions_Silent, "", 0, 0)[0]
    if model is None:
        raise RuntimeError(f"cannot open {model_path}")
    model = T(model, "IModelDoc2")
    size = model_box(model, is_asm)
    pname, w, h = PAPER[paper]
    if template == "standard":
        template = standard_template(sw)
    doc = sw.NewDocument(template or drawing_template(sw), _const(pname), w, h)
    if doc is None:
        raise RuntimeError("drawing document not created (template?)")
    doc = T(doc, "IModelDoc2")
    drw = T(doc, "IDrawingDoc")
    sw.ActivateDoc3(doc.GetTitle(), False, 0, 0)            # sheet changes (scale) are ignored on an inactive drawing
    sheet = T(drw.GetCurrentSheet(), "ISheet")
    want_bom = bom is True or (bom == "auto" and is_asm)
    band = (0.0075 * (len(expected_bom(model)) + 1) + 0.012) if (want_bom and is_asm) else (0.04 if want_bom else 0.0)
    if sheet_format:
        # the sheet format decides size and title block; the scale goes in with it (SetScale after SetupSheet5
        # did not take: the views came out 1:1 on a sheet laid out for 1:2)
        a, b = scale or pick_scale(size, w, h, iso, band)
        fmt = sheet_format_file(sw, paper, sheet_format) if not os.path.isabs(sheet_format) else sheet_format
        if not drw.SetupSheet5(sheet.GetName(), _const(pname), _const("swDwgTemplateCustom", 12), float(a), float(b),
                               bool(first_angle), fmt, w, h, "Default", True):
            raise RuntimeError(f"sheet format not applied: {fmt}")
        sheet = T(drw.GetCurrentSheet(), "ISheet")
        sheet.SetScale(float(a), float(b), False, False)    # SetupSheet5 itself kept 1:1 on 2019
    else:
        # the template decides the sheet; SetScale, not SetProperties2 with a new scale (see pitfalls in drawings.md)
        sp = list(sheet.GetProperties2())                   # paper, template, scale1, scale2, firstAngle, w, h, ...
        w, h = (sp[5] or w), (sp[6] or h)
        a, b = scale or pick_scale(size, w, h, iso, band)
        if bool(sp[4]) != bool(first_angle):
            sheet.SetProperties2(sp[0], sp[1], sp[2], sp[3], bool(first_angle), w, h, bool(sp[7]) if len(sp) > 7 else True)
        sheet.SetScale(float(a), float(b), False, False)    # FLOATS: integer arguments are ignored silently (2019)
    # Views placed explicitly at the sheet scale (Create1stAngleViews2 picks its own scale: on 2019 the three views
    # came out at ~1:3.3 on a 1:2 sheet). Front view top-left, one projected view to its right, one below; the
    # sheet's projection type (first / third angle) decides what they show.
    k = a / b
    dx, dy, dz = size
    gap = 0.04                                               # room for dimensions between the views (m)
    fx, fy = 0.07 * w + dx * k / 2 + 0.03, h - 0.05 * h - dy * k / 2 - 0.025 - band
    front = drw.CreateDrawViewFromModelView3(model_path, "*Front", fx, fy, 0)
    if front is None:
        raise RuntimeError("front view not created")
    front = T(front, "IView")
    rep_scale_note = ""
    if abs(front.ScaleDecimal - k) > 1e-6 * k:
        # 2019: the sheet scale is sometimes not taken (1:500 came out 1:200): set it on the view itself; the
        # projected views created next follow their parent
        front.ScaleDecimal = k
        doc.ForceRebuild3(False)
        rep_scale_note = f"sheet scale not taken, set on the views ({a}:{b})"
        if abs(front.ScaleDecimal - k) > 1e-6 * k:
            raise RuntimeError(f"scale {a}:{b} not applied (front view is at {front.ScaleDecimal:g})")
    below = (fx, fy - dy * k / 2 - gap - dz * k / 2)
    sec_view = None
    for px, py in ((fx + dx * k / 2 + gap + dz * k / 2, fy), below):
        if section and not is_asm and (px, py) == below:
            sec_view = _section(sw, doc, drw, front, fx, fy, dx * k, px, py)
            continue
        doc.ClearSelection2(True)
        doc.Extension.SelectByID2(front.GetName2(), "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0)
        if drw.CreateUnfoldedViewAt3(px, py, 0, False) is None:
            rep_problem = f"projected view at ({px:.3f}, {py:.3f}) not created"
            raise RuntimeError(rep_problem)
    doc.ClearSelection2(True)
    iso_view = None
    if iso:
        ix = min(0.86 * w, fx + dx * k / 2 + gap + dz * k + gap + 0.6 * (dx + dz) * k / 2 + 0.03)
        iso_view = drw.CreateDrawViewFromModelView3(model_path, "*Isometric", ix, fy, 0)
        if iso_view is not None:
            iso_view = T(iso_view, "IView")
            if rep_scale_note:
                iso_view.ScaleDecimal = k
    # the template decides the real sheet: report its size, not the size that was asked for
    paper = next((n for n, (_, pw, ph) in PAPER.items() if abs(pw - w) < 2e-3 and abs(ph - h) < 2e-3),
                 f"{w * 1000:.0f}x{h * 1000:.0f}")
    rep = dict(model=os.path.basename(model_path), paper=paper, scale=f"{a}:{b}", files=[], problems=[])
    if rep_scale_note:
        rep["scale_note"] = rep_scale_note
        sheet = T(drw.GetCurrentSheet(), "ISheet")           # the title block reads the SHEET scale: try once more
        sheet.SetScale(float(a), float(b), False, False)
        sp2 = list(sheet.GetProperties2())
        if abs(sp2[2] / sp2[3] - k) > 1e-9:
            rep["problems"].append(f"title block scale: the sheet stayed {sp2[2]:g}:{sp2[3]:g} (views are {a}:{b})")
    if section and not is_asm:
        if sec_view is None:
            rep["problems"].append("section view not created")
        else:
            ol = sec_view.GetOutline()
            sw_, sh_ = (ol[2] - ol[0]) / k, (ol[3] - ol[1]) / k
            # a view outline has a margin around the geometry (2019: the same on both axes): compare the margins
            pad_w, pad_h = sw_ - dx, sh_ - dz
            ok_ = abs(pad_w - pad_h) < 0.002 and -0.001 < pad_w < 0.03
            rep["section"] = f"A-A {sw_ * 1000:.0f} x {sh_ * 1000:.0f} mm (part {dx * 1000:.0f} x {dz * 1000:.0f})"
            if not ok_ or sec_view.Type != _const("swDrawingSectionView", 2):
                rep["problems"].append(f"section view wrong: {rep['section']}, type {sec_view.Type}")
    if dims:
        # swInsertDimensions (8) must be set TOGETHER with "marked for drawing" (32768): the marked flag alone
        # brought only feature dimensions (pattern, plane) and no sketch dimension (2019)
        types = _const("swInsertDimensions", 8) | _const("swInsertDimensionsMarkedForDrawing", 32768) | \
            _const("swInsertHoleWizardProfileDimensions", 65536) | _const("swInsertHoleWizardLocationDimensions", 131072)
        # DuplicateDims MUST be False: with True, 2019 dropped 12 of the 16 model dimensions (probe 2026-11-17).
        # False brings every dimension, some in more than one view - the repeats are removed. The import is not
        # reliable on the first call (4 of 13 once): it is repeated while an expected value is still missing.
        rep["imports"] = 0
        for _ in range(3):
            doc.ForceRebuild3(False)
            drw.InsertModelAnnotations3(_const("swImportModelItemsFromEntireModel"), types, True, False, False, True)
            rep["imports"] += 1
            rep["duplicates_removed"] = rep.get("duplicates_removed", 0) + _dedupe(doc, drw)
            have = [d[0] for v in views_of(drw) for d in dims_of(v)]
            if have and not [e for e in (expect or []) if not any(abs(x - e) < 1e-3 for x in have)]:
                break
        # SolidWorks' own auto-arrange per view (the import stacks dimensions where they sit in the sketch)
        for v in views_of(drw):
            dds = v.GetDisplayDimensions() or ()
            if len(dds) < 2:
                continue
            drw.ActivateView(v.GetName2())
            doc.ClearSelection2(True)
            n = sum(_pick(doc, T(T(dd, "IDisplayDimension").GetAnnotation(), "IAnnotation")) for dd in dds)
            if n >= 2:
                try:
                    doc.Extension.AlignDimensions(_const("swAlignDimensionType_AutoArrange", 0), 0.006)
                except Exception:
                    rep["problems"].append(f"auto-arrange failed in {v.GetName2()}")
        doc.ClearSelection2(True)
        for v in views_of(drw):
            _tidy_radial(v)
    if tolerances:
        rep["tolerances"] = _tolerances(drw, tolerances, rep["problems"])
    views = views_of(drw)
    if centre_marks:
        for v in views:
            if iso_view is not None and v.GetName2() == iso_view.GetName2():
                continue
            try:
                v.AutoInsertCenterMarks2(_const("swAutoInsertCenterMarkType_Hole", 1),
                                         _const("swCenterMark_ShowNoConnectLines", 0), False, False, True, 0, 0, True,
                                         False, 0)
            except Exception:
                rep["problems"].append(f"centre marks failed in {v.GetName2()}")
    # ---- bill of materials + balloons (assemblies)
    rep["bom"], rep["bom_ok"], rep["balloons"] = None, None, 0
    if want_bom:
        host = iso_view or views[0]
        tpl = bom_template(sw)
        rep["bom_template"] = os.path.basename(tpl)
        table = host.InsertBomTable4(False, 0.07 * w, h - 0.04 * h, _const("swBOMConfigurationAnchor_TopLeft", 1),
                                     _const("swBomType_TopLevelOnly", 2), host.ReferencedConfiguration, tpl, False,
                                     _const("swNumberingType_None", 0), False)
        doc.ForceRebuild3(False)
        if table is None:
            rep["problems"].append("BOM table not created")
        else:
            rows = read_table(table)
            rep["bom"] = rows
            if is_asm and len(rows) <= 1:
                rep["bom_ok"] = False
                rep["problems"].append(f"BOM has no rows (template {rep['bom_template']!r}, columns {rows[0] if rows else []})")
            if is_asm and len(rows) > 1:
                head = [str(c).upper() for c in rows[0]]
                cp = next((i for i, c in enumerate(head) if "PART" in c), 1)
                cq = next((i for i, c in enumerate(head) if "QTY" in c or "QUANT" in c), len(head) - 1)
                got = {}
                for r in rows[1:]:
                    try:
                        got[str(r[cp]).strip()] = int(float(str(r[cq]).strip()))
                    except ValueError:
                        pass
                want = expected_bom(model)
                rep["bom_ok"] = got == want
                if not rep["bom_ok"]:
                    rep["problems"].append(f"BOM {got} != assembly {want}")
        if balloons:
            doc.ClearSelection2(True)
            doc.Extension.SelectByID2(host.GetName2(), "DRAWINGVIEW", 0, 0, 0, False, 0, None, 0)
            try:
                notes = drw.AutoBalloon5(drw.CreateAutoBalloonOptions())
                rep["balloons"] = len(notes) if notes else 0
            except Exception as ex:
                rep["problems"].append(f"balloons failed: {str(ex)[:60]}")
            doc.ClearSelection2(True)
    if props:
        cpm = T(doc.Extension.CustomPropertyManager(""), "ICustomPropertyManager")
        for k, v in props.items():
            cpm.Add3(k, C.swCustomInfoText, str(v), C.swCustomPropertyReplaceValue)
    doc.ForceRebuild3(False)
    # ---- checks
    alld = []
    rep["views"] = []
    for v in views_of(drw):
        d = dims_of(v)
        rep["views"].append((v.GetName2(), len(d)))
        alld += d
    rep["dims"] = len(alld)
    rep["dangling"] = [n for _, dang, _, n in alld if dang]
    rep["off_sheet"] = [n for _, _, (x, y), n in alld if not (0 <= x <= w and 0 <= y <= h)]
    vals = [v for v, _, _, _ in alld]
    rep["missing"] = [e for e in (expect or []) if not any(abs(v - e) < 1e-3 for v in vals)]
    # ---- save + export
    save_as(doc, out_base + ".SLDDRW")
    rep["files"].append(out_base + ".SLDDRW")
    for ext in exports:
        path = f"{out_base}.{ext}"
        if os.path.exists(path):
            os.remove(path)
        doc.Extension.SaveAs(path, 0, 1, None, 0, 0)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            rep["files"].append(path)
        else:
            rep["problems"].append(f"export {ext} failed")
    pdf = out_base + ".pdf"
    if "png" in exports and os.path.exists(pdf):
        shot = pdf_preview(pdf, out_base + ".png")           # what the shop gets, not a screen capture
        if shot:
            rep["preview"] = shot
    if close:
        sw.CloseDoc(doc.GetTitle())
        if not was_open:
            sw.CloseDoc(model.GetTitle())
    for key, text in (("dangling", "dangling dimensions"), ("off_sheet", "dimensions off the sheet"),
                      ("missing", "expected values not on the drawing")):
        if rep[key]:
            rep["problems"].append(f"{text}: {rep[key][:6]}")
    if dims and not rep["dims"]:
        rep["problems"].append("no dimensions imported")
    rep["ok"] = not rep["problems"]
    try:
        import reviewlog
        checks = [("model dimensions on the drawing", bool(rep["dims"]) or not dims, rep["dims"]),
                  ("dangling dimensions", not rep["dangling"], len(rep["dangling"])),
                  ("dimensions on the sheet", not rep["off_sheet"], len(rep["off_sheet"])),
                  ("expected values present", not rep["missing"], rep["missing"] or "all")]
        if rep.get("bom") is not None:
            checks.append(("BOM quantities = assembly", bool(rep["bom_ok"]), f"{len(rep['bom']) - 1} rows"))
        checks.append(("exports", not any("export" in p for p in rep["problems"]),
                       [os.path.splitext(f)[1] for f in rep["files"]]))
        reviewlog.record("drawing", rep["model"], checks, ["overlap / readability (look at the PDF)"])
    except Exception:
        pass
    if dims:
        rep["problems"] and rep["problems"].append(f"stages: imported {rep.get('imported')}, duplicates removed "
                                                    f"{rep.get('duplicates_removed')}, after {rep.get('after_dedupe')}")
    rep["line"] = (f"{'OK  ' if rep['ok'] else 'FAIL'} drawing {rep['model']}: {paper} scale {rep['scale']}, views "
                   f"{rep['views']}, dimensions {rep['dims']} (dangling {len(rep['dangling'])}, off sheet "
                   f"{len(rep['off_sheet'])}, expected missing {rep['missing'] or 0})"
                   + (f", BOM rows {len(rep['bom']) - 1 if rep['bom'] else 0} = assembly {rep['bom_ok']}, balloons "
                      f"{rep['balloons']}" if rep["bom"] is not None else "")
                   + (f", section {rep['section']}" if rep.get("section") else "")
                   + (f", tolerances {rep['tolerances']}" if rep.get("tolerances") else "")
                   + f", files {[os.path.splitext(f)[1] for f in rep['files']]}"
                   + (f"; problems: {rep['problems']}" if rep["problems"] else ""))
    return rep
