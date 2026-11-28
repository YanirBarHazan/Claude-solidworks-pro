"""The tab's update check: versions, what counts as newer, once a day, "not now", and the installer line."""
import json

import pytest

import updater as u


def fake(release=None, main=None):
    def fetch(url):
        if url == u.RELEASES:
            if release is None:
                raise OSError("404")
            return json.dumps(release)
        if main is None:
            raise OSError("offline")
        return main
    return fetch


def test_newer():
    assert u.newer("2.10.0", "2.9.1") and u.newer("v2.5", "2.4.9") and not u.newer("2.4.0", "2.4.0")
    assert not u.newer("garbage", "2.4.0") and not u.newer("2.3.9", "2.4")


def test_latest_prefers_a_published_release():
    info = u.latest(fake({"tag_name": "v2.5.0", "html_url": "https://x/r", "body": "notes"}, "2.6.0"))
    assert info == {"version": "2.5.0", "ref": "v2.5.0", "url": "https://x/r", "notes": "notes"}


def test_latest_skips_drafts_and_falls_back_to_main():
    assert u.latest(fake({"tag_name": "v9.0.0", "prerelease": True}, "2.5.0\n"))["ref"] == "main"
    assert u.latest(fake(None, "2.5.0"))["version"] == "2.5.0"
    assert u.latest(fake(None, None)) is None                     # offline: no nag, no error


def test_check_once_a_day_and_snooze(tmp_path):
    st = str(tmp_path / "update.json")
    f = fake({"tag_name": "v2.5.0"})
    assert u.check("2.4.0", st, f, now=1000)["version"] == "2.5.0"
    assert u.check("2.4.0", st, f, now=1000 + 3600) is None       # checked an hour ago: not again
    assert u.check("2.4.0", st, f, now=1000 + u.DAY + 1)["version"] == "2.5.0"
    u.snooze(st, now=1000 + u.DAY + 2)
    assert u.check("2.4.0", st, f, now=1000 + 2 * u.DAY) is None  # "not now" holds for a day
    assert u.check("2.5.0", st, f, now=1000 + 5 * u.DAY) is None  # up to date


def test_update_command_is_pinned_and_safe():
    c = u.update_command("v2.5.0")
    assert "SW_INSTALL_REF='v2.5.0'" in c and "/v2.5.0/install.ps1" in c
    for bad in ("v2.5'; rm -rf /", "main; calc", "$(x)"):
        with pytest.raises(ValueError):
            u.update_command(bad)
