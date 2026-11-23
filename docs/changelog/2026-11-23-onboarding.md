# What's new (2026-11-23, v2.3): install in one line, the tab opens by itself, start questions every time

## The problem
- Several users installed the skill and never saw the Claude tab in SolidWorks. Copying the skill (or uploading it in the Claude app) only puts files on disk; the tab needs a small watcher process, and nothing started it.
- After an update the tab stayed old: the running watcher keeps the old code in memory.
- Claude often skipped the start questions (verification level, review report, its understanding of the design). They were step 2 of the workflow, and the tab's own prompt did not mention them at all.

## What changed
- **One-line install for people who don't code:** Windows key + R, paste one line (or double-click `install.cmd` from the ZIP). It installs Python and Claude Code if missing, the skill, and the Claude tab, and prints one line per step.
- **`scripts/install_panel.py`:** installs, updates and checks the tab. It keeps a stable copy in `~/.solidworks-api/app`, stops an old tab still running, starts the new one, and adds a Windows sign-in shortcut so the tab is there every time SolidWorks opens. `--check` reports, `--remove` undoes.
- **Step 0 in SKILL.md, every session:** Claude checks the tab (`install_panel.py --check`) and fixes it if needed, so installing the skill any way (copy, Claude app upload) ends with a working tab.
- **Start questions are now the first reply**, in Claude Code and in the tab: verification level, review report, restated understanding and assumed values, each with a recommended default. Answers are saved to `project.json` and not asked again in the same project.
- The tab also finds Claude Code from its native installer (`~/.local/bin`).
- `VERSION` file in the skill (2.3.0).

## Not tested yet
The installer and `install_panel.py` were written without a Windows machine. First field runs: please report anything that prints `[!!]` or `FAIL`.

Feedback: [Yanir Bar Hazan on LinkedIn](https://www.linkedin.com/in/yanir-hazan)

[Back to the changelog](README.md)
