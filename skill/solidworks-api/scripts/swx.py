"""Client of the warm SolidWorks worker (swpanel_worker.py). Standard library only: starts in ~50 ms.

    python swx.py info
    python swx.py set BOX_H=10 HOLE_D=12 [--selected]
    python swx.py save
    python swx.py run my_script.py
Prints JSON; exit code 1 when the command failed.
"""
import json
import os
import socket
import sys

PANEL = os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel")


def call(cmd, args):
    try:
        with open(os.path.join(PANEL, "worker.json")) as f:
            w = json.load(f)
        s = socket.create_connection(("127.0.0.1", w["port"]), timeout=5)
    except (OSError, ValueError, KeyError):
        return {"ok": False, "result": "worker not running: the Claude tab starts it (or run swpanel_worker.py)"}
    with s:
        s.settimeout(None)
        if cmd == "run" and args:
            args = [os.path.abspath(args[0])] + args[1:]
        s.sendall((json.dumps({"token": w["token"], "cmd": cmd, "args": args}) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


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
