# Setup (once per machine, ~2 min)

1. SolidWorks open, same Windows user, **not** "Run as administrator" (else COM can't see it).
2. `pip install pywin32` (numpy optional, for area checks).
3. Copy `scripts/*.py` from this skill into the project folder (they save parts to `./parts`,
   or set env `SW_OUT`). Then `python scripts/preflight.py`:
   - **known version** (in the skill's table, or fully tested on this machine before): a quick check only - connect,
     version, version guard, templates, open documents. Seconds, no document is created, almost no tokens.
   - **version never tested**: the full capability suite runs once (parts, update in place, Hole Wizard, patterns,
     material, sketches, skeleton assembly with mates, drawings + BOM, audit). Minutes. Tell the user before.
     The report goes to `~/.solidworks-api/version_<year>.md` on that machine; nothing is uploaded. A FAIL marks one
     capability as unavailable on that version (write it in the version notes) - it does not stop the rest.
   - `--full` forces the suite (after a service pack), `--quick` never runs it.
   The user's own engineering checks (how much to verify while building) are a separate question of the design
   brief (`dialogue.md`), not part of this start check.
4. If several SolidWorks versions are installed, `sw_common` uses the folder of the running
   SLDWORKS.exe (override `SW_DIR`). Check add-ins you will need (e.g. Motion: `cmotionsw.dll`
   in that folder) *before* promising a feature — tell the user early if it's missing.
5. **Version guard.** If the project targets an older SolidWorks (files go to a PDM/team on that version),
   set `SW_REQUIRE_REV` (e.g. `27.` for 2019) and refuse to work on any other running version: a newer save
   can never be reopened by the older one. Read `references/version_notes.md` for known version issues.
6. A project with a special need (e.g. Pack and Go, a PDM vault path, a company template) adds ONE small check of
   that need in the project folder; the generic capabilities are covered by preflight.
