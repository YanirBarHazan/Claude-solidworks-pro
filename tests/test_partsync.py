import partsync


def snap(features, globals_, equations=()):
    return {"features": features, "globals": globals_, "equations": list(equations), "linked_file": ""}


def test_compare_finds_hand_edits():
    old = snap([["Base", "Extrusion", False], ["Hole", "Cut", False]], {"W": 100.0})
    now = snap([["Base", "Extrusion", False], ["Fillet9", "Fillet", False]], {"W": 120.0}, ["W = 120"])
    rep = partsync.compare(old, now)
    assert rep["drift"]
    assert rep["added_features"] == [["Fillet9", "Fillet"]] and rep["deleted_features"] == ["Hole"]
    assert rep["globals_changed"] == {"W": [100.0, 120.0]}
    assert not partsync.additive_only(rep)        # something was deleted


def test_no_drift():
    s = snap([["Base", "Extrusion", False]], {"W": 100.0})
    rep = partsync.compare(s, s)
    assert not rep["drift"] and partsync.additive_only(rep)


def test_classify_values_three_way():
    changes = {"PULL": [10.0, 12.0], "SAME": [10.0, 12.0], "BOTH": [10.0, 12.0], "GONE": [1.0, 2.0]}
    params = {"PULL": 10.0, "SAME": 12.0, "BOTH": 11.0}
    pull, same, conflict = partsync.classify_values(changes, params)
    assert pull == {"PULL": (10.0, 12.0)} and same == ["SAME"]
    assert set(conflict) == {"BOTH", "GONE"}
