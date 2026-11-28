"""Client of the warm SolidWorks worker (swpanel_worker.py). Standard library only: starts in ~50 ms.

    python swx.py card [--full] [--doc PATH]
    python swx.py info [--full] [--doc PATH]
    python swx.py set BOX_H=10 HOLE_D=12 [--selected] [--doc PATH]
    python swx.py fillet 2 [--edges selected|x|y|z] [--name N] [--var V]
    python swx.py save [--doc PATH]
    python swx.py snapshot [--doc PATH] [--out X.png] [--view iso|front|top|right]
    python swx.py run my_script.py [--background]
    python swx.py ping
--doc PATH works on that document without making it the active one (background agents).
The commands and their arguments: contracts/worker_commands.json (checked here before sending).
Prints JSON; exit code 1 when the command failed.
"""
import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract  # noqa: E402

PANEL = os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel")


def call(cmd, args):
    try:
        contract.check(cmd, args)
    except contract.ContractError as e:
        return {"ok": False, "result": str(e)}
    try:
        with open(os.path.join(PANEL, "worker.json")) as f:
            w = json.load(f)
        s = socket.create_connection(("127.0.0.1", w["port"]), timeout=5)
    except (OSError, ValueError, KeyError):
        return {"ok": False, "result": "worker not running: the Claude tab starts it (or run swpanel_worker.py)"}
    with s:
        s.settimeout(None)
        if cmd == "run":                 # the worker runs in another folder: send the script's full path
            args = [a if a.startswith("--") else os.path.abspath(a) for a in args]
        if "--doc" in args[:-1]:
            i = args.index("--doc")
            args = args[:i + 1] + [os.path.abspath(args[i + 1])] + args[i + 2:]
        s.sendall((json.dumps({"token": w["token"], "cmd": cmd, "args": args}) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


def ensure_worker(timeout=25):
    """Start the warm worker when none answers (the Claude tab normally starts it). -> True when it answers."""
    if call("ping", []).get("ok"):
        return True
    import subprocess
    import time
    here = os.path.dirname(os.path.abspath(__file__))
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([pyw if os.path.exists(pyw) else sys.executable, os.path.join(here, "swpanel_worker.py")],
                     creationflags=flags)
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.5)
        if call("ping", []).get("ok"):
            return True
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    r = call(sys.argv[1], sys.argv[2:])
    sys.stdout.reconfigure(encoding="utf-8")
    if r.get("printed"):
        print(r["printed"].rstrip())
    if r.get("result") is not None or not r.get("ok"):
        print(json.dumps(r.get("result"), ensure_ascii=False, separators=(",", ":")) if not isinstance(r.get("result"), str)
              else r["result"])
    print(f"[{'ok' if r.get('ok') else 'FAILED'} {r.get('s', 0)} s]")
    sys.exit(0 if r.get("ok") else 1)
