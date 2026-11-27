"""Does the Claude add-in work when registered for this user only (no admin)? Answers it on this PC.

    python addin\\test_registration.py                   1. registry  2. COM per user  3. live load in SolidWorks
    python addin\\test_registration.py --after-restart   4. did SolidWorks load it BY ITSELF at start?

Order: build.ps1 -> register.ps1 (user scope) -> this script (SolidWorks open) -> restart SolidWorks ->
this script --after-restart. Step 4 is the deciding one: it is what a user without admin rights would get.

Proof of loading = the add-in's heartbeat file ~/.solidworks-api/addin/connected.json, written in ConnectToSW with
the SolidWorks process id. Result: ~/.solidworks-api/addin/test_result.json. Exit code 0 = add-in loaded.
"""
import json
import os
import subprocess
import sys
import time
import winreg

GUID = "{DDC81893-703C-404D-BFFD-74D6781C5148}"
PROGID = "ClaudeSw.Addin"
HOME = os.path.join(os.path.expanduser("~"), ".solidworks-api", "addin")
DLL = os.path.join(HOME, "bin", "ClaudeSwAddin.dll")
BEAT = os.path.join(HOME, "connected.json")
RESULT = os.path.join(HOME, "test_result.json")

KEYS = {
    "com_user": (winreg.HKEY_CURRENT_USER, r"Software\Classes\CLSID\%s\InprocServer32" % GUID),
    "com_machine": (winreg.HKEY_LOCAL_MACHINE, r"Software\Classes\CLSID\%s\InprocServer32" % GUID),
    "sw_list_user": (winreg.HKEY_CURRENT_USER, r"Software\SolidWorks\Addins\%s" % GUID),
    "sw_list_machine": (winreg.HKEY_LOCAL_MACHINE, r"Software\SolidWorks\Addins\%s" % GUID),
    "sw_startup": (winreg.HKEY_CURRENT_USER, r"Software\SolidWorks\AddInsStartup\%s" % GUID),
}


def say(ok, text):
    print("  [%s]  %s" % ("OK" if ok else "!!", text))


def key_exists(hive, path):
    try:
        winreg.CloseKey(winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY))
        return True
    except OSError:
        return False


def sw_pid():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower() == "sldworks.exe":
            return int(parts[1])
    return None


def beat():
    try:
        with open(BEAT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def connect_sw():
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        return win32com.client.Dispatch(
            pythoncom.GetActiveObject("SldWorks.Application").QueryInterface(pythoncom.IID_IDispatch))
    except pythoncom.com_error:
        return None


def loaded_in(sw):
    for ident in (GUID, PROGID):
        try:
            if sw.GetAddInObject(ident) is not None:
                return True
        except Exception:
            pass
    return False


def main():
    after_restart = "--after-restart" in sys.argv
    res = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "after_restart" if after_restart else "first"}
    if sys.maxsize <= 2 ** 32:
        say(False, "this Python is 32-bit: use 64-bit Python (SolidWorks is 64-bit)")
        return 2

    print("\n1. registry")
    reg = {k: key_exists(*v) for k, v in KEYS.items()}
    res["registry"] = reg
    for k, v in reg.items():
        say(v or k.endswith("machine"), "%-16s %s" % (k, "present" if v else "absent"))
    res["scope"] = "machine" if reg["sw_list_machine"] else ("user" if reg["sw_list_user"] else "none")
    if res["scope"] == "none":
        say(False, "not registered: run register.ps1 first")
        return 2
    say(os.path.exists(DLL), "DLL " + DLL)

    if not after_restart:
        print("\n2. COM activation in this process (proves Windows finds the class)")
        try:
            import win32com.client
            obj = win32com.client.Dispatch(PROGID)
            del obj
            res["com_activation"] = True
            say(True, "created %s (%s registration works for COM)" % (PROGID, res["scope"]))
        except Exception as e:
            res["com_activation"] = False
            say(False, "could not create %s: %s" % (PROGID, str(e)[:200]))

    print("\n%d. SolidWorks" % (4 if after_restart else 3))
    pid = sw_pid()
    sw = connect_sw() if pid else None
    res["sw_pid"] = pid
    if not sw:
        say(False, "SolidWorks is not running: open it and run this again")
        write(res)
        return 1
    try:
        res["sw_rev"] = sw.RevisionNumber() if callable(sw.RevisionNumber) else sw.RevisionNumber
    except Exception:
        pass
    b = beat()
    loaded_now = bool(b and b.get("pid") == pid)
    res["loaded_at_start" if after_restart else "loaded_before_test"] = loaded_now
    res["in_addin_list"] = loaded_in(sw)

    if after_restart:
        if loaded_now:
            say(True, "SolidWorks loaded the add-in BY ITSELF at start (heartbeat %s)" % b.get("time"))
        else:
            say(False, "SolidWorks did NOT load it at start (heartbeat: %s)" % (b.get("time") if b else "none"))
    elif loaded_now:
        say(True, "already loaded in this SolidWorks (heartbeat %s)" % b.get("time"))
    else:
        t0 = time.time()
        try:
            code = sw.LoadAddIn(DLL)
        except Exception as e:
            code = "error: %s" % str(e)[:200]
        time.sleep(2)
        b = beat()
        live = bool(b and b.get("pid") == pid)
        res["load_addin_code"] = code
        res["loaded_live"] = live
        # LoadAddIn: 0 loaded, 1 error, 2 already loaded, -1 not a valid add-in
        say(live, "LoadAddIn -> %s; heartbeat %s (%.1f s)" % (code, "written" if live else "NOT written",
                                                              time.time() - t0))

    write(res)
    print("\nverdict")
    ok = res.get("loaded_at_start") if after_restart else (res.get("loaded_before_test") or res.get("loaded_live"))
    if after_restart and ok and res["scope"] == "user":
        say(True, "NO ADMIN NEEDED: per-user registration is enough on SolidWorks %s" % res.get("sw_rev", "?"))
    elif after_restart and ok:
        say(True, "works with machine registration (admin). Try -Scope User on a PC without the HKLM keys.")
    elif after_restart and res["scope"] == "user":
        say(False, "SolidWorks ignores the per-user add-in list -> needs register.ps1 -Scope Machine "
                   "(admin, once). Check Tools > Add-Ins too and send ~/.solidworks-api/addin/addin.log")
    elif after_restart:
        say(False, "not loaded even with machine registration: send ~/.solidworks-api/addin/addin.log")
    elif ok:
        say(True, "the add-in runs. Now restart SolidWorks and run: python addin\\test_registration.py "
                  "--after-restart  (also look at Tools > Add-Ins: is 'Claude for SolidWorks' listed?)")
    else:
        say(False, "the add-in did not run: send ~/.solidworks-api/addin/addin.log and test_result.json")
    return 0 if ok else 1


def write(res):
    os.makedirs(HOME, exist_ok=True)
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\n  result: " + RESULT)


if __name__ == "__main__":
    sys.exit(main())
