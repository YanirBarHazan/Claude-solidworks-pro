"""Read a 2D drawing file (.dxf, or .dwg through the ODA File Converter) into facts a part can be built from.
No SolidWorks here: plain Python + ezdxf, so it runs anywhere and is tested in CI.

    python drawing_read.py part.dxf            one-page summary + the verdict
    python drawing_read.py part.dxf --json     the whole analysis as JSON

    analyze(path) -> analysis dict              (also analyze_doc(ezdxf_doc))
    plan_sheet_metal(analysis) -> plan dict     verdict DIRECT (build it as is) or NOT_DIRECT + reasons

What it reads, and the rule behind each part (a fact is reported, a guess is not):
  - units from $INSUNITS; every length comes out in mm
  - primitives (lines, arcs, circles, polylines with bulges, ellipses / splines flattened), with blocks exploded;
    each gets an edge class from its linetype or layer: visible / hidden / center / bend / phantom / annotation
  - closed loops: visible primitives chained end to end, strictly - a node with more or fewer than two ends is a
    junction and the chain stops there; what did not close is reported as an open chain, never closed by guessing
  - views: outer loops with the loops inside them (holes); a drawing frame (layer name or ISO / ANSI sheet size)
    is set aside, not taken for a part
  - dimensions with the string the CAD system PRINTED (%%c -> Ø ...); when printed numbers and the geometry
    disagree by one steady factor, that factor is the drawing scale and is applied to the geometry
  - texts: title-block fields (material, thickness, weight, scale, part number), bend notes ("UP 90° R2")
    paired to the nearest bend line, each note used once
The sheet-metal plan is DIRECT only when everything the part needs is forced by the drawing itself: one flat
view, a closed outline, a thickness, and every bend line with its own note. Anything else is NOT_DIRECT with the
reasons - the model reads the analysis then, as an engineer would (references/drawing_to_part.md)."""
import json
import math
import os
import re
import sys

TOL = 0.01            # mm: two ends closer than this are the same point
UNITS = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 8: 0.0000254, 9: 0.0254, 10: 914.4}
SHEETS = [(297, 210), (420, 297), (594, 420), (841, 594), (1189, 841),      # ISO A4..A0 (landscape)
          (279.4, 215.9), (431.8, 279.4), (558.8, 431.8), (863.6, 558.8)]  # ANSI A..D
CLASS_BY_LINETYPE = (("HIDDEN", "hidden"), ("DASHED", "hidden"), ("CENTER", "center"), ("DASHDOT", "center"),
                     ("PHANTOM", "phantom"), ("DIVIDE", "phantom"))
CLASS_BY_LAYER = (("BEND", "bend"), ("HIDDEN", "hidden"), ("CENTER", "center"), ("CENTRE", "center"),
                  ("AXIS", "center"), ("DIM", "annotation"), ("TEXT", "annotation"), ("NOTE", "annotation"),
                  ("TITLE", "frame"), ("FRAME", "frame"), ("BORDER", "frame"), ("SHEET", "frame"),
                  ("קיפול", "bend"), ("כיפוף", "bend"), ("מסגרת", "frame"))
FIELDS = {   # title-block / note fields: (key words, value pattern)
    "material": (r"MATERIAL|MAT'L|MATL|חומר", r"(.+)"),
    "thickness": (r"THICKNESS|THK|THK\.|T\s*=|עובי", r"([0-9]+(?:[.,][0-9]+)?)"),
    "weight": (r"WEIGHT|MASS|משקל", r"([0-9]+(?:[.,][0-9]+)?)\s*(KG|G|ק\"ג|גר)?"),
    "scale": (r"SCALE|קנה\s*מידה|ק\"מ", r"([0-9]+(?:[.,][0-9]+)?)\s*:\s*([0-9]+(?:[.,][0-9]+)?)"),
    "part_number": (r"PART\s*(?:NO|NUMBER|#)|P/N|DWG\s*NO|מק\"ט|מספר\s*שרטוט", r"([\w\-./]+)"),
    "title": (r"TITLE|NAME|DESCRIPTION|שם\s*החלק|תיאור", r"(.+)"),
}
BEND_NOTE = re.compile(
    r"(?P<dir>UP|DOWN|מעלה|למעלה|מטה|למטה)?\s*(?P<ang>[0-9]+(?:[.,][0-9]+)?)\s*(?:°|DEG|%%D)\s*"
    r"(?:(?P<dir2>UP|DOWN|מעלה|למעלה|מטה|למטה)\s*)?(?:R\s*=?\s*(?P<r>[0-9]+(?:[.,][0-9]+)?))?", re.I)


# ---------------------------------------------------------------- reading
def _num(s):
    return float(str(s).replace(",", "."))


def _clean_text(t):
    t = re.sub(r"\\[A-Za-z][^;\\]*;", "", t or "")           # MTEXT inline formats \fArial|b0;  \H2.5;
    t = t.replace("\\P", "\n").replace("{", "").replace("}", "")
    return (t.replace("%%c", "Ø").replace("%%C", "Ø").replace("%%d", "°").replace("%%D", "°")
            .replace("%%p", "±").replace("%%P", "±")).strip()


def _linetype(doc, e):
    lt = (e.dxf.get("linetype", "BYLAYER") or "BYLAYER").upper()
    if lt in ("BYLAYER", "BYBLOCK"):
        try:
            lt = (doc.layers.get(e.dxf.layer).dxf.linetype or "CONTINUOUS").upper()
        except Exception:
            lt = "CONTINUOUS"
    return lt


def edge_class(linetype, layer):
    lay = (layer or "").upper()
    for key, cls in CLASS_BY_LAYER:
        if key in lay:
            return cls
    lt = (linetype or "").upper()
    for key, cls in CLASS_BY_LINETYPE:
        if key in lt:
            return cls
    return "visible"


def _flatten(doc):
    """Model-space entities with every block reference exploded (recursively)."""
    out = []

    def walk(ents, depth=0):
        for e in ents:
            if e.dxftype() == "INSERT" and depth < 8:
                try:
                    walk(list(e.virtual_entities()), depth + 1)
                except Exception:
                    out.append(("skipped", e))
            else:
                out.append(("entity", e))
    walk(doc.modelspace())
    return out


def _segments(doc, e, k):
    """LINE / ARC / CIRCLE / polylines / ellipse / spline -> list of segment dicts (mm)."""
    t = e.dxftype()
    lay = e.dxf.get("layer", "0")
    cls = edge_class(_linetype(doc, e), lay)
    base = {"layer": lay, "cls": cls}
    if t == "LINE":
        a, b = e.dxf.start, e.dxf.end
        return [dict(base, kind="line", a=(a.x * k, a.y * k), b=(b.x * k, b.y * k))]
    if t == "ARC":
        c, r = e.dxf.center, e.dxf.radius
        s, en = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
        a = (c.x + r * math.cos(s), c.y + r * math.sin(s))
        b = (c.x + r * math.cos(en), c.y + r * math.sin(en))
        return [dict(base, kind="arc", a=(a[0] * k, a[1] * k), b=(b[0] * k, b[1] * k), c=(c.x * k, c.y * k),
                     r=r * k, start=e.dxf.start_angle % 360, end=e.dxf.end_angle % 360)]
    if t == "CIRCLE":
        c = e.dxf.center
        return [dict(base, kind="circle", c=(c.x * k, c.y * k), r=e.dxf.radius * k)]
    if t in ("LWPOLYLINE", "POLYLINE"):
        segs = []
        for v in e.virtual_entities():
            for s in _segments(doc, v, k):
                s.update(base)
                segs.append(s)
        return segs
    if t in ("ELLIPSE", "SPLINE"):
        pts = [(p.x * k, p.y * k) for p in e.flattening(0.01)]
        return [dict(base, kind="line", a=pts[i], b=pts[i + 1], approx=t.lower()) for i in range(len(pts) - 1)
                if math.dist(pts[i], pts[i + 1]) > 1e-9]
    return None


def _arc_points(s, n=24):
    span = (s["end"] - s["start"]) % 360 or 360
    return [(s["c"][0] + s["r"] * math.cos(math.radians(s["start"] + span * i / n)),
             s["c"][1] + s["r"] * math.sin(math.radians(s["start"] + span * i / n))) for i in range(n + 1)]


def _key(p):
    return (round(p[0] / TOL), round(p[1] / TOL))


def _flip(s):
    s = dict(s)
    s["a"], s["b"] = s["b"], s["a"]
    s["rev"] = not s.get("rev", False)
    return s


def chain(segs):
    """Chain line / arc segments into closed loops. Strict: a node is walked through only when exactly two ends
    meet there; at a junction (3+) or a free end the chain stops and is reported open, never closed by a guess.
    -> (loops, open_chains, junctions); each is a list of segments oriented head to tail."""
    ends = {}
    for i, s in enumerate(segs):
        ends.setdefault(_key(s["a"]), []).append(i)
        ends.setdefault(_key(s["b"]), []).append(i)
    junctions = [k for k, v in ends.items() if len(v) > 2]
    used, loops, chains = set(), [], []

    def walk(path):
        """extend path forward from its last end; True when it closes on its first start."""
        while True:
            node = _key(path[-1]["b"])
            here = ends[node]
            if len(here) != 2:
                return False
            j = here[0] if here[1] == path[-1]["_i"] else here[1]
            if j == path[0]["_i"] and len(path) > 1 or (j == path[-1]["_i"] and here[0] == here[1]):
                return _key(path[0]["a"]) == node
            if j in used:
                return False
            used.add(j)
            s = dict(segs[j], _i=j)
            path.append(s if _key(s["a"]) == node else _flip(s))

    for i in range(len(segs)):
        if i in used:
            continue
        used.add(i)
        path = [dict(segs[i], _i=i)]
        if walk(path):
            loops.append(path)
            continue
        back = [_flip(path[0])]                     # open forward: grow the other way from the first segment
        walk(back)
        full = [_flip(s) for s in reversed(back[1:])] + path
        chains.append(full)
    return loops, chains, junctions


def loop_points(loop):
    pts = []
    for s in loop:
        if s["kind"] == "arc":
            p = _arc_points(s)
            if s.get("rev"):
                p = p[::-1]
            pts.extend(p[:-1])
        else:
            pts.append(s["a"])
    return pts


def area(pts):
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2


def bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _inside(b, outer):
    return b[0] >= outer[0] - TOL and b[1] >= outer[1] - TOL and b[2] <= outer[2] + TOL and b[3] <= outer[3] + TOL


def _is_sheet(b):
    w, h = b[2] - b[0], b[3] - b[1]
    w, h = max(w, h), min(w, h)
    return any(abs(w - W) <= 0.03 * W and abs(h - H) <= 0.03 * H for W, H in SHEETS)


def _dist_point_seg(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def _fields(texts):
    out = {}
    for t in texts:
        for line in t["text"].split("\n"):
            for name, (key, val) in FIELDS.items():
                if name in out:
                    continue
                m = re.search(rf"(?:{key})\s*[:=]?\s*{val}", line, re.I)
                if m:
                    out[name] = {"text": line.strip(), "value": m.group(m.lastindex if name != "weight" else 1)}
                    if name in ("thickness",):
                        out[name]["value"] = _num(m.group(1))
                    elif name == "weight":
                        unit = (m.group(2) or "KG").upper()
                        out[name]["value"] = _num(m.group(1)) * (0.001 if unit in ("G", "גר") else 1.0)
                        out[name]["unit"] = "kg"
                    elif name == "scale":
                        out[name]["value"] = _num(m.group(1)) / _num(m.group(2))
                    else:
                        out[name]["value"] = m.group(1).strip()
    return out


def _dimension(e, k):
    raw = e.dxf.get("text", "") or ""
    try:
        meas = e.get_measurement()
        meas = float(meas) if not hasattr(meas, "x") else None
    except Exception:
        meas = None
    dtype = e.dimtype & 7 if hasattr(e, "dimtype") else e.dxf.get("dimtype", 0) & 7
    kind = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular", 6: "ordinate"}.get(
        dtype, "linear")
    printed = _clean_text(raw.replace("<>", f"{meas:g}" if meas is not None else "<>")) if raw not in ("", "<>") \
        else (f"{meas:g}" if meas is not None else "")
    if kind == "diameter" and printed and not printed.startswith("Ø"):
        printed = "Ø" + printed
    num = re.search(r"[0-9]+(?:[.,][0-9]+)?", printed or "")
    geo = meas * (k if kind not in ("angular",) else 1) if meas is not None else None
    return {"kind": kind, "printed": printed, "value": _num(num.group(0)) if num else None,
            "geometry": round(geo, 4) if geo is not None else None, "override": raw not in ("", "<>"),
            "layer": e.dxf.get("layer", "0")}


def analyze_doc(doc, source="(document)"):
    k = UNITS.get(doc.header.get("$INSUNITS", 4), 1.0)
    segs, circles, texts, dims, skipped, frame = [], [], [], [], {}, []
    not_read = {}
    for what, e in _flatten(doc):
        t = e.dxftype()
        if what == "skipped":
            skipped[t] = skipped.get(t, 0) + 1
            continue
        if t in ("TEXT", "MTEXT", "ATTRIB"):
            raw = e.plain_text() if t == "MTEXT" else e.dxf.get("text", "")
            p = e.dxf.insert
            texts.append({"text": _clean_text(raw), "at": (p.x * k, p.y * k), "layer": e.dxf.get("layer", "0")})
            continue
        if t == "DIMENSION":
            dims.append(_dimension(e, k))
            continue
        try:
            got = _segments(doc, e, k)
        except Exception:
            got = None
        if got is None:
            not_read[t] = not_read.get(t, 0) + 1
            continue
        for s in got:
            if s["cls"] == "frame":
                frame.append(s)
            elif s["kind"] == "circle":
                circles.append(s)
            else:
                segs.append(s)

    # drawing scale: printed dimension numbers vs. the geometry they measure
    ratios = sorted(d["value"] / d["geometry"] for d in dims
                    if d["kind"] in ("linear", "aligned", "diameter", "radius") and d["value"] and d["geometry"])
    scale_used, scale_note = 1.0, "no dimensions to check the scale against"
    if ratios:
        med = ratios[len(ratios) // 2]
        steady = sum(1 for r in ratios if abs(r / med - 1) < 0.005)
        if abs(med - 1) < 0.005:
            scale_note = f"1:1 ({steady} of {len(ratios)} dimensions agree with the geometry)"
        elif steady >= max(2, 0.6 * len(ratios)):
            scale_used = med
            scale_note = (f"geometry drawn at 1:{1 / med:g}: {steady} of {len(ratios)} printed dimensions = "
                          f"geometry x {med:g}; applied")
        else:
            scale_note = f"printed dimensions do not agree with the geometry by one factor ({len(ratios)} checked)"
    if scale_used != 1.0:
        def sc(p):
            return (p[0] * scale_used, p[1] * scale_used)
        for s in segs + circles:
            for key in ("a", "b", "c"):
                if key in s:
                    s[key] = sc(s[key])
            if "r" in s:
                s["r"] *= scale_used
        for t in texts:
            t["at"] = sc(t["at"])
        for d in dims:
            if d["geometry"] is not None and d["kind"] != "angular":
                d["geometry"] = round(d["geometry"] * scale_used, 4)

    visible = [s for s in segs if s["cls"] == "visible"]
    bends = [s for s in segs if s["cls"] == "bend" and s["kind"] == "line"]
    loops_raw, chains, junctions = chain([dict(s) for s in visible])
    loops = []
    for lp in loops_raw:
        pts = loop_points(lp)
        if len(pts) >= 3:
            loops.append({"segments": lp, "points": pts, "bbox": bbox(pts), "area": area(pts)})
    for c in circles:
        if c["cls"] != "visible":
            continue
        r = c["r"]
        pts = [(c["c"][0] + r * math.cos(2 * math.pi * i / 48), c["c"][1] + r * math.sin(2 * math.pi * i / 48))
               for i in range(48)]
        loops.append({"segments": [c], "points": pts, "bbox": [c["c"][0] - r, c["c"][1] - r, c["c"][0] + r,
                                                              c["c"][1] + r], "area": math.pi * r * r,
                      "circle": {"center": c["c"], "d": 2 * r}})

    # frame: a sheet-sized loop that holds other loops is the drawing border, not a part
    loops.sort(key=lambda L: -L["area"])
    frames = [L for L in loops if _is_sheet(L["bbox"]) and any(_inside(o["bbox"], L["bbox"]) for o in loops
                                                                 if o is not L)]
    loops = [L for L in loops if L not in frames]
    views = []
    for L in loops:                                  # largest first: a loop inside an existing view is its hole
        host = next((v for v in views if _inside(L["bbox"], v["outer"]["bbox"])), None)
        if host is None:
            views.append({"outer": L, "holes": []})
        elif not any(_inside(L["bbox"], h["bbox"]) for h in host["holes"]):
            host["holes"].append(L)

    fields = _fields(texts)
    notes = []
    for t in texts:
        m = BEND_NOTE.search(t["text"].upper().replace("%%D", "°"))
        if m and ("°" in t["text"] or "%%D" in t["text"].upper() or "DEG" in t["text"].upper()):
            d = (m.group("dir") or m.group("dir2") or "").upper()
            notes.append({"text": t["text"], "at": t["at"], "angle": _num(m.group("ang")),
                          "radius": _num(m.group("r")) if m.group("r") else None,
                          "direction": "up" if d in ("UP", "מעלה", "למעלה") else "down" if d else None})
    free = list(range(len(notes)))
    bend_out = []
    for b in bends:                                   # each note goes to its nearest bend line, once
        best = min(free, key=lambda i: _dist_point_seg(notes[i]["at"], b["a"], b["b"]), default=None)
        note = None
        if best is not None:
            L = math.dist(b["a"], b["b"])
            if _dist_point_seg(notes[best]["at"], b["a"], b["b"]) <= max(15.0, 0.25 * L):
                note = notes[best]
                free.remove(best)
        bend_out.append({"a": b["a"], "b": b["b"], "length": round(math.dist(b["a"], b["b"]), 4),
                         "note": note})

    units_warning = None
    if views:
        big = max(max(v["outer"]["bbox"][2] - v["outer"]["bbox"][0], v["outer"]["bbox"][3] - v["outer"]["bbox"][1])
                  for v in views)
        if k > 1 and big > 5000 and scale_used == 1.0:
            units_warning = (f"the file says its units are x{k:g} mm, which makes the part {big / 1000:.1f} m long; "
                             f"in mm it would be {big / k:.2f} mm - confirm the units")
    gaps = [{"from": c[0]["a"], "to": c[-1]["b"], "segments": len(c)} for c in chains]
    # T-junctions: a free end that lands inside another line (a silhouette ending mid-edge). Reported, not split:
    # which side the edge belongs to is a reading decision, not a fact of the file.
    lines = [x for x in visible if x["kind"] == "line"]
    t_junctions = []
    for c in chains:
        for p in (c[0]["a"], c[-1]["b"]):
            for ln in lines:
                if (_dist_point_seg(p, ln["a"], ln["b"]) < TOL and math.dist(p, ln["a"]) > TOL
                        and math.dist(p, ln["b"]) > TOL):
                    t_junctions.append([round(p[0], 4), round(p[1], 4)])
                    break
    return {
        "source": source,
        "units_to_mm": k,
        "units_warning": units_warning,
        "scale": {"factor_applied": scale_used, "note": scale_note,
                  "title_block": fields.get("scale", {}).get("value")},
        "counts": {"segments": len(segs), "circles": len(circles), "texts": len(texts), "dimensions": len(dims),
                   "frame_items": len(frame)},
        "views": [{"bbox": [round(x, 4) for x in v["outer"]["bbox"]], "area": _wire_area(_loop_wire(v["outer"])),
                   "outer": _loop_wire(v["outer"]), "holes": [_loop_wire(h) for h in v["holes"]]} for v in views],
        "frames_ignored": len(frames),
        "open_chains": gaps,
        "junctions": len(junctions),
        "t_junctions": t_junctions,
        "hidden_segments": sum(1 for s in segs if s["cls"] == "hidden"),
        "center_segments": sum(1 for s in segs if s["cls"] == "center"),
        "bends": bend_out,
        "bend_notes_unpaired": [notes[i] for i in free],
        "dimensions": dims,
        "fields": fields,
        "texts": [t["text"] for t in texts][:200],
        "not_read": {**not_read, **{f"block:{k2}": v for k2, v in skipped.items()}},
    }


def _wire_area(w):
    return round(math.pi * w["d"] ** 2 / 4, 4) if w["kind"] == "circle" else w["area"]


def exact_area(segs):
    """Area of a closed profile of lines and arcs (wire form: a, b, c, r, ccw) - exact, no sampling:
    the polygon of the segment ends plus each arc's circular segment, signed by its turn."""
    pts = [tuple(sg["a"]) for sg in segs]
    poly = sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(len(pts))) / 2
    sign = 1 if poly >= 0 else -1
    extra = 0.0
    for sg in segs:
        if sg["kind"] != "arc":
            continue
        a0 = math.atan2(sg["a"][1] - sg["c"][1], sg["a"][0] - sg["c"][0])
        a1 = math.atan2(sg["b"][1] - sg["c"][1], sg["b"][0] - sg["c"][0])
        sweep = (a1 - a0) % (2 * math.pi) if sg["ccw"] else -((a0 - a1) % (2 * math.pi))
        seg_area = sg["r"] ** 2 / 2 * (abs(sweep) - math.sin(abs(sweep)))
        # an arc turning the same way as the loop bulges outward (adds area); the other way it cuts in
        extra += seg_area if (sweep > 0) == (sign > 0) else -seg_area
    return abs(poly) + extra


def _loop_wire(L):
    if "circle" in L:
        c = L["circle"]
        return {"kind": "circle", "center": [round(c["center"][0], 4), round(c["center"][1], 4)],
                "d": round(c["d"], 4)}
    segs = []
    for s in L["segments"]:
        if s["kind"] == "arc":
            segs.append({"kind": "arc", "a": [round(v, 4) for v in s["a"]], "b": [round(v, 4) for v in s["b"]],
                         "c": [round(v, 4) for v in s["c"]], "r": round(s["r"], 4), "ccw": not s.get("rev", False)})
        else:
            segs.append({"kind": "line", "a": [round(v, 4) for v in s["a"]], "b": [round(v, 4) for v in s["b"]]})
    return {"kind": "profile", "segments": segs, "area": round(exact_area(segs), 4),
            "bbox": [round(x, 4) for x in L["bbox"]]}


def _read(path):
    import ezdxf
    if path.lower().endswith(".dwg"):
        try:
            from ezdxf.addons import odafc
            return odafc.readfile(path)
        except Exception as e:
            raise RuntimeError("a .dwg is read through the free ODA File Converter (opendesign.com); install it, "
                               f"or save the drawing as .dxf ({type(e).__name__}: {e})") from None
    return ezdxf.readfile(path)


def analyze(path):
    return analyze_doc(_read(path), os.path.basename(path))


# ---------------------------------------------------------------- sheet metal plan
def plan_sheet_metal(a, thickness=None):
    """DIRECT: the drawing alone fixes the part (one flat view, closed outline, thickness, a note on every bend).
    thickness: from the user when the drawing has none (a fact the user gave, not a guess)."""
    reasons = []
    t = thickness if thickness is not None else a["fields"].get("thickness", {}).get("value")
    if not a["views"]:
        reasons.append("no closed outline found")
    elif len(a["views"]) > 1:
        reasons.append(f"{len(a['views'])} views: not a single flat pattern - read it as an engineer "
                       "(references/drawing_to_part.md)")
    if a.get("units_warning"):
        reasons.append(a["units_warning"])
    if a["t_junctions"]:
        reasons.append(f"{len(a['t_junctions'])} edge(s) end in the middle of another edge (first at "
                       f"{a['t_junctions'][0]}): a section or step the reader does not split by itself")
    if a["open_chains"]:
        reasons.append(f"{len(a['open_chains'])} visible chain(s) do not close (first gap at "
                       f"{[round(v, 2) for v in a['open_chains'][0]['from']]})")
    if t is None:
        reasons.append("no thickness in the drawing (THK / THICKNESS / עובי): ask the user")
    missing = [i for i, b in enumerate(a["bends"]) if not b["note"]]
    if missing:
        reasons.append(f"bend line(s) {missing} have no note with angle and direction")
    no_r = [i for i, b in enumerate(a["bends"]) if b["note"] and b["note"]["radius"] is None]
    if no_r:
        reasons.append(f"bend(s) {no_r} have no radius (R): ask the user or take the shop's default")
    if a["scale"]["note"].startswith("printed dimensions do not agree"):
        reasons.append("the drawing scale is unclear: " + a["scale"]["note"])
    view = a["views"][0] if a["views"] else None
    plan = {"verdict": "NOT_DIRECT" if reasons else "DIRECT", "reasons": reasons, "kind": "sheet_metal",
            "thickness": t, "material": a["fields"].get("material", {}).get("value")}
    if view:
        flat = view["area"] - sum(_wire_area(h) for h in view["holes"])
        plan.update(outline=view["outer"], holes=view["holes"],
                    bends=[{"line": [b["a"], b["b"]], "angle": b["note"]["angle"] if b["note"] else None,
                            "radius": b["note"]["radius"] if b["note"] else None,
                            "direction": b["note"]["direction"] if b["note"] else None} for b in a["bends"]],
                    expect={"flat_area_mm2": round(flat, 3),
                            "volume_mm3": round(flat * t, 3) if t else None,
                            "flat_bbox_mm": [round(view["bbox"][2] - view["bbox"][0], 4),
                                             round(view["bbox"][3] - view["bbox"][1], 4)],
                            "weight_kg": a["fields"].get("weight", {}).get("value")})
    return plan


def summary(a, plan=None):
    plan = plan or plan_sheet_metal(a)
    L = [f"DRAWING {a['source']}: units x{a['units_to_mm']:g} -> mm; scale: {a['scale']['note']}",
         f"views {len(a['views'])}" + "".join(
             f"; view {i + 1}: {v['bbox'][2] - v['bbox'][0]:.2f} x {v['bbox'][3] - v['bbox'][1]:.2f} mm, "
             f"{len(v['holes'])} hole(s)" for i, v in enumerate(a["views"])),
         f"bends {len(a['bends'])} ({sum(1 for b in a['bends'] if b['note'])} with a note); "
         f"open chains {len(a['open_chains'])}; hidden {a['hidden_segments']}; frames ignored {a['frames_ignored']}",
         "fields: " + (", ".join(f"{k}={v['value']}" for k, v in a["fields"].items()) or "-"),
         f"dimensions {len(a['dimensions'])}: " + ", ".join(d["printed"] for d in a["dimensions"][:12]),
         ]
    if a["not_read"]:
        L.append("not read: " + ", ".join(f"{k} x{v}" for k, v in a["not_read"].items()))
    L.append(f"VERDICT {plan['verdict']}" + ("" if not plan["reasons"] else ": " + "; ".join(plan["reasons"])))
    if plan.get("expect"):
        e = plan["expect"]
        L.append(f"expect: flat {e['flat_bbox_mm'][0]} x {e['flat_bbox_mm'][1]} mm, area {e['flat_area_mm2']} mm²"
                 + (f", volume {e['volume_mm3']} mm³" if e["volume_mm3"] else "")
                 + (f", weight {e['weight_kg']} kg" if e["weight_kg"] else ""))
    return "\n".join(L)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.stdout.reconfigure(encoding="utf-8")
    an = analyze(sys.argv[1])
    if "--json" in sys.argv:
        print(json.dumps({"analysis": an, "plan": plan_sheet_metal(an)}, ensure_ascii=False, indent=1, default=str))
    else:
        print(summary(an))
