import os

import filesafe


def test_self_test():
    filesafe.self_test()


def test_states(tmp_path, monkeypatch):
    monkeypatch.setenv("SW_BACKUP_DIR", str(tmp_path / "bak"))
    f = tmp_path / "cad" / "a.sldprt"
    f.parent.mkdir()
    assert filesafe.status(str(f)) == "new"
    f.write_text("v1")
    assert filesafe.status(str(f)) == "unknown"
    filesafe.record(str(f))
    assert filesafe.status(str(f)) == "ours"
    f.write_text("a longer hand edit")
    assert filesafe.status(str(f)) == "changed"
    filesafe._backed.clear()
    copy = filesafe.backup(str(f))
    assert copy and os.path.exists(copy)
