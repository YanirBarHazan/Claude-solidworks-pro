"""One contract (contracts/worker_commands.json), four places that must agree with it: the worker's dispatch,
the swx.py client, the MCP server and the tab's prompt. Plus the contract's own argument checks."""
import ast
import asyncio
import os
import re
import sys

import pytest

import contract

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(contract.__file__)))
SCRIPTS = os.path.join(SKILL, "scripts")


def src(rel):
    return open(os.path.join(SKILL, rel), encoding="utf-8").read()


def test_contract_shape():
    assert contract.CONTRACT["contract"] == "worker_commands"
    for name, spec in contract.COMMANDS.items():
        assert spec["summary"] and isinstance(spec["changes_model"], bool), name
        for a in spec["args"]:
            assert a["kind"] in ("flag", "option", "number", "path", "list"), (name, a)


def test_worker_has_a_method_for_every_command_and_dispatches_only_through_the_contract():
    tree = ast.parse(src("scripts/swpanel_worker.py"))
    worker = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Worker")
    methods = {f.name for f in worker.body if isinstance(f, ast.FunctionDef)}
    for name in contract.COMMANDS:
        assert name == "ping" or name in methods, f"contract command {name} has no Worker.{name}"
    s = src("scripts/swpanel_worker.py")
    assert "contract.check(cmd, args)" in s
    assert s.index("contract.check(cmd, args)") < s.index("getattr(w, cmd)(args)")


def test_swx_documents_every_command():
    doc = src("scripts/swx.py").split('"""')[1]
    for name in contract.COMMANDS:
        assert re.search(rf"swx\.py {name}\b", doc), f"swx.py docstring misses {name}"


def test_panel_prompt_lists_every_user_command():
    p = src("swpanel/PANEL_PROMPT.md")
    for name in contract.COMMANDS:
        if name != "ping":
            assert re.search(rf'"\{{SWX\}}" {name}\b', p), f"PANEL_PROMPT.md misses the {name} command"


@pytest.mark.parametrize("cmd,args", [
    ("set", ["A=1", "B=2.5", "--selected"]), ("fillet", ["2", "--edges", "x", "--name", "F1", "--var", "F1_R"]),
    ("card", []), ("card", ["--full"]), ("info", ["--full"]), ("save", []), ("run", ["x.py"]), ("ping", [])])
def test_contract_accepts(cmd, args):
    contract.check(cmd, args)


@pytest.mark.parametrize("cmd,args", [
    ("active", []), ("__init__", []), ("set", []), ("set", ["A"]), ("fillet", ["x"]), ("fillet", []),
    ("fillet", ["2", "--edges", "q"]), ("fillet", ["2", "--name"]), ("save", ["x"]), ("card", ["--bogus"]),
    ("run", [])])
def test_contract_rejects(cmd, args):
    with pytest.raises(contract.ContractError):
        contract.check(cmd, args)


def test_swx_refuses_before_sending():
    import swx
    r = swx.call("active", [])
    assert r["ok"] is False and "unknown command" in r["result"]


mcp = pytest.importorskip("mcp")


def test_mcp_server_has_one_tool_per_command():
    sys.path.insert(0, os.path.join(SKILL, "mcp"))
    import server
    tools = {t.name for t in asyncio.run(server.server.list_tools())}
    assert set(server.TOOL_FOR) == set(contract.COMMANDS)
    assert set(server.TOOL_FOR.values()) <= tools
    assert {"read_drawing", "engineering_guide"} <= tools


def test_mcp_stdio_round_trip(tmp_path):
    """Start the server as a client would (stdio), list its tools and read a drawing through it."""
    ezdxf = pytest.importorskip("ezdxf")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    doc.modelspace().add_lwpolyline([(0, 0), (40, 0), (40, 20), (0, 20)], close=True)
    doc.modelspace().add_text("THK 2", dxfattribs={"insert": (0, -5)})
    f = tmp_path / "plate.dxf"
    doc.saveas(f)

    async def go():
        params = StdioServerParameters(command=sys.executable, args=[os.path.join(SKILL, "mcp", "server.py")])
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                res = await s.call_tool("read_drawing", {"path": str(f)})
                return names, res.content[0].text
    names, text = asyncio.run(asyncio.wait_for(go(), 60))
    assert "model_card" in names and "VERDICT DIRECT" in text and "40.0 x 20.0" in text
