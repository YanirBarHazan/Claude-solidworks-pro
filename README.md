# Claude × SolidWorks

### Describe the part. Claude builds it in SolidWorks, measures it, and proves it works.

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![SolidWorks 2019 | 2025](https://img.shields.io/badge/SolidWorks-2019%20%7C%202025-red)
![Claude Code skill](https://img.shields.io/badge/Claude%20Code-skill-orange)
![Hebrew + English](https://img.shields.io/badge/language-Hebrew%20%7C%20English-blue)

[עברית](README.he.md) · [Getting started](docs/getting-started.md) · [How it works](docs/how-it-works.md) · [Changelog](docs/changelog/README.md) · [Example project](examples/desk-agent/README.md)

<p align="center">
  <a href="assets/demo/demo.mp4"><img src="assets/demo/demo.gif" width="720" alt="Claude building a parametric folding phone stand live in SolidWorks from the Claude tab: base, back plate, hinge pin, mated assembly, then a live change of angle, width and fillets"></a>
  <br><sub>Claude building a folding phone stand (3 parts + mated assembly) from the Claude tab inside SolidWorks, then changing it in place (thinking time cut, sped up). <a href="assets/demo/demo.mp4">Full video</a></sub>
</p>

<p align="center">
  <a href="https://www.linkedin.com/in/yanir-hazan"><img src="https://img.shields.io/badge/Tried_it%3F_Tell_me_how_it_went-LinkedIn-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white" alt="Feedback on LinkedIn"></a>
  <a href="https://www.linkedin.com/in/yanir-hazan"><img src="https://img.shields.io/badge/Custom_version_for_your_company-Let%27s_talk-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white" alt="Custom version for your company"></a>
</p>

A **skill for [Claude Code](https://claude.com/claude-code)** that turns Claude into a SolidWorks engineer on your own PC. You say what you need in plain words, Hebrew or English. Claude writes and runs the code, builds real parametric parts and assemblies, **checks every dimension and every fit with numbers, and only then says it's done.** No copying error messages back and forth.

## Why engineers use it

- **Nothing is "done" until it's measured.** Bounding box, volume, mass, interference and a save, close, reopen test with zero errors. A step that can't show its numbers isn't finished.
- **Models a human can keep working on.** Every dimension is a named global in *Tools → Equations*. Change one number and the whole assembly follows. Edit by hand and Claude picks up your change instead of overwriting it.
- **Claude inside SolidWorks.** A chat tab in the Task Pane: select a face or a component, type what you want, watch it happen. No add-in, no C#, no admin rights.
- **Built for real, big assemblies.** Tested on assemblies of more than 2,000 components on SolidWorks 2019: a design change plus a full re-check in minutes, not hours. COM calls up to 100x faster than plain scripting.
- **From idea to factory floor.** Production drawings with BOM and balloons, PDF / DXF, print-ready STL and sliced Bambu Studio projects.

## Claude inside SolidWorks

<p align="center">
  <img src="assets/images/solidworks-panel.png" width="820" alt="The Claude tab docked in the SolidWorks Task Pane next to a parametric flange: plan, approve card, and a verified result">
  <br><sub>The Claude tab in the Task Pane: describe, approve, and get a verified result. Hebrew or English. (Panel shown with a sample conversation.)</sub>
</p>

## What it can do

| | |
|---|---|
| **Parametric parts** | Every dimension linked to a named global, editable by hand. Hole Wizard holes, patterns, mirrors, SolidWorks materials. |
| **Verification** | Size and volume against hand calculations, an edit test, reopen with zero rebuild errors, a one-page review report. |
| **Assemblies** | Skeleton-driven layouts, interference checks with a list of *designed* overlaps, moving parts swept through every position. |
| **Design for change** | Client values live in one place. Update in place in seconds, never rebuild the files. |
| **Engineering checks** | Snap-fit strain, detent torque, tipping stability, tolerance stacks. |
| **Drawings** | Standard views and scale, model dimensions, section views, tolerances, BOM, ISO or company title block. |
| **3D printing** | Print orientation, overhang and support analysis, sliced projects with time and filament per plate. |

## Built with it: the desk agent

<p align="center">
  <img src="assets/images/desk-agent-photo.webp" width="420" alt="The finished desk agent: a 5-inch screen in a 3D-printed enclosure designed by Claude in SolidWorks">
</p>

A desk display with a touch screen, a presence radar, a light bar and a speaker, designed from the first sketch to the sliced print files. Test coupons, hidden snap fits, an adjustable kickstand checked at six angles, a production drawing, and an honest list of what went wrong. [See the full project →](examples/desk-agent/README.md)

<p align="center">
  <img src="assets/images/exploded-back.png" width="32%" alt="Exploded view from the back">
  <img src="assets/images/drawing-hinge-block.png" width="32%" alt="Production drawing made by the skill">
  <img src="assets/images/coupon-c-hinge.png" width="32%" alt="Hinge test coupon">
</p>

## How it works

```mermaid
flowchart LR
    U([You: plain-language request]) --> C[Claude Code + this skill]
    C -->|writes and runs Python| P[swcad.py library]
    P -->|COM API, pywin32| SW[(SolidWorks)]
    SW -->|geometry, errors, volumes| V{Verify}
    V -->|fail: fix and retry| C
    V -->|pass| O[Parts, assembly, drawings, STL, sliced 3MF]
    O --> U
```

SolidWorks' API is huge and full of traps. The skill packages every trap that broke a real build, with its fix, a library that handles them, and a method: ask for missing measurements first, print test coupons before the big part, verify everything. [More →](docs/how-it-works.md)

## Quick start (5 minutes, no code)

**You need:** a Windows PC with SolidWorks (2019 to 2025, Student Edition works) and a Claude account. Everything else is installed for you.

1. Press **Windows key + R**, paste this line, press **Enter**:
   ```
   powershell -ExecutionPolicy Bypass -NoExit -c "irm https://raw.githubusercontent.com/YanirBarHazan/Claude-solidworks-pro/main/install.ps1 | iex"
   ```
   *Or:* **Code → Download ZIP** on this page, extract it, double-click **`install.cmd`**.
2. Wait for **Done** (it installs Python and Claude Code if missing, the skill, and the Claude tab).
3. Open SolidWorks. The **Claude** tab appears in the Task Pane on the right. First time only: click **connect to Claude**.
4. Type what you need, for example:
   > *Design a wall bracket for a 40 mm pipe, two M5 screws, printable in PLA without supports.*

   Claude first asks a few short start questions (how much to verify, a review report, its understanding of your design). Then it builds.

Using Claude Code outside SolidWorks works too: the skill is in `%USERPROFILE%\.claude\skills\solidworks-api`, and on first use Claude checks that the tab is installed and fixes it if not. Step by step with pictures: [docs/getting-started.md](docs/getting-started.md).

## Updating

Run the same line (or `install.cmd`) again. It stops the old tab, installs the latest version (the old one goes to `~\.solidworks-api\backups\`, chats and settings are kept) and starts the new tab. Restart SolidWorks if it was open.

## Repository layout

```
skill/solidworks-api/   the skill itself (SKILL.md, scripts, references)
dist/                   the skill packed for upload
docs/                   guides, architecture, troubleshooting, changelog (docs/he: Hebrew)
examples/               real projects: desk agent, large structure, drawings, skeleton grid
assets/                 images and the demo video
```

## Latest updates

- **2026-11-23, v2.3: Install in one line.** The installer sets up Python, Claude Code, the skill and the Claude tab; the tab opens with SolidWorks every time; Claude asks the start questions first. [Details](docs/changelog/2026-11-23-onboarding.md)
- **2026-11-18, v2.2: Claude inside SolidWorks.** A chat tab in the Task Pane, fast mode with COM calls up to 100x faster, and design for change: a span edit plus a full re-check in 5 s. [Details](docs/changelog/2026-11-18-v2.2.md)
- **2026-11-18: Drawings in one call.** Views, model dimensions, sections, BOM and balloons, PDF / DXF, a light start check and a one-page review report. [Details](docs/changelog/2026-11-18-drawings.md)

[Full changelog →](docs/changelog/README.md)

## License

[MIT](LICENSE). SolidWorks is a trademark of Dassault Systèmes. This project is not affiliated with Dassault Systèmes or Anthropic.

## Feedback and custom versions

Ideas, bugs, a story of what you built, or a company that wants this tuned to its own standards: **[Yanir Bar Hazan on LinkedIn](https://www.linkedin.com/in/yanir-hazan)**.
