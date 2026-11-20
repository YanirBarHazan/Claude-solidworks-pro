"""Verification level of the project + a log of every check that ran (and every check that was skipped), so the
review report (`review.py`) can tell the engineer exactly what was proven and what was not.

Level (asked at the start of every project, `references/dialogue.md` 0):
    quick     rebuild errors, one body, bounding box. Fast iterations, early concepts.
    standard  + volume against a hand calculation, every sketch fully defined, the edit test when one is given.
    strict    + an edit test is REQUIRED for every part, mass against volume x density when a material is set.
Set it with env SW_VERIFY_LEVEL or in <project>/project.json {"verify_level": "standard"}; default standard.

Log: <project>/out/review_log.jsonl (env SW_REVIEW_LOG overrides). One JSON line per checked item:
    {"time", "kind": "part" / "assembly" / "drawing" / ..., "name", "level", "checks": [[check, "OK"/"FAIL", detail]],
     "skipped": [check, ...]}"""
import json
import os
import time

LEVELS = ("quick", "standard", "strict")


def project_dir():
    out = os.environ.get("SW_OUT")
    return os.path.dirname(os.path.abspath(out)) if out else os.getcwd()


def level():
    lv = os.environ.get("SW_VERIFY_LEVEL", "").strip().lower()
    if not lv:
        try:
            lv = json.load(open(os.path.join(project_dir(), "project.json"), encoding="utf-8")).get("verify_level", "")
        except (OSError, ValueError):
            lv = ""
    lv = lv or "standard"
    if lv not in LEVELS:
        raise ValueError(f"verify level {lv!r}: use one of {LEVELS}")
    return lv


def log_path():
    return os.environ.get("SW_REVIEW_LOG") or os.path.join(project_dir(), "out", "review_log.jsonl")


def record(kind, name, checks, skipped=(), lv=None):
    """checks: [(check, ok_bool, detail)]. Never raises: the log must not break a build."""
    try:
        p = log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        row = dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), kind=kind, name=name, level=lv or level(),
                   checks=[[c, "OK" if ok else "FAIL", str(d)[:160]] for c, ok, d in checks], skipped=list(skipped))
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def rename(old, new):
    """A part verified before its first save is logged under its untitled name (Part17): give it the file name."""
    try:
        p = log_path()
        out = []
        for line in open(p, encoding="utf-8").read().splitlines():
            r = json.loads(line)
            if r.get("name") == old:
                r["name"] = new
            out.append(json.dumps(r, ensure_ascii=False))
        open(p, "w", encoding="utf-8").write("\n".join(out) + "\n")
    except (OSError, ValueError):
        pass


def read(path=None):
    """Latest record per (kind, name)."""
    rows = {}
    try:
        for line in open(path or log_path(), encoding="utf-8"):
            r = json.loads(line)
            rows[(r["kind"], r["name"])] = r
    except OSError:
        pass
    return list(rows.values())
