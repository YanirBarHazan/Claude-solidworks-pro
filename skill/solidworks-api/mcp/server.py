"""SolidWorks for any AI client, over MCP (Model Context Protocol): Claude Desktop, Cursor, other agents.
The same warm worker the Claude tab uses, the same contract (contracts/worker_commands.json), and the skill's
engineering method served as a tool so a model that never saw this skill still works the same way.

    pip install mcp ezdxf            (Python 3.10+; pywin32 is already there from the installer)
    python server.py                 stdio transport - an MCP client starts it (README: "Other AI clients")

Tools: one per worker command (tests/test_contracts.py checks they match the contract), plus read_drawing
(DXF -> analysis and sheet-metal plan, no SolidWorks needed) and engineering_guide (the method and references).
"""
import json
import os
import sys
import tempfile
import time
from typing import Literal

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)

import contract  # noqa: E402
import swx  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

# the tool that serves each contract command (one each - checked by tests/test_contracts.py)
TOOL_FOR = {"ping": "solidworks_status", "card": "model_card", "info": "model_info", "set": "set_globals",
            "fillet": "add_fillet", "save": "save_document", "run": "run_script"}

INSTRUCTIONS = """You drive the user's running SolidWorks as a senior mechanical engineer would.
Before any design work call engineering_guide("index") once and follow it. The rules that matter most:
1. Never guess a missing dimension, side or material: ask. List every assumption back to the user.
2. Change an existing model in place (set_globals) - never rebuild a part to change a value.
3. Never report success without numbers: rebuild errors, size and volume against your own hand calculation.
   Say what you did not verify.
4. Every dimension you create is driven by a named global variable; name features and reference geometry.
5. Never overwrite the user's hand edits silently; start with model_card to see what changed since last time.
6. Before deleting, rebuilding or overwriting a file you did not create, stop and ask.
Units: mm, mm2, mm3, kg."""

server = MCPServer(name="solidworks", title="SolidWorks (Claude x SolidWorks)", instructions=INSTRUCTIONS,
                   version=open(os.path.join(SKILL, "VERSION"), encoding="utf-8").read().strip())
READ = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
CHANGE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def _call(cmd, args):
    """Run one contract command in the worker (started on demand); the result as text for the model."""
    if cmd != "ping" and not swx.ensure_worker():
        return ("SolidWorks worker did not start: is SolidWorks open on this PC? "
                "(the worker connects to the running instance)")
    r = swx.call(cmd, args)
    out = []
    if r.get("printed"):
        out.append(r["printed"].rstrip())
    res = r.get("result")
    if res is not None:
        out.append(res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, indent=1))
    out.append(f"[{'ok' if r.get('ok') else 'FAILED'} {r.get('s', 0)} s]")
    return "\n".join(out)


@server.tool(name="solidworks_status", annotations=READ,
             description=contract.COMMANDS["ping"]["summary"] + " Starts nothing.")
def solidworks_status() -> str:
    return _call("ping", [])


@server.tool(name="model_card", annotations=READ, description=contract.COMMANDS["card"]["summary"]
             + " Read it first for every document, and again to see what changed.")
def model_card(full: bool = False) -> str:
    return _call("card", ["--full"] if full else [])


@server.tool(name="model_info", annotations=READ, description=contract.COMMANDS["info"]["summary"])
def model_info(full: bool = False) -> str:
    return _call("info", ["--full"] if full else [])


@server.tool(name="set_globals", annotations=CHANGE, description=contract.COMMANDS["set"]["summary"]
             + " Example: {\"WALL\": 3, \"HOLE_D\": \"6.6\"}. selected=true: in the selected component's part.")
def set_globals(assignments: dict[str, float | str], selected: bool = False) -> str:
    args = [f"{k}={v}" for k, v in assignments.items()] + (["--selected"] if selected else [])
    return _call("set", args)


@server.tool(name="add_fillet", annotations=CHANGE, description=contract.COMMANDS["fillet"]["summary"])
def add_fillet(radius_mm: float, edges: Literal["selected", "x", "y", "z"] = "selected", name: str | None = None,
               variable: str | None = None) -> str:
    args = [repr(float(radius_mm)), "--edges", edges]
    if name:
        args += ["--name", name]
    if variable:
        args += ["--var", variable]
    return _call("fillet", args)


@server.tool(name="save_document", annotations=CHANGE, description=contract.COMMANDS["save"]["summary"])
def save_document() -> str:
    return _call("save", [])


@server.tool(name="run_script", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                                             openWorldHint=False),
             description=contract.COMMANDS["run"]["summary"]
             + " Pass the Python code itself. Use the library (PartBuilder links every dimension to a global; "
               "engineering_guide('library')) rather than raw API calls.")
def run_script(code: str, label: str = "script") -> str:
    d = os.path.join(os.path.expanduser("~"), ".solidworks-api", "mcp", "scripts")
    os.makedirs(d, exist_ok=True)
    safe = "".join(ch for ch in label if ch.isalnum() or ch in "-_")[:40] or "script"
    path = os.path.join(d, f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    return _call("run", [path])


@server.tool(name="read_drawing", annotations=READ,
             description="Read a 2D drawing (.dxf, or .dwg with the ODA File Converter installed): views, closed "
                         "outlines, holes, dimensions as printed, title block, bend lines with their notes, and a "
                         "sheet-metal verdict - DIRECT (the drawing alone fixes the part) or NOT_DIRECT with the "
                         "reasons. Needs no SolidWorks. thickness_mm: only when the user gave it.")
def read_drawing(path: str, thickness_mm: float | None = None, full_json: bool = False) -> str:
    import drawing_read
    a = drawing_read.analyze(path)
    plan = drawing_read.plan_sheet_metal(a, thickness=thickness_mm)
    if full_json:
        return json.dumps({"analysis": a, "plan": plan}, ensure_ascii=False, default=str)
    return drawing_read.summary(a, plan)


GUIDE = {"index": "SKILL.md", "library": "SKILL.md"}
GUIDE.update({os.path.splitext(n)[0]: os.path.join("references", n)
              for n in sorted(os.listdir(os.path.join(SKILL, "references"))) if n.endswith(".md")})


@server.tool(name="engineering_guide", annotations=READ,
             description="The engineering method of this skill and its references (pitfalls, verification, "
                         "assemblies, drawings, manufacturing, sheet metal, drawing_to_part ...). "
                         "section='index' first; it lists the others.")
def engineering_guide(section: str = "index") -> str:
    rel = GUIDE.get(section)
    if rel is None:
        return f"no section {section!r}; sections: {', '.join(GUIDE)}"
    with open(os.path.join(SKILL, rel), encoding="utf-8") as f:
        text = f.read()
    if section == "index":
        text += "\n\n## Sections of engineering_guide\n" + ", ".join(GUIDE)
    return text


if __name__ == "__main__":
    server.run("stdio")
