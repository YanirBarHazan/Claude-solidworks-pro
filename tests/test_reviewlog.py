import json

import pytest

import reviewlog


def test_level_from_env_and_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SW_VERIFY_LEVEL", raising=False)
    monkeypatch.delenv("SW_OUT", raising=False)
    assert reviewlog.level() == "standard"
    (tmp_path / "project.json").write_text(json.dumps({"verify_level": "strict"}))
    assert reviewlog.level() == "strict"
    monkeypatch.setenv("SW_VERIFY_LEVEL", "quick")
    assert reviewlog.level() == "quick"
    monkeypatch.setenv("SW_VERIFY_LEVEL", "paranoid")
    with pytest.raises(ValueError):
        reviewlog.level()


def test_record_rename_read(tmp_path, monkeypatch):
    monkeypatch.setenv("SW_REVIEW_LOG", str(tmp_path / "out" / "log.jsonl"))
    monkeypatch.setenv("SW_VERIFY_LEVEL", "standard")
    reviewlog.record("part", "Part17", [("bbox", True, "120x40x8"), ("volume", False, "off by 3%")], ["mass"])
    reviewlog.record("part", "Part17", [("bbox", True, "120x40x8")])
    reviewlog.rename("Part17", "bracket.sldprt")
    rows = reviewlog.read()
    assert len(rows) == 1 and rows[0]["name"] == "bracket.sldprt"      # latest record per item
    assert rows[0]["checks"] == [["bbox", "OK", "120x40x8"]]
