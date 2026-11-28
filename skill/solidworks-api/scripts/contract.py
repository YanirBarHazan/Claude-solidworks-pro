"""The worker's command contract (contracts/worker_commands.json): load it and check a command line against it.
Standard library only - used by the worker, the swx.py client and the MCP server.

    COMMANDS                      {name: spec} from the contract
    check(cmd, args) -> None      raises ContractError when the command or its arguments do not fit the contract
"""
import json
import os
import re

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "worker_commands.json")

with open(PATH, encoding="utf-8") as _f:
    CONTRACT = json.load(_f)
COMMANDS = CONTRACT["commands"]
_ASSIGN = re.compile(r"^[A-Za-z_][\w.]*=.+$")


class ContractError(ValueError):
    """A command or argument the contract does not allow."""


def check(cmd, args):
    if cmd not in COMMANDS:
        raise ContractError(f"unknown command {cmd!r}; commands: {', '.join(COMMANDS)}")
    specs = COMMANDS[cmd]["args"]
    flags = {s["name"] for s in specs if s["kind"] == "flag"}
    options = {s["name"]: s for s in specs if s["kind"] == "option"}
    positional = [s for s in specs if s["kind"] not in ("flag", "option")]
    rest, i = [], 0
    args = list(args or [])
    while i < len(args):
        a = args[i]
        if a in flags:
            i += 1
        elif a in options:
            if i + 1 >= len(args):
                raise ContractError(f"{cmd}: {a} needs a value")
            ch = options[a].get("choices")
            if ch and args[i + 1] not in ch:
                raise ContractError(f"{cmd}: {a} must be one of {ch}, not {args[i + 1]!r}")
            i += 2
        elif a.startswith("--"):
            raise ContractError(f"{cmd}: unknown option {a}")
        else:
            rest.append(a)
            i += 1
    if not positional and rest:
        raise ContractError(f"{cmd} takes no arguments, got {rest}")
    for s in positional:
        if s["kind"] == "list":
            if s.get("required") and not rest:
                raise ContractError(f"{cmd}: needs {s['pattern']} ...")
            bad = [a for a in rest if not _ASSIGN.match(a)]
            if bad:
                raise ContractError(f"{cmd}: expected {s['pattern']}, got {bad}")
            rest = []
        else:
            if not rest:
                if s.get("required"):
                    raise ContractError(f"{cmd}: missing {s['name']}")
                continue
            v = rest.pop(0)
            if s["kind"] == "number":
                try:
                    float(v)
                except ValueError:
                    raise ContractError(f"{cmd}: {s['name']} must be a number, not {v!r}") from None
    if rest:
        raise ContractError(f"{cmd}: unexpected arguments {rest}")
