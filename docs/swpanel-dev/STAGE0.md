# SolidWorks Claude panel - stage 0 (contract + risk spikes)

Status: **VBA form spike FAILED (SolidWorks hung) -> user chose the fallback: Python window beside SolidWorks.
Python window: all automatic checks PASS on 2019 SP3 (27.3). Open: the user's own Hebrew typing + Send check.**
Date: 2026-11-18. Machine: work PC, ANSI code page 1255.

## Decision: Python panel window (`scripts/swpanel_window.py`)
Separate process (`pythonw`), tkinter, always on top, bottom-right corner, single instance (named mutex).
SolidWorks state is read over COM in a worker thread (its own apartment), so a busy SolidWorks blocks only that
thread, never the window, and nothing of ours runs on SolidWorks' main thread. Launch: a shortcut / `pythonw
swpanel_window.py` (toolbar button in stage 2: a one-line `.swb` that shells out, or a desktop shortcut).

| Check (`scripts/swpanel_window_test.py`, run 15:57:58) | Result |
|---|---|
| Window up | 0.31 s, visible, WS_EX_TOPMOST |
| (b) 2 s refresh | 6 polls / 12 s, period 2.00 s |
| (c) Hebrew UTF-8 status -> label -> echo | 3/3 exact (quotes, backslash, Ø); latency 1.61 / 2.01 / 2.01 s (= one poll period); renders in correct RTL order (screenshot) |
| (a) panel sees SolidWorks | new part + Front Plane selected -> panel showed the document and "1 selected" after 2.42 s; document closed -> "no active document" after 1.11 s; worker COM call 5 ms |
| (a) work while open | Ø11 x 20 extrude, volume 1900.7 mm³ = expected 1900.7 |
| (a) minimise / restore / hide / show SolidWorks while polling | SolidWorks COM answered in 5.6 / 8.1 / 0 / 0 ms; panel kept polling (5 polls); no hang |
| Typing Hebrew into the panel + Send | not automatable here (desktop control blocked by the window in front); user check |

Implementation note: late-bound `Dispatch` exposes no-argument methods (`RevisionNumber`, `GetTitle`) as
properties - `_get()` handles both.

## Contract (draft, unchanged by the spike result)
Folder: `%USERPROFILE%\.solidworks-api\swpanel\` (ASCII path on purpose: VBA file I/O is ANSI).
All files UTF-8 without BOM, written to `<name>.tmp` then renamed (no reader sees half a file).

| File | Writer | Content |
|---|---|---|
| `inbox/<id>.json` (stage 3; `request.json` in the spike) | panel | `{"schema": "swpanel.request/1", "id", "time", "text", "doc": {"path", "type", "config"}, "selection": [ ...stage-1 objects ]}` |
| `status.json` | Claude / tools | `{"schema": "swpanel.status/1", "seq", "request_id", "state": "received|working|need_approval|done|error|stopped", "text", "time", "elapsed_s"}` - the panel shows `text`, reacts to `state`; `seq` replaces the spike's file-time check (1 s resolution) |
| `approve.json` | panel | `{"schema": "swpanel.approve/1", "request_id", "action": "approve_rebuild|reject|stop|update_params|run_checks", "time"}` - `approve_rebuild` is the only thing that permits a from-scratch rebuild |

## Spike results (`scripts/swpanel_spike.py`, `swpanel/vba/swpanel_spike.swb`)
| Item | Result |
|---|---|
| Building a form without C#/.swp | OK: `.swb` + `Application.VBE` builds form + 5 controls + code in 0.055 s (version notes 36-39) |
| Form survives the end of `main` | NO: destroyed when `main` returns (note 40) -> `Sleep 50 + DoEvents` loop keeps it alive |
| (b) refresh without a VBA timer | OK with the loop: 7 polls / 12 s; Win32 `SetTimer` untestable (form gone) |
| (c) Hebrew + UTF-8 JSON | OK: 3/3 Hebrew status texts (quotes, backslash, Ø, ✓) round trip status.json -> label -> seen.json exactly; latency 1.31 / 0.80 / 0.91 s. Displayed RTL-correct in the form (screenshot). ✓ shows as a box in Arial |
| (a) usable while working | PARTLY: while the loop ran, Python built a part (Ø11 extrude, volume 1900.7 mm³ = expected) and the form kept polling (4 polls in ~8 s) |
| (a) stability | **FAIL**: SolidWorks became Not Responding at 15:28:26.18 and stayed so; 0.04 s later the desktop-control tool hid SolidWorks' windows. Cause not proven |
| Typing Hebrew into the form by desktop control | not possible: the tool refuses to type into the form window ("no app frontmost"); needs the user |

## Options (for the user)
1. Fallback recommended by the plan: a small **Python window beside SolidWorks** (tkinter, always-on-top, Hebrew RTL),
   reading the selection through COM. Nothing runs inside SolidWorks' main thread, so it cannot hang it.
2. One more diagnostic of the VBA loop after a restart: minimise / restore SolidWorks by hand while it runs.
   If it hangs again -> option 1 (two failures = stop).

## Stage 0c: panel inside SolidWorks (Task Pane tab) - preferred by the user
The user wants the panel inside SolidWorks, not beside it. `scripts/swpanel_taskpane.py` adds a Task Pane tab
(`ISldWorks.CreateTaskpaneView2` + `ITaskpaneView.AddControl("Shell.Explorer.2")`) showing `swpanel/html/panel.html`
(RTL, UTF-8). All logic stays in the Python process (DOM over COM): no add-in, no C#, no registry, no VBA loop.
Results on 2019 SP3: tab + page created, page ready in 0.12 s; polls every 2 s; kept polling with SolidWorks
minimised, SolidWorks "Running". The tab lives as long as the Python process.
Pitfalls hit: late-bound `ShowView` / `DeleteView` behave as properties; MSHTML `getElementById` needs
`_FlagAsMethod("getElementById")` on a dynamic dispatch.
User's typing check (Python window, 16:00:03): 'תיצור לי קופסהה 6 סמ יל 6 סמ', 28 chars, saved exactly.
