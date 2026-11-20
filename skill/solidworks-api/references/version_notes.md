# Version notes

The library was developed on SolidWorks 2025. Findings on other versions go here: symptom, cause, workaround.

## Version guard
Several versions on one PC are common (2019 + 2020 seen). A part saved by a newer version cannot be opened by an
older one, ever. `connect()` must refuse unless `RevisionNumber()` starts with the required major
(`SW_REQUIRE_REV`, e.g. `27.` = 2019, `28.` = 2020 ... `33.` = 2025). Tell the user to close the other version and
never to open project files by double-click while two versions are installed.

## SolidWorks 2019 (revision 27.x)
| # | Symptom | Cause | Workaround |
|---|---|---|---|
| 1 | `Equations` error 51 after save + reopen (2 of 3 runs) | `IEquationMgr.LinkToFile` to an external txt | do not link; globals live in each part (`--no-link`); a project text file + update script replaces the link |
| 2 | `GetPackAndGo()` → "Parameter not optional" / "Invalid number of parameters" | 2019 type library signature | Pack and Go by hand (or investigate the late-bound call) |
| 3 | Crash when opening the ~46th document in a row | each `OpenDoc6` opens a window | `sw.DocumentVisible(False, type)` while loading, restore in `finally` |
| 4 | `InterferenceDetectionManager` is None | assembly opened without a window is not active | open normally + `ActivateDoc3` |
| 5 | Interference on ~740 comps hangs / "object disconnected" | job size | see assemblies.md §5 |
| 6 | Next open hangs on a modal "file in use" dialog | `~$*.sld*` locks left by a crashed instance | before each run with no documents open: delete stale lock files of the project |
| 7 | Colour read back differs from the value set (0.05 → 0.047) | `MaterialPropertyValues` stored as 8-bit RGB | compare with 1/255 tolerance |
| 8 | COM blocked, no error | any modal dialog | lock-file hygiene; trace log + stall detector (pitfall 42) |
| 9 | Non-ASCII project path | worked for parts, assemblies and saves | set `PYTHONIOENCODING=utf-8`; avoid shell heredocs with non-ASCII text, write files with the file tool |
| 10 | Every update run "changes" a value like 2/3 | global values are stored to ~6 significant digits (0.666667) | compare at 1e-6 relative (`push_globals`) |
| 11 | Documents from failed runs stay open; a later `SaveAs` of the same name returns error 1 | `close_out_docs` only closed documents directly in `SW_OUT` | close documents in any sub-folder of `SW_OUT` too; close the part's documents on every failure in a one-session batch |
| 12 | `AddConfiguration2` -> "Internal application error" | adding a configuration after a `ShowConfiguration2` | add all configurations first |
| 13 | `SetEquationAndConfigurationOption` -> "Internal application error" on a new part | first configuration-specific value set on a new configuration | set it first on the template's configuration (renamed after the others exist) |
| 14 | `SaveAs` ok=False err=1 although the file is written (configured part) | not isolated; unsaved test parts and the template `Part.prtdot` were open | open |
| 15 | On a clean restart, the configured-part code -> "Internal application error" twice, then a crash | configuration-specific equations in a batch (suspect `GetConfigurationNames()` on an unsaved part before `AddConfiguration2`) | **do not use**; configurations by suppression |
| 16 | "RPC failed" / "object disconnected" mid-build, SolidWorks closes by itself | suspected: VPN drop -> network licence (SolidNetWork) lost | keep the VPN up or borrow a licence; scripts save per file and can resume |
| 17 | `NewDocument` works, then throws "The server threw an exception" a minute later | instance in a bad state (template `Part.prtdot` was open as a document) | restart SolidWorks |
| 18 | Shell heredocs with long Python fail ("unexpected EOF") | quoting in the shell wrapper | write files with the file tool and run them |
| 19 | `ISldWorks.VersionHistoryFromFile` missing in the 2019 type library | API age | `IModelDoc2.VersionHistory()` after opening; a file that opens in 2019 was saved by <= 2019 |
| 20 | `InterferenceDetectionManager` on 738 comps: hang / disconnect | job size | per sub-assembly + ~190-comp cut-out assembly + Python clearances |
| 21 | Component Linear Pattern by API: `CreateDefinition(swFmLocalLPattern)` + `CreateFeature` returns None; `FeatureLinearPattern5` by selection does nothing | the selection MARKS: seeds must be mark 1, direction-1 axis mark 2, direction-2 axis mark 4 (found by trying 11 variants) | `asmtools.linear_pattern` (`FeatureLinearPattern2`) and `modify_pattern` (count/spacing of an existing pattern in place, survives reopen) |
| 22 | `MirrorComponents3` (same component instance about a reference plane) | works | use it for symmetric halves of a structure |
| 23 | `SaveAs` err=1 when saving over an assembly, no `~$` lock file in the folder | the file was open in a SECOND SolidWorks instance (the user viewing it); Windows holds the file | before saving over a shared file test `open(path, "r+b")`; ask the user to close it; never kill their instance |
| 24 | "object disconnected" on the first document call of a run, the next run fine | VPN dropped (network licence) - confirmed by the user reconnecting it | retry once after the VPN is back |
| 25 | Assembly configurations by suppression: per-component `SetSuppression2` on ~100 components of a 770-component assembly ran > 25 min (killed) | every call updates the assembly | select all seeds + pattern features, then ONE `EditSuppress2` per configuration; pattern instances follow their pattern feature |
| 26 | Same job still 15 min per configuration after that fix | measured: `FirstFeature/GetNextFeature` walk of the tree = 55 s on 770 components, and the script walked it once PER pattern looked up (56x); `GetComponents` 26 s; select 0.2 s; `EditSuppress2` 0.6 s; rebuild 2.6 s | walk the tree ONCE into a name -> feature dict: 35 s per configuration. Measure before guessing: the cost was COM traffic, not SolidWorks work |
| 27 | `IsSuppressed()` said all 770 components were suppressed right after a silent `OpenDoc6` | components not resolved yet | count resolved with `GetSuppression2() != 0` after a rebuild |
| 28 | Equation `sqr(TOP_H^2 + LEAN^2)` gave 5778.4 instead of 5821.5 with the global LEAN = -500 | a negative global under `^` is evaluated as -(500^2) | never square a signed global with `^`: write `X*X` (or `abs(X)^2`). The volume / bbox check caught it |
| 29 | SolidWorks died during a 74-part batch (part 33): "RPC server is unavailable", then "Operation unavailable" for every later part | crash of SolidWorks itself | restart and rerun: fingerprints skip the finished parts; write the 'last good values' snapshot only after a PASS so the change is detected again |
| 30 | Lock on the main assembly after a killed run | the killed Python left it open in the SAME session (89 documents) | `CloseDoc(title)` in the connected session before the `open(path, 'r+b')` lock test |
| 31 | (library bug, fixed) update mode rewrote equations in place but reported the part 'unchanged', closed it unsaved and stored its fingerprint | only global / property changes counted as a change | `PartBuilder.edited` lists equation / sketch edits; the runner saves + verifies when it is not empty |
| 32 | Drawing sheet scale ignored: `ISheet.SetScale(1, 2, ...)` with integer arguments did nothing; on one sheet even floats were ignored (1:500 came out 1:200) | COM argument types / unknown | pass floats; check the front view's `ScaleDecimal` after creating it and set `view.ScaleDecimal` when the sheet scale was not taken (`drawings.py`) |
| 33 | `InsertModelAnnotations3(..., DuplicateDims=True, ...)` imported 4 of 16 model dimensions | the flag's meaning is inverted in practice | pass False and delete the repeats; repeat the import while an expected value is missing |
| 34 | `IAnnotation.Select3` returns False for drawing dimensions | - | `ISelectionMgr.AddSelectionListObject(annotation, None)` |
| 35 | `GetFirstDocument().GetNext()` -> "Member not found" | the first document comes back late-bound | wrap in `T(d, "IModelDoc2")` before `GetNext` |
| 36 | (works) a text `.swb` macro runs with `RunMacro2(path, <file name>, "main", 0)`; inside it `Application.VBE` is available: `VBComponents.Add(3)` adds a UserForm, `Designer.Controls.Add` adds controls, `CodeModule.AddFromString` adds code (form + 5 controls + code in 0.06 s) | - | the panel form is built at runtime by the launcher (swpanel) |
| 37 | Setting `VBComponent.Name` -> 0x80010108 "object disconnected"; `Properties("Caption")` -> 50135 | unknown (runtime-added component) | keep the default name; set caption / size in `UserForm_Initialize` |
| 38 | `VBProject.SaveAs` -> error 748 "not valid in this type of project"; the VBE Save button is disabled (`Execute` fails) | SolidWorks owns project saving | a `.swp` cannot be produced by code; sources stay as text, built on each launch |
| 39 | `.swb` projects persist for the session (project `Evaluation1`): forms added by earlier runs accumulate | - | the launcher removes its own earlier forms (marker in the form code) |
| 40 | A modeless form shown from a `.swb` closes the moment `main` returns (window destroyed), so a Win32 `SetTimer` bound to it never fires | SolidWorks resets the macro project when the macro ends | keep `main` alive with a `Sleep 50` + `DoEvents` loop; the loop also does the 2 s poll |
| 41 | With that loop running, SolidWorks went **Not Responding** permanently at 15:28:26, 0.04 s before an external tool (desktop control) hid the SolidWorks windows; before that, 49 ticks / 98 s, COM calls from Python (new part + extrude) worked | suspected: hiding / minimising the main window while a VBA `DoEvents` loop runs; not reproduced yet | OPEN: stage-0 spike failed; see docs/swpanel-dev/STAGE0.md in the repository |
| 42 | Arial in an MSForms label shows "✓" as a box | no glyph in the font | plain text status words, no symbols |
| 43 | (decision after 41) the Claude panel is a separate Python window, not a VBA form: minimise / restore / hide / show of SolidWorks while it polls -> no hang, COM 0-8 ms | nothing runs on SolidWorks' main thread | `docs/swpanel-dev/swpanel_window.py` (repository); superseded by the Task Pane tab, `references/panel.md` |
| 50 | Assembly equations and component values (phase 0 spike, `spike_asm_equations.py`) | - | an assembly equation can drive a PLAIN dimension of a component part (top level and inside a sub-assembly; all instances follow; kept after save + reopen); driving a part GLOBAL or a sub-assembly GLOBAL is rejected (`Add2` -1) - feed a sub-assembly through one of its dimensions (e.g. a distance mate) that its own equation reads; `atn()` returns degrees. OPEN: Equations error 51 in the top assembly after reopen, values correct |
| 44 | Late-bound `Dispatch`: `sw.RevisionNumber()` / `doc.GetTitle()` -> "'str' object is not callable" | dynamic dispatch exposes no-argument methods as properties | call through a helper that calls only if callable |
| 45 | Every out-of-process COM call costs ~15 ms while SolidWorks is idle (4 ms while a Task Pane page polls it); a 22-feature tree walk took 4.2 s | SolidWorks serves external calls from its idle message loop | `sw.CommandInProgress = True`: 0.15 ms per call, walk 80 ms (100x). The flag is a COUNTER and SURVIVES a killed client (each True needs a False). Now in `sw_common.connect()`: clears leftovers, turns it on, resets at exit; `SW_FAST=0` turns it off; `with fast(sw):` for other code. Measured with it: capability suite 13/13 OK in 117 s (was 397 s); 754-feature walk 31.6 -> 2.8 s; 738 component reads 36.7 -> 4.4 s; skill-recipe assembly (skeleton, 6 mates, equation-driven patterns, 739 components, `bench_asm.py`): position check 62.6 -> 6.8 s, tree walk 12.6 -> 2.5 s, SPAN_X edit + recheck 32.0 -> 5.0 s. Explains row 26 (55 s walk) |
| 46 | Panel `set --selected` (global of a part inside a sub-assembly): `SetEquation` changed the text, `Value` stayed 11, hole stayed Ø11, no error | same as `asmtools.edit_component_equation`: the component's document must be ACTIVE for an equation change (2019) | activate the part, `EditRebuild3`, re-activate the top; `swpanel_seltest.py` step 5 checks it from the top assembly (r 5.5 -> 6.0 -> 5.5) |
| 47 | First component added with `AddComponent5` to a new assembly is FIXED; plane mates to it then fail with error 51 and the part stays at the insertion point | API behaves like the GUI (first component fixed) | `UnfixComponent` before mating (or `fix_only` the skeleton on purpose) |
| 48 | `IMeasure` on one arc + a point with `ArcOption = 1` gave the nearest point of the arc, not its centre | 0 = centre, 1 = minimum, 2 = maximum | `ArcOption = 0` for centre distances |
| 49 | (not a bug) a large update run with fast mode stopped mid-parts: "object disconnected" then "Operation unavailable" | the user closed SolidWorks during the run | none; a closed SolidWorks looks exactly like a crash in the log - ask before blaming the code |

## How this table is kept
Every new failure gets a row in the same turn (symptom | cause found or suspected | status). Rows 10-20 come from one
day on a 738-component model; each with its measured cost.

## Tested on (capability suite: `scripts/preflight.py`)
| SolidWorks | Suite | Result | Notes |
|---|---|---|---|
| 2019 SP3 (27.3) | 2.1 | 13 / 13 OK, 397 s (2026-11-18) | + field project of 770 components |
| 2019 SP3 (27.3) | 2.1 + fast mode | 13 / 13 OK, 117 s (2026-11-18) | `connect()` fast mode; large-assembly update 619 s (was 1,181 s) |
| 2025 | - | not run with v2 | the v1 library and the drawing recipe were first written on 2025 |
Other versions: untested (not known to fail). Run `preflight.py` on them - it runs the full suite on first use - and
send the report from `~/.solidworks-api/` to add a row here.
