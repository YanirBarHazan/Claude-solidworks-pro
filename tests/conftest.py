"""Tests that run without SolidWorks or Windows: the pure-Python parts of the skill (parameter file, hand-edit
detection, pattern planning, review log, the tab's text and markup). Anything that needs SolidWorks itself is
covered by scripts/smoke_test.py and scripts/preflight.py on a real machine.

`partsync` imports `sw_common` (pywin32 COM) at the top; the tested functions never touch it, so a stub stands in."""
import os
import sys
import types

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skill", "solidworks-api", "scripts")
sys.path.insert(0, SCRIPTS)

if "sw_common" not in sys.modules:
    stub = types.ModuleType("sw_common")
    stub.T = lambda *a, **k: None
    stub.swconst = types.SimpleNamespace(constants=types.SimpleNamespace())
    sys.modules["sw_common"] = stub
