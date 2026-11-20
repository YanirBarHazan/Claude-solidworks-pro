# Production drawings through the API

## Start here: one call (`scripts/drawings.py`, verified on SolidWorks 2019, 2026-11-18)
```python
from drawings import make_drawing
rep = make_drawing(sw, r"...\FLANGE.sldprt", r"...\out\FLANGE",
                   expect=[120, 64, 34, 12],                 # values that must appear on the drawing (mm)
                   section=True,                              # the view below the front = full section A-A
                   tolerances={"D1@SK_BORE": (0, 0.05)},      # bilateral, on the model's own dimension
                   template="standard", sheet_format="iso",   # or None = the user's default template / title block
                   exports=("pdf", "dxf", "png"))
print(rep["line"])                                            # OK / FAIL + every number below
```
What it does and checks:
- **Views**: front + one projected view + (part) section A-A or (assembly) the second projected view + isometric,
  at a standard scale chosen to fit the sheet; first or third angle from `first_angle`.
- **Dimensions = the MODEL's own dimensions** (so the drawing follows the model), duplicates across views removed,
  linear ones auto-arranged, radial ones moved clear of the views. Checked: none dangling, all on the sheet, every
  `expect` value present (the import is repeated while one is missing - it is flaky on 2019).
- **Section**: cut line drawn in the view's own sketch space, hatched view created; checked by its size.
- **Tolerances**: set on the imported dimensions and read back.
- **Assembly**: bill of materials (top level) in a band above the views + balloons; checked: BOM quantities =
  components counted in the assembly.
- **Exports**: SLDDRW + PDF / DXF / PNG; the PNG is rendered from the PDF (PyMuPDF) - what the shop receives.
- **Review log**: every check goes to `out/review_log.jsonl` for the review report (`review.py`).
- **Title block**: fields come from custom properties - part: Description, Material (`pb.link_properties()` makes
  Material / Weight follow the model), drawing: `props={"DrawnBy": ..., "Revision": ...}`. The scale field reads
  the SHEET scale.

Measured on the test flange (2019): 13 model dimensions, section A-A, tolerance +0.05/0, ISO A3 title block with
SCALE 1:2, PDF + DXF, ~10 s per drawing. Assembly (34 components): BOM 3 rows = assembly counts, 2 balloons.

**Always look at the PDF / PNG once per drawing type** - numbers cannot see crowded or overlapping text. Known
leftovers: two model dimensions with the same value at the same place both appear (e.g. hole position and pattern
spacing); a company template whose title-block notes scale with the sheet becomes unreadable at small scales (tell
the user - it is the template); not done yet: detail views, GD&T frames, hole tables, multi-sheet drawings.

## Pitfalls of the API (2019)
- Activate the drawing (`ActivateDoc3`) before changing its sheet: on an inactive drawing `SetScale` /
  `SetupSheet5` scale is ignored, the views come out 1:1 and the title block says 1:1.
- `ISheet.SetScale` needs float arguments; `SetProperties2` with a new scale rescaled the sheet-format notes.
- `Create1stAngleViews2` picks its own scale - place views with `CreateDrawViewFromModelView3` +
  `CreateUnfoldedViewAt3`.
- `InsertModelAnnotations3(..., DuplicateDims=False, ...)` (True dropped 12 of 16 dimensions); repeat the import.
- `IAnnotation.Select3` returns False on drawing dimensions: `ISelectionMgr.AddSelectionListObject`.
- BOM: pass the view's `ReferencedConfiguration` and rebuild before reading the table.
- A view outline includes a margin around the geometry (the same on both axes).

## Manual recipe (when the one call is not enough)
Verified on SOLIDWORKS 2025, ISO A3, first angle (v1).

Worked example: the desk-agent project script `step8_drawing.py` (hinge block) - copy and adapt.

## Recipe
1. Part custom properties feed the title block (`$PRPSHEET:` fields): Description, Material, Finish, Weight.
   `cpm = T(part.Extension.CustomPropertyManager(""), "ICustomPropertyManager")`;
   `cpm.Add3(name, C.swCustomInfoText, value, C.swCustomPropertyReplaceValue)`. Drawing properties
   (`$PRP:` fields): DrawnBy, DrawnDate, CheckedBy, Revision, COMPANYNAME. DWG NO = file name.
2. `doc = sw.NewDocument(<templates>\Drawing.DRWDOT, C.swDwgPaperA3size, 0.42, 0.297)`;
   `drw.SetupSheet5(name, C.swDwgPaperA3size, C.swDwgTemplateCustom, scale1, scale2, True (first angle),
   <lang\english\sheetformat\a3 - iso.slddrt>, 0.42, 0.297, "Default", True)`.
3. Document style: `SetUserPreferenceInteger(swDetailingLinearDimPrecision, 0, 1)`,
   `swDetailingLinearTolPrecision` 2, `swDetailingDimTrailingZero` = `swDimRemoveTrailingZeroes`.
4. Views: `CreateDrawViewFromModelView3(part, "*Front", x, y, 0)`; select it
   (`SelectByID2(view.GetName2(), "DRAWINGVIEW", ...)`) then `CreateUnfoldedViewAt3(x, y, 0, False)`.
   First angle: put the RIGHT view on the LEFT, the TOP view BELOW. Iso: `"*Isometric"`, ScaleDecimal.
   Display: `view.SetDisplayMode3(False, C.swHIDDEN / swHIDDEN_GREYED / swSHADED_EDGES, False, True)`.
5. Section: activate the parent view, draw the cut line in the VIEW SKETCH space, select it,
   `drw.CreateSectionViewAt5(x, y, 0, "A", 0, None, 0)`. Check the result has hatching.
6. Centre marks: `view.AutoInsertCenterMarks2(swAutoInsertCenterMarkType_Hole, swCenterMark_ShowNoConnectLines,
   False, False, True, 0, 0, True, False, 0)`.
7. Dimensions: `drawtools.Dimensioner` (select edges through model points, place relative to the view
   outline, read the value back). Tolerances: `t = T(dim.Tolerance, "IDimensionTolerance")`;
   `t.Type = C.swTolBILAT`; `t.SetValues(min_m, max_m)`; read back `GetMinValue/GetMaxValue`.
8. Notes: `note = T(doc.InsertNote(text), "INote")`; `note.SetTextJustification(C.swTextJustificationLeft)`;
   `T(note.GetAnnotation(), "IAnnotation").SetPosition2(x, y, 0)` (upper-left of the box).
9. Export: `doc.Extension.SaveAs(".pdf" / ".png", 0, 1, None, 0, 0)`. LOOK at the PNG (crop/zoom with
   PIL): value checks cannot see overlapping text or a section that cut nothing.

## Pitfalls met
- A sketch in a drawing view uses the view space (model units about the view centre = sheet scaled by
  1/scale and shifted): convert sheet points with `view.GetSketch().ModelToSketchTransform`.
  Using sheet coordinates put the section line outside the part -> a "section" with no hatching.
- `IDimensionTolerance.SetValues2(..., swSetValue_InThisConfiguration, None)` silently did nothing in a
  drawing; `SetValues(min, max)` works.
- `SetText(swDimensionTextPrefix, "2X ")` replaces the default prefix and drops the diameter symbol:
  use `"2X <MOD-DIAM>"`.
- The default note justification put the text left of its anchor (off the sheet): set it left first.
- Place dimensions from the view outline (bbox corners through the view transform), not from the picked
  point, or they land inside the view.
- Edge picking: `SelectByID2("", "EDGE", sheet_x, sheet_y, ...)` at a model point mapped by
  `view.ModelToViewTransform` works; pick points away from other edges and from section arrows.

## Content that improves on a typical company sheet
Critical-to-function dims marked `*` with real tolerances (fits), general tolerances in the notes,
a section through the feature whose depth matters, an iso view, process notes (print orientation,
inserts, assembly), weight computed from the model, revision field filled.

## Entry point (from SKILL.md v1)
For a production drawing read `references/drawings.md` and use `scripts/drawtools.py`; check every
dimension value AND look at the exported PNG (overlaps, empty sections).
