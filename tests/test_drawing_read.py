"""drawing_read: DXF -> analysis -> sheet-metal plan. Synthetic drawings made here with ezdxf, one per rule."""
import math

import ezdxf
import pytest

import drawing_read as dr


def new(units=4):
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = units
    return doc, doc.modelspace()


def rect(msp, x, y, w, h, layer="0"):
    msp.add_lwpolyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], close=True, dxfattribs={"layer": layer})


def test_flat_plate_with_holes_is_direct():
    doc, msp = new()
    rect(msp, 0, 0, 100, 60)
    msp.add_circle((20, 30), 3.3)
    msp.add_circle((80, 30), 3.3)
    msp.add_text("THK 2", dxfattribs={"insert": (0, -10)})
    msp.add_text("MATERIAL: AL 5052", dxfattribs={"insert": (0, -20)})
    a = dr.analyze_doc(doc)
    p = dr.plan_sheet_metal(a)
    assert p["verdict"] == "DIRECT", p["reasons"]
    assert len(a["views"]) == 1 and len(a["views"][0]["holes"]) == 2
    assert p["thickness"] == 2 and p["material"] == "AL 5052"
    flat = 100 * 60 - 2 * math.pi * 3.3 ** 2
    assert p["expect"]["flat_area_mm2"] == pytest.approx(flat, abs=1e-3)
    assert p["expect"]["flat_bbox_mm"] == [100, 60]


def test_bend_with_note_is_direct_and_paired():
    doc, msp = new()
    rect(msp, 0, 0, 120, 80)
    doc.layers.add("BEND", linetype="DASHED")
    msp.add_line((0, 30), (120, 30), dxfattribs={"layer": "BEND"})
    msp.add_text("UP 90° R2", dxfattribs={"insert": (50, 32)})
    msp.add_text("THICKNESS: 1.5", dxfattribs={"insert": (0, -10)})
    a = dr.analyze_doc(doc)
    p = dr.plan_sheet_metal(a)
    assert p["verdict"] == "DIRECT", p["reasons"]
    b = p["bends"][0]
    assert (b["angle"], b["radius"], b["direction"]) == (90, 2, "up")


def test_bend_without_note_is_not_direct():
    doc, msp = new()
    rect(msp, 0, 0, 120, 80)
    msp.add_line((0, 30), (120, 30), dxfattribs={"layer": "BEND"})
    msp.add_text("THK 2", dxfattribs={"insert": (0, -10)})
    p = dr.plan_sheet_metal(dr.analyze_doc(doc))
    assert p["verdict"] == "NOT_DIRECT" and any("bend line" in r for r in p["reasons"])


def test_missing_thickness_is_asked_not_guessed():
    doc, msp = new()
    rect(msp, 0, 0, 50, 50)
    a = dr.analyze_doc(doc)
    assert dr.plan_sheet_metal(a)["verdict"] == "NOT_DIRECT"
    assert dr.plan_sheet_metal(a, thickness=3)["verdict"] == "DIRECT"     # the user gave it


def test_open_outline_is_reported_not_closed():
    doc, msp = new()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=False)   # last edge missing
    msp.add_text("THK 2", dxfattribs={"insert": (0, -10)})
    a = dr.analyze_doc(doc)
    assert a["views"] == [] and len(a["open_chains"]) == 1 and a["open_chains"][0]["segments"] == 3
    assert dr.plan_sheet_metal(a)["verdict"] == "NOT_DIRECT"


def test_junction_stops_the_chain():
    doc, msp = new()
    rect(msp, 0, 0, 100, 50)
    msp.add_line((50, 0), (50, -20))           # ends in the middle of the bottom edge: a T-junction
    msp.add_line((0, 50), (-20, 50))           # ends ON a corner: three ends meet there, a junction
    a = dr.analyze_doc(doc)
    assert a["t_junctions"] == [[50, 0]]
    assert a["junctions"] == 1
    p = dr.plan_sheet_metal(a, thickness=2)
    assert p["verdict"] == "NOT_DIRECT" and any("middle of another edge" in r for r in p["reasons"])


def test_arcs_and_reversed_segments_close():
    doc, msp = new()
    # a slot outline drawn with lines in mixed directions and two arcs
    msp.add_line((0, 0), (40, 0))
    msp.add_arc((40, 10), 10, -90, 90)
    msp.add_line((0, 20), (40, 20))             # drawn left -> right: reversed relative to the loop
    msp.add_arc((0, 10), 10, 90, 270)
    a = dr.analyze_doc(doc)
    assert len(a["views"]) == 1 and not a["open_chains"]
    assert a["views"][0]["area"] == pytest.approx(40 * 20 + math.pi * 100, abs=1e-3)


def test_frame_is_ignored():
    doc, msp = new()
    rect(msp, 0, 0, 297, 210)                 # A4 border
    rect(msp, 50, 50, 80, 40)
    a = dr.analyze_doc(doc)
    assert a["frames_ignored"] == 1 and len(a["views"]) == 1
    assert a["views"][0]["bbox"] == [50, 50, 130, 90]


def test_two_views_need_engineering_reading():
    doc, msp = new()
    rect(msp, 0, 0, 60, 40)
    rect(msp, 100, 0, 60, 5)
    msp.add_text("THK 5", dxfattribs={"insert": (0, -10)})
    p = dr.plan_sheet_metal(dr.analyze_doc(doc))
    assert p["verdict"] == "NOT_DIRECT" and any("views" in r for r in p["reasons"])


def test_scale_from_printed_dimensions():
    doc, msp = new()
    rect(msp, 0, 0, 50, 30)                     # drawn at 1:2: the real part is 100 x 60
    for (p1, p2, base) in (((0, 0), (50, 0), (0, -10)), ((0, 0), (0, 30), (-10, 0))):
        angle = 0 if p1[1] == p2[1] else 90
        d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, text=str(round(math.dist(p1, p2) * 2)))
        d.render()
    a = dr.analyze_doc(doc)
    assert a["scale"]["factor_applied"] == pytest.approx(2.0)
    assert a["views"][0]["bbox"] == pytest.approx([0, 0, 100, 60])


def test_inch_units_and_diameter_symbol():
    doc, msp = new(units=1)                    # inches
    rect(msp, 0, 0, 4, 2)
    d = msp.add_diameter_dim(center=(1, 1), radius=0.25, angle=45, text="%%c<>")
    d.render()
    a = dr.analyze_doc(doc)
    assert a["units_to_mm"] == 25.4
    assert a["views"][0]["bbox"] == pytest.approx([0, 0, 101.6, 50.8])
    assert any(x["printed"].startswith("Ø") for x in a["dimensions"])


def test_summary_runs():
    doc, msp = new()
    rect(msp, 0, 0, 10, 10)
    a = dr.analyze_doc(doc)
    assert "VERDICT" in dr.summary(a)


def test_units_header_that_makes_a_giant_part_is_questioned():
    doc, msp = new(units=6)                    # header says meters, the outline was drawn in mm
    rect(msp, 0, 0, 120, 40)
    msp.add_text("THK 2", dxfattribs={"insert": (0, -10)})
    a = dr.analyze_doc(doc)
    assert a["units_warning"] and "120.00 mm" in a["units_warning"]
    assert dr.plan_sheet_metal(a)["verdict"] == "NOT_DIRECT"


def test_exact_area_of_lines_and_arcs():
    slot = [{"kind": "line", "a": [0, 0], "b": [40, 0]},
            {"kind": "arc", "a": [40, 0], "b": [40, 20], "c": [40, 10], "r": 10, "ccw": True},
            {"kind": "line", "a": [40, 20], "b": [0, 20]},
            {"kind": "arc", "a": [0, 20], "b": [0, 0], "c": [0, 10], "r": 10, "ccw": True}]
    assert dr.exact_area(slot) == pytest.approx(800 + 100 * math.pi, abs=1e-9)
    notch = [{"kind": "line", "a": [0, 0], "b": [40, 0]}, {"kind": "line", "a": [40, 0], "b": [40, 20]},
             {"kind": "line", "a": [40, 20], "b": [30, 20]},
             {"kind": "arc", "a": [30, 20], "b": [10, 20], "c": [20, 20], "r": 10, "ccw": False},
             {"kind": "line", "a": [10, 20], "b": [0, 20]}, {"kind": "line", "a": [0, 20], "b": [0, 0]}]
    assert dr.exact_area(notch) == pytest.approx(800 - 50 * math.pi, abs=1e-9)


def test_build_expectation_from_the_drawing():
    import drawing_build as db
    doc, msp = new()
    rect(msp, 0, 0, 100, 60)
    msp.add_circle((20, 30), 3.3)
    msp.add_circle((80, 30), 3.3)
    msp.add_circle((50, 30), 5)
    msp.add_text("THK 2", dxfattribs={"insert": (0, -10)})
    plan = dr.plan_sheet_metal(dr.analyze_doc(doc))
    expect, gl, circles = db.expect_for(plan)
    assert gl == {"HOLE_D1": 10.0, "HOLE_D2": 6.6} or gl == {"HOLE_D1": 6.6, "HOLE_D2": 10.0}
    size, vol = expect({"T": 2, **gl})
    assert size == [100, 60, 2]
    assert vol == pytest.approx((6000 - 2 * math.pi * 3.3 ** 2 - math.pi * 25) * 2, rel=1e-9)
    assert vol == pytest.approx(plan["expect"]["volume_mm3"], rel=1e-6)
    # an edit of a hole global changes the expected volume, as it will change the part
    _, vol2 = expect({"T": 2, **{k: (v + 1 if v == 10.0 else v) for k, v in gl.items()}})
    assert vol2 < vol
