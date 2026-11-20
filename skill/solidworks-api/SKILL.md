---
name: solidworks-api
description: Drive SolidWorks directly from Python (pywin32 COM) as a senior CAD engineer would - real parametric parts and assemblies whose design intent lives in SolidWorks (dimensions linked to global variables, named reference geometry, mates, patterns, configurations by suppression), verified with numbers, updated in place instead of rebuilt, and safe to edit by hand afterwards. Use this whenever the user wants SolidWorks files (.sldprt/.sldasm/.slddrw) made, changed, checked or audited, wants Claude to "work in SolidWorks", design a part, bracket, enclosure, mechanism, frame or large repetitive structure, change values across a model, check fits/interference, make drawings, run a Motion study, or prepare parts for 3D printing - even if they don't mention the API, pywin32 or COM. Also use when a previous attempt to connect Claude to SolidWorks via plugins/macros failed, or to judge how editable an existing model is.
---

# SolidWorks through the API

Claude runs Python on the same Windows machine as SolidWorks, talks to the running instance over COM, builds the
model and **verifies every step itself**. What makes it work is the method, not the API: a small library that
absorbs the API's quirks, design intent decided before geometry, and never trusting what has not been measured.

## Five rules (always)
1. **Never rebuild an existing part to change it.** Open it and update it in place (global values, equations,
   properties, appended features). A rebuild is needed only when the feature structure changes - stop and ask first.
2. **Never report success without numbers.** Parts: rebuild errors, one body, bounding box and volume against a
   hand calculation, an edit test, save + reopen. Assemblies: solved position = computed position, an explicit
   list of designed overlaps, counts. Say what was not verified.
3. **Design intent before geometry.** Decide what drives what (skeleton / named reference geometry, mates,
   patterns, files vs configurations) and name every feature, sketch, plane and mate. A human must be able to open
   the model, understand it from the tree and change it. Only the skeleton / base component is fixed: seeds are
   mated to a skeleton part and repeats are patterns driven by assembly equations, so a value edited in Tools >
   Equations moves the model (`references/assemblies.md` 13). `asmtools.check_held()` enforces it: more than one
   Fixed component or a floating one FAILS the assembly. Computed-transform placement is a measured fallback, used
   only when the user approved it (`check_held(fixed_ok="reason")`).
   Build for change: every value a client may change is ONE global that SolidWorks propagates (assemblies.md 14).
   This holds for throwaway test and benchmark models too, and say in one line before a test model appears in the
   user's SolidWorks.
4. **Never overwrite human work silently.** Hand edits are detected before a file is touched; stop and ask
   (keep / adopt into the parameters / discard). Open only the documents the task changes: read an assembly
   from the assembly (`swx card`, its component list), never by opening every component file. Close only
   documents you opened; never touch files outside the project.
5. **Spend few credits.** One summary line per item, details in `logs/` (read only `tail` / `grep`); long runs in
   the background, saving after each unit; measure a slow step before guessing at it; anything the user will repeat
   becomes a tool that runs without Claude; log every SolidWorks error in the project's notes in the same turn;
   keep sessions short with a hand-over file (`references/dialogue.md` 7).

**Day log (automatic).** Every script that calls `connect()` and every changing `swx` command writes one line to
`~/.solidworks-api/daylog/<date>.jsonl`: script, time, ok / error, files opened, and for each open assembly how
many components are Fixed / floating / mated and how many mates it has. At the end of a working day, or when the
user says something went wrong, run `python scripts/daylog.py [date]`: one page (`<date>.md`) with the day's
requests, runs and Claude Code conversations on one timeline, and warnings where a rule above was broken. Read
the warnings before answering a complaint; a warning that repeats is a fix to this skill.

## Workflow
1. **Setup** (once per machine, `references/setup.md`): SolidWorks open, `pip install pywin32`, copy `scripts/`
   into the project, `python scripts/preflight.py` (seconds, no documents; on a SolidWorks version never tested
   it runs the full capability suite once and writes a report - say so to the user first: it takes minutes).
   Set `SW_REQUIRE_REV` when the files must open in an older SolidWorks (a newer save can never be reopened
   by an older version).
2. **Dialogue** (`references/dialogue.md`): **at the start of EVERY project ask the start questions (section 0)** -
   verification level, start check, review report, and your restated understanding of the design - then one
   design-brief round, then a one-page project card (`templates/PROJECT_CARD.md`) approved before building.
   Gates: one sample part -> one sub-assembly -> the whole model, each with a review PDF (`scripts/review.py`).
3. **Parameters**: one file, every value with a source tag `[M]` measured, `[D]` datasheet / decision, `[C]`
   calculated, `[A]` assumption (listed back to the user). Derived geometry in one module. For layout-driven
   models run the layout and clearance checks in plain Python before any CAD.
4. **Build** with the library: `PartBuilder` links every dimension to a global variable, so the user edits the part
   in Tools > Equations. One outline per sketch; shapes through the library (they get proper relations); named
   reference geometry (`PL_*`, `AX_*`) on everything that will be mated. Raw API only after
   `references/pitfalls.md`.
5. **Verify** (`references/verification.md`) after every part and assembly; stop on any failure.
6. **Deliver**: the files, one command that updates everything from the parameters, a short guide for the
   engineer, the open assumptions, and the audit score (`scripts/audit.py`).

## Module map - read only what the task needs
| When the task is | Read |
|---|---|
| Talking to the user, planning, estimating, hand-over | `references/dialogue.md`, `references/intake.md` |
| Any raw API call the library does not cover | `references/pitfalls.md`, `references/api_cheatsheet.md` |
| Changing an existing model, value changes, batch runs, one-command updates | `references/update_in_place.md` |
| The user also edits in SolidWorks | `references/hand_edits.md` |
| Checking a part or assembly | `references/verification.md` |
| Assemblies, mates, patterns, > 30 components, configurations | `references/assemblies.md` (start at section 13) |
| Judging an existing model (how editable is it?) | `scripts/audit.py` (read-only, one line + JSON) |
| Standard holes, feature patterns, mirror inside a part | `references/part_features.md` |
| Materials, mass, weight / material properties for BOM and title block | `references/materials_properties.md` |
| Production drawings, BOM, sections, tolerances, PDF / DXF | `references/drawings.md` (`scripts/drawings.py`: one call) |
| 3D-printed parts, enclosures, snap fits, print files | `references/fdm_printing.md`, `references/engineering.md` |
| A SolidWorks error or a version question | `references/version_notes.md` |
| Reading listings, approval sketches, token habits | `references/tools_and_workflow.md` |
| Quick look / value change in the open document (fast commands), or the Claude tab inside SolidWorks | `references/panel.md` |
| What happened today / the user is unhappy with a session | `python scripts/daylog.py` -> `~/.solidworks-api/daylog/<date>.md` |

## Library (`scripts/`)
- `sw_common.py` - connect, early binding, typed wrapper `T()`, version guard, templates, save, safe closing.
  `connect()` turns on fast mode (`CommandInProgress`: COM calls 0.15 ms instead of ~15 ms; capability suite 397 s ->
  117 s on 2019) and resets it at exit; `SW_FAST=0` turns it off (version note 45).
- `swpanel_worker.py` + `swx.py` - warm worker and its client: `card` (compact model summary + what changed since the last look - read it
  instead of re-reading the feature tree), `info` (document, selection with geometry in part
  and assembly coordinates, features, equations, size), `set NAME=VALUE [--selected]` (in place), `fillet`, `save`,
  `run script.py` - ~0.2 s each instead of a 2 s start-up per script (`references/panel.md`).
- `swpanel_taskpane.py` - the Claude chat tab inside the SolidWorks Task Pane (`references/panel.md`).
- `swcad.py` - `PartBuilder`: planes, sketches, extrude / cut, Hole Wizard, feature pattern / mirror, material and
  mass, linked equations and properties, update mode, checks, verified save.
- `paramfile.py` - the parameter text file (`NAME = value ; note`, groups, value sets, in-place rewrite).
- `partsync.py` - manifests, hand-edit detection, three-way value decision, build / update decision. `filesafe.py` - backup and
  change detection for any file before it is overwritten.
- `asmtools.py` - placement, mates on named planes, mate / transform checks, interference, linear patterns,
  `check_held` (the held-by-mates gate).
- `patterns.py` - turns a placement list into seeds + linear patterns. `hygiene.py` - stale locks, stall detector.
- `daylog.py` - the day log: recorder (started by `connect()`, nothing to call) and the one-page day report.
- `audit.py` - model health / editability score of any existing part or assembly.
- `reviewlog.py` - the project's verification level + the log of every check; `review.py` - the one-page review PDF.
- `drawings.py` - one call from a model to a checked drawing (views, model dimensions, section, tolerances,
  BOM + balloons, PDF / DXF). `drawtools.py` - extra dimensions picked on model edges.
- `orient_stl.py`, `overhangs.py`, `bambu_project.py` - print pipeline.
- `preflight.py` - start-of-work check: quick on a tested version, full capability suite on a new one.
  `smoke_test.py`, `sync_test.py` - self tests it runs. `bench_asm.py` - speed benchmark on a 739-component
  skeleton / mates / equation-driven-pattern assembly; `swpanel_seltest.py`, `swpanel_bench.py` - panel tests.

## Status
Field-tested on SolidWorks 2019 (a 770-component structure); the library was first
written on a newer release. Recipes say where they were tested; anything else is untested, not known to fail.
`ROADMAP.md` lists what is planned (design-intent assemblies with a skeleton, two-way value sync, project
scaffold, materials and mass, drawings + BOM, sheet metal, simulation).
