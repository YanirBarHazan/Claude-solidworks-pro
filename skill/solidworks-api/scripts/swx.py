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
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract  # noqa: E402

PANEL = os.path.join(os.path.expanduser("~"), ".solidworks-api", "swpanel")
BUSY_WAIT = 90          # seconds a busy worker may keep a caller waiting before it counts as not running
START_WAIT = 60         # a cold worker connects to SolidWorks and loads the type library: often more than 25 s


def pid_alive(pid):
    """False only when the process is surely gone (worker.json left behind by a stopped worker): then a refused
    connection is not a busy worker, and waiting BUSY_WAIT for it only delays starting a new one."""
    if not pid:
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return not (k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259)   # 259 = STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def connect(port, wait=BUSY_WAIT):
    """The worker runs one command at a time; with several agents its queue of waiting connections can be full
    for a while. A refused connection is retried for `wait` seconds before the worker counts as not running."""
    if not port:
        return None
    t0, delay = time.time(), 0.2
    while True:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=5)
        except (ConnectionRefusedError, socket.timeout, TimeoutError):
            if time.time() - t0 >= wait:
                return None
            time.sleep(delay)
            delay = min(delay * 2, 3.0)
        except OSError:
            return None


def call(cmd, args):
    try:
        contract.check(cmd, args)
    except contract.ContractError as e:
        return {"ok": False, "result": str(e)}
    try:
        with open(os.path.join(PANEL, "worker.json")) as f:
            w = json.load(f)
    except (OSError, ValueError):
        return {"ok": False, "result": "worker not running: the Claude tab starts it (or run swpanel_worker.py)"}
    s = connect(w.get("port"), BUSY_WAIT if pid_alive(w.get("pid")) else 0)
    if s is None:
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


def ensure_worker(timeout=START_WAIT):
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
