# Manufacturing and optimisation - rules of thumb for design review

Used by the Claude tab (`[ייצור]` / `[ייעול]` lines) and in any design review. These are common shop guidelines,
not a standard: the supplier's own limits win. Always tie a remark to a MEASURED feature of the model
(`swx info` / `card` / a short `run` script), never to a guess about geometry you did not measure.

## 0. Choosing the process (quantity x geometry x material)
| Quantity | Typical best fit |
|---|---|
| 1-10 | FDM / SLA print (plastic, fit checks), CNC from stock, laser-cut sheet + bending, welded profiles |
| 10-1,000 | CNC, sheet metal (laser + press brake), SLS / MJF print, urethane casting, welded frames with a jig |
| 1,000+ | injection moulding (plastic), die casting (Al / Zn), stamping (sheet), extrusion + cut (constant section) |
Hints from geometry: constant thickness + bends -> sheet metal; constant cross-section -> extrusion / profile;
thin ribs + bosses + plastic -> moulding (print for prototypes); rotationally symmetric -> turning (lathe).
If quantity or material is unknown and it changes the advice, say the assumption in a `[הנחה]` line.

## 1. CNC milling
- Internal vertical corners need a radius: R >= tool radius; aim R >= 1/3 of pocket depth (R3 for a 9 mm pocket).
  Sharp internal corner = EDM or a redesign (relief / dog-bone).
- Pocket depth <= 4x tool diameter (6x is slow and chatters). Walls: Al >= 0.8-1 mm, steel >= 0.5 mm,
  plastics >= 1.5 mm.
- Holes: standard drill sizes; depth <= 4-5x diameter (deeper = gun drill / pecking, cost x2+); blind holes get a
  118° drill point; threads: tap depth 1.5x D is enough (M6 -> 9 mm), more adds cost not strength.
- Setups cost money: features on 1-2 sides instead of 6 sides. Count the directions the tool must come from.
- Tolerances: +-0.1 mm general is cheap; +-0.02 only where it fits (bearings, dowels) - mark them, not everything.
- Stock: size the part to standard bar / plate (Al plate 5, 6, 8, 10, 12, 15, 20, 25 mm) plus ~2-3 mm clean-up.

## 2. Turning (lathe)
- Rotational parts: prefer turning over milling. Undercuts / grooves need standard insert widths (2, 3 mm).
- Length / diameter > 3-4 needs tailstock support; thin long parts deflect.
- Off-axis features (flats, cross holes) add a milling op - group them.

## 3. Sheet metal (laser / punch + press brake)
- Constant thickness. Inside bend radius ~= thickness (min 0.5-1x t steel, 1-2x t aluminium 5052; 6061-T6 cracks:
  avoid bending or use large radius).
- Hole to bend edge >= 2x t + R; hole diameter >= t; hole to hole / edge >= 2x t.
- Flange length >= 4x t (the die needs to hold it). Add bend reliefs where a bend meets an edge.
- Same bend radius and direction on every bend = one tool, fewer setups. Fewer bends = cheaper.
- Replace a welded box by tabs + slots or bent flanges; replace machined brackets by bent sheet when loads allow.

## 4. Welding and frames
- Standard profiles (RHS 40x40x2, 50x50x3, angle, flat bar); one profile size where possible.
- Design for the jig: square cuts beat mitres for cost; coped ends only where needed.
- Weld access for the torch; avoid welds on finished / machined faces (distortion) - machine after welding.
- Hot-dip galvanising: vent / drain holes in closed sections (dia >= 10 mm, both ends).

## 5. Injection moulding / casting
- Uniform wall (plastics 1.5-3 mm; ABS / PP ~2-2.5 mm); thick sections sink and warp -> core them out.
- Draft 1-2° on walls in the pull direction (more on textured faces). No undercuts unless a side action is paid for.
- Ribs 50-60% of wall, height <= 3x wall; bosses with a cored hole, joined to walls by ribs.
- Radii on all corners (inner R >= 0.5x wall). Die casting: similar, walls 2-4 mm Al.

## 6. 3D printing
- FDM: see `fdm_printing.md` / `engineering.md` (walls, clearances, overhangs, orientation for strength).
- SLS / MJF: no supports, min wall ~1 mm, escape holes for hollow parts, good for small series of complex parts.

## 7. Optimisation checklist (what to suggest, in this order)
1. **Fewer parts**: merge parts that never move relative to each other and share a process.
2. **Standard parts**: catalogue fasteners, bearings, profiles, sheet thicknesses; one screw size across the product.
3. **Fewer setups / operations**: features from fewer directions, same radii / hole sizes, fewer tools.
4. **Right process for the quantity** (section 0) - the biggest cost lever.
5. **Material**: cheaper / easier grade when loads allow (6061 vs 7075, S235 vs stainless, PLA vs PETG vs nylon).
6. **Tolerances only where they work**; general tolerance everywhere else.
7. **Mass**: remove material only where it does not carry load (pockets, lightening holes), check stiffness.
8. **Assembly**: self-locating features, one assembly direction, no hidden fasteners, poka-yoke (cannot be fitted wrong).
State the expected gain in numbers when you can measure it (mass -x %, setups 4 -> 2, parts 7 -> 4).
