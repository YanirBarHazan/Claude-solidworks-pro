# Fast commands and the Claude tab inside SolidWorks

Two things, usable separately:
- **Fast commands** (`scripts/swx.py` -> `scripts/swpanel_worker.py`): a warm Python process keeps the COM connection
  and the library loaded. Use them in any session for a quick look at the open document or a value change: ~0.2 s
  per call instead of ~2 s start-up per script, and no code to write (= fewer tokens).
- **The Claude tab** (`scripts/swpanel_taskpane.py`): a chat tab in the SolidWorks Task Pane. The user selects in
  SolidWorks, types in Hebrew (or any language), Claude Code runs headless in the background and answers in the tab.
No add-in, no C#, no registry, no admin rights. Tested on 2019 SP3 (2026-11-18).

## Fast commands
    python swx.py card [--full]                compact model card: globals, driven dimensions grouped by what drives
                                               them, top-level components per file, mates, patterns, named features,
                                               size, rebuild errors + CHANGES since the last card of the same file
                                               (stored in ~/.solidworks-api/cards/, keyed by path). Use it instead of
                                               re-reading the tree: a large top assembly 15,004 -> ~4,000 chars;
                                               an unchanged file says "changes: none"
    python swx.py info [--full]                active document, selection (geometry in mm, in the part AND in top
                                               assembly coordinates, component chain, the part's globals), size;
                                               --full adds raw equations + feature list
    python swx.py set NAME=VALUE ... [--selected]   globals in place (as Tools > Equations), rebuild, before/after size;
                                               --selected = in the part of the selected component (activates it)
    python swx.py fillet R [--edges selected|x|y|z] [--name N] [--var V]   radius driven by a new global
    python swx.py save
    python swx.py run script.py                ready names: sw, doc, c (sw_common), swcad, PartBuilder, T
The worker starts with the tab, or by hand: `pythonw swpanel_worker.py` (writes `~/.solidworks-api/swpanel/
worker.json`: port + token, 127.0.0.1 only). Fast mode is on only while a command runs.
Measured: `info` 0.12 s (1.9 s before fast mode), `set` + rebuild + measure 0.2 s.

## The tab
Start: `pythonw swpanel_taskpane.py watch` - waits for SolidWorks (version `SW_REQUIRE_REV`, default 2019) and adds
the tab every time SolidWorks starts; `python swpanel_taskpane.py stop` removes it. For "always there", a shortcut to
the watch command in the user's Windows Startup folder (ask the user first: it is a standing setting).
First use: the tab offers "Connect to Claude" (`claude auth login` of the Claude Code that ships with the Claude
app; once per computer).
How it works: `CreateTaskpaneView2` + `AddControl("Shell.Explorer.2")` hosts `swpanel/html/panel.html`; the Python
process drives the page over COM (all DOM access on its main thread). One persistent headless Claude Code process
(stream-json, `--resume` = one conversation until "new chat"), started with: no MCP servers, only the built-in
tools Bash/Read/Write/Edit/Glob/Grep (fixed context 39.5k -> 9.6k tokens per round), PowerShell tool disabled
(~7 s per call), effort medium, the system prompt `swpanel/PANEL_PROMPT.md`.
Look (2026-11-19): dark engineering theme (IE11-safe CSS, no variables), telemetry strip (SEL / DIR), numbers with
units highlighted, insight cards from tagged lines (`[למה]` `[ייצור]` `[ייעול]` `[שים לב]` `[הנחה]`, rendered by
`Panel.rich`), quick-prompt chips (manufacturing check, optimisation, explain the model). The prompt makes Claude
a manufacturing engineer: result first, then measured, model-specific insights (`references/manufacturing.md`).
Features: bubbles with time, live step line, Stop, New chat, save folder, file attachments, Approve / Reject cards
(`[[APPROVE]]` - required for rebuild from scratch, delete, overwrite), history restored when the tab reopens.
Files: `~/.solidworks-api/swpanel/` - settings.json, chat.log.jsonl, tokens.csv (per request, from Claude Code's
result event), taskpane.log, agent/ (Claude's working folder).

## Tests
- `swpanel_bench.py` - 5 fixed requests on a test plate, each result checked by measurement; tokens per request.
  2026-11-18: input tokens 814,766 -> 116,900 (-86%) after the tool / prompt changes, all 5 PASS.
- `swpanel_seltest.py` - selection in a skill-built SUB / TOP assembly vs SolidWorks Measure: radius 5.5 +-0.001,
  centre and axis in top coordinates, feature + chain, part globals, `set --selected` 11 -> 12 -> 11 measured from
  the top. 5/5.

## Rejected on the way (do not retry)
- VBA UserForm built from a `.swb` macro (version notes 36-41): works, but the form dies when the macro ends, and
  keeping the macro alive with a DoEvents loop hung SolidWorks 2019.
- A separate always-on-top Python window: works, but the user wants the panel inside SolidWorks.
