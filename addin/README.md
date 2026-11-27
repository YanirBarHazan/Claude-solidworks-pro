# Optional SolidWorks add-in (stage 1 skeleton)

The Claude tab works **without** this add-in. The add-in is a thin, optional extra that gives:

- a **Claude** button in the Tools menu, a toolbar and a "Claude" tab in the CommandManager (starts the tab watcher)
- the tab watcher started when SolidWorks starts (heartbeat file proves it loaded)
- selection / active-document events written to `~/.solidworks-api/swpanel/events/sel.json`
  (for instant reaction instead of the 2 s poll; the Python tab does not read it yet)

All logic stays in Python. The add-in never touches the model, and every handler is wrapped so an error is logged
(`~/.solidworks-api/addin/addin.log`), never thrown into SolidWorks.

## Status

Not yet run on Windows. Checked so far: compiles as C# 5 against stub interop types. The real build, registration
and loading need the steps below on a PC with SolidWorks.

## Steps (Windows, SolidWorks installed, the Claude tab installed with install.ps1)

```powershell
powershell -ExecutionPolicy Bypass -File addin\build.ps1        # csc.exe from Windows, no Visual Studio
powershell -ExecutionPolicy Bypass -File addin\register.ps1     # this user only, NO admin
# open SolidWorks, then:
python addin\test_registration.py                               # registry, COM per user, live load
# restart SolidWorks, then:
python addin\test_registration.py --after-restart               # the deciding test: loaded by itself?
```

If `--after-restart` says SolidWorks ignores the per-user list, register for all users once (admin):
`register.ps1 -Unregister` then, in an elevated PowerShell, `register.ps1 -Scope Machine`.

Remove: `register.ps1 -Unregister` (with the same `-Scope`).

## The open question this answers

COM classes can be registered per user (`HKCU\Software\Classes`), so Windows can load the DLL without admin.
What is not known is whether SolidWorks reads its add-in list from `HKCU\Software\SolidWorks\Addins` as well as
the documented `HKLM\SOFTWARE\SolidWorks\Addins`. If yes, the add-in installs with no admin rights.
