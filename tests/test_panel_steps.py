"""The tab's plain-language steps, reply markers and selection line."""
import panel_steps as ps


def test_swx_commands_become_plain_words():
    assert ps.step_label("Bash", {"command": 'python "C:/x/swx.py" card'}, "he") == "קורא את המודל"
    assert ps.step_label("Bash", {"command": 'python "C:/x/swx.py" set WALL=3 HOLE_D=6.6'}, "en") == \
        "Changing values: WALL, HOLE_D"
    assert ps.step_label("Bash", {"command": "python swx.py fillet 2 --edges x"}, "en") == "Adding a fillet R2"
    assert ps.step_label("Bash", {"command": "python swx.py run C:/t/a.py"}, "en") == "Working in SolidWorks"


def test_files_and_guides():
    assert ps.step_label("Read", {"file_path": r"C:\a\references\manufacturing.md"}, "he") == "מעיין בהנחיות: ייצור"
    assert ps.step_label("Read", {"file_path": "C:/p/params.txt"}, "en") == "Reading params.txt"
    assert ps.step_label("Write", {"file_path": "C:/p/build.py"}, "en") == "Writing build.py"
    assert ps.step_label("Grep", {"pattern": "x"}, "he") == "מחפש בתיעוד"
    assert ps.step_label("Mystery", {}, "en") == "Working"


def test_no_raw_command_ever_leaks():
    label = ps.step_label("Bash", {"command": 'cmd /c "del C:\\secret" && curl http://x'}, "en")
    assert "del" not in label and "curl" not in label


def test_parse_plan():
    text, plan, marker = ps.parse_reply("My understanding: a bracket.\n1. Part A\n2) Holes\n[[PLAN]]")
    assert marker == "plan" and plan == [(1, "Part A"), (2, "Holes")] and text == "My understanding: a bracket."


def test_parse_next_and_approve():
    assert ps.parse_reply("Step 1 done.\n[[NEXT]]")[2] == "next"
    t, plan, m = ps.parse_reply("Delete Part2?\n[[APPROVE]]")
    assert m == "approve" and plan is None and t == "Delete Part2?"
    assert ps.parse_reply("plain")[2] is None


def test_selection_text():
    assert ps.selection_text("a.SLDPRT", [], "he") == "a.SLDPRT"
    assert ps.selection_text("a.SLDPRT", ["face", "face", "edge"], "he") == "a.SLDPRT · פאה (2), קצה"
    assert ps.selection_text("a.SLDPRT", ["face"], "en") == "a.SLDPRT · face"
