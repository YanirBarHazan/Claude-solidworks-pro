# From a 2D drawing to a part (.dxf / .dwg)

A supplier sends a drawing with no model. The reader turns it into facts, the plan says whether those facts
alone fix the part, and the build is proven against numbers taken from the drawing BEFORE building.

## 1. Read (`scripts/drawing_read.py`, no SolidWorks needed)
    python drawing_read.py part.dxf            summary + verdict
    python drawing_read.py part.dxf --json     everything (views, loops, dimensions, title block, bends)
A .dwg needs the free ODA File Converter (or ask for a .dxf). What the reader guarantees:
- every length in mm (`$INSUNITS`); a header that makes the part absurdly large is questioned, not applied
- closed outlines are chained strictly: a junction or a T-junction stops the chain and is reported
- dimensions carry the string the CAD system PRINTED - that string wins over the stored number; a steady factor
  between printed numbers and geometry is the drawing scale and is applied
- the frame / title block is set aside; its fields (material, thickness, weight, scale, part number) are read
- bend notes ("UP 90° R2", "מעלה 90° R2") are paired to the nearest bend line, each note once

## 2. Decide
`plan_sheet_metal()` gives **DIRECT** only when the drawing alone fixes the part: one flat view, a closed
outline, a thickness, a note (angle + direction + radius) on every bend line, a clear scale. Anything else is
**NOT_DIRECT** with the reasons. Then read it as an engineer, in this order, and ask - never guess:
1. Which views exist and how they project (first / third angle: from the title block or the symbol; if neither,
   ask). Match each view's extents to the others before using any of them.
2. The base shape from the view that shows it whole; depths from the views that show them.
3. Every feature's size from a PRINTED dimension. A size you can only measure off the geometry is an assumption:
   list it back to the user.
4. Hidden lines = internal features (pockets, through holes): confirm with a section if one is drawn.
5. Before building: the expected volume / weight from the drawing's own numbers, written down.

## 3. Build and prove (`scripts/drawing_build.py`)
- flat part: outline + holes extruded by `T`; globals `T` and `HOLE_D<n>`; verify bbox and volume against the
  drawing, an edit test on `T`, save + reopen
- bends: waits for the live API check (`scripts/probe_api.py --sheetmetal`) - no API call is written from memory
- a weight in the title block: compare mass after setting the material (`materials_properties.md`)
Report: built / not built, the measured numbers against the drawing's, and every assumption.
