"""One-page review report for the engineer: what was built, what was PROVEN (with the numbers), what was NOT
checked, the assumptions still open. Built from the review log (`reviewlog.py`) and the project card.

    python review.py [project folder] [--lang he|en]     -> <project>/out/review.html + review.pdf

The point: the engineer's review takes minutes, and nothing that was skipped is hidden. PDF through Edge / Chrome
headless (Windows); without a browser the HTML stays."""
import glob
import html
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reviewlog  # noqa: E402

T = {
    "en": dict(title="Review report", level="Verification level", items="Items checked", ok="checks passed",
               fail="FAILED", skipped="skipped by the level", item="Item", kind="Kind", result="Result",
               details="Failures", not_checked="Not checked", assumptions="Assumptions to confirm",
               open_q="Open questions", none="none", always="Always: look at drawings for overlapping text "
               "and crowded views - numbers cannot see it.", decision="Decision", question="Question",
               blocks="Blocks", rec="Recommendation", date="Date"),
    "he": dict(title="דוח סקירה", level="רמת אימות", items="פריטים שנבדקו", ok="בדיקות עברו", fail="נכשלו",
               skipped="דולגו לפי הרמה", item="פריט", kind="סוג", result="תוצאה", details="כשלים",
               not_checked="מה לא נבדק", assumptions="הנחות לאישור", open_q="שאלות פתוחות", none="אין",
               always="תמיד: להסתכל על השרטוטים - טקסט חופף ומבטים צפופים לא נראים במספרים.",
               decision="החלטה", question="שאלה", blocks="חוסם", rec="המלצה", date="תאריך"),
}


def card_tables(path):
    """{section title: [rows as lists]} from the markdown tables of PROJECT_CARD.md, + the card's title."""
    out, title, sec = {}, "", None
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return "", {}
    for line in lines:
        if line.startswith("# "):
            title = line[2:].replace("Project card -", "").strip()
        elif line.startswith("## "):
            sec = re.sub(r"^\d+\.\s*", "", line[3:]).strip()
        elif sec and line.startswith("|") and not re.match(r"^\|[\s\-|]+\|$", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if any(cells):
                out.setdefault(sec, []).append(cells)
    return title, out


def browser():
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            return p
    return None


def build(project=None, lang="en"):
    project = os.path.abspath(project or reviewlog.project_dir())
    L = T.get(lang, T["en"])
    log = os.environ.get("SW_REVIEW_LOG") or os.path.join(project, "out", "review_log.jsonl")
    rows = reviewlog.read(log)
    try:
        lv = json.load(open(os.path.join(project, "project.json"), encoding="utf-8")).get("verify_level", "standard")
    except (OSError, ValueError):
        lv = rows[-1]["level"] if rows else "standard"
    title, tables = card_tables(os.path.join(project, "PROJECT_CARD.md"))
    n_ok = sum(c[1] == "OK" for r in rows for c in r["checks"])
    n_fail = sum(c[1] == "FAIL" for r in rows for c in r["checks"])
    skipped = sorted({s for r in rows for s in r["skipped"]})
    e = html.escape
    body = []
    for r in rows:
        oks = sum(c[1] == "OK" for c in r["checks"])
        fails = [c for c in r["checks"] if c[1] == "FAIL"]
        res = f"{oks} OK" + (f", <b class='f'>{len(fails)} FAIL</b>" if fails else "")
        sk = ", ".join(e(s) for s in r["skipped"]) or "-"
        det = "<br>".join(f"{e(c[0])}: {e(c[2])}" for c in fails) or "-"
        body.append(f"<tr><td>{e(r['name'])}</td><td>{e(r['kind'])}</td><td>{res}</td><td>{sk}</td><td>{det}</td></tr>")
    def section(prefix):
        return next((rows_ for t, rows_ in tables.items() if t.lower().startswith(prefix)), [])

    def strip_no(row):                                       # drop the "#" column
        return row[1:] if row and re.fullmatch(r"\d+", row[0]) else row
    dec = [strip_no(d) for d in section("decisions")[1:]]
    assumed = [[d[0], d[1] if len(d) > 1 else "", d[2] if len(d) > 2 else ""] for d in dec
               if any("ASSUMED" in c for c in d)]
    openq = [strip_no(q) for q in section("open questions")[1:] if any(q)] + \
        [[d[0], "", ""] for d in dec if any(c.strip() == "OPEN" for c in d)]

    def lst(items, cols):
        if not items:
            return f"<p>{L['none']}</p>"
        return ("<table><tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
                + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in it[:len(cols)]) + "</tr>" for it in items)
                + "</table>")
    rtl = lang == "he"
    page = f"""<!doctype html><html lang="{lang}" dir="{'rtl' if rtl else 'ltr'}"><head><meta charset="utf-8">
<title>{L['title']}</title><style>
@page {{ size: A4; margin: 12mm; }}
body {{ font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; color: #1d2329; }}
h1 {{ font-size: 17pt; margin: 0; color: #0f3d5c; }} h2 {{ font-size: 12pt; color: #0f3d5c; margin: 5mm 0 1.5mm;
border-bottom: 1.5px solid #0f3d5c; }}
.sum {{ display: flex; gap: 4mm; margin: 3mm 0; }} .sum div {{ border: 1px solid #c9d3db; border-radius: 2mm;
padding: 2mm 3mm; background: #f6f8fa; }} .sum b {{ font-size: 14pt; display: block; }}
table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid #c9d3db; padding: 1mm 1.5mm;
vertical-align: top; text-align: {'right' if rtl else 'left'}; }} th {{ background: #e8eef3; }}
.f {{ color: #b42318; }} .muted {{ color: #5b6670; }}
</style></head><body>
<h1>{L['title']}{(' - ' + e(title)) if title else ''}</h1>
<div class="muted">{L['date']} {time.strftime('%d/%m/%Y %H:%M')} · {L['level']}: <b>{e(lv)}</b></div>
<div class="sum"><div><b>{len(rows)}</b>{L['items']}</div><div><b>{n_ok}</b>{L['ok']}</div>
<div><b class="{'f' if n_fail else ''}">{n_fail}</b>{L['fail']}</div><div><b>{len(skipped)}</b>{L['skipped']}</div></div>
<table><tr><th>{L['item']}</th><th>{L['kind']}</th><th>{L['result']}</th><th>{L['skipped']}</th><th>{L['details']}</th></tr>
{''.join(body)}</table>
<h2>{L['not_checked']}</h2><ul>{''.join(f'<li>{e(s)}</li>' for s in skipped)}<li>{L['always']}</li></ul>
<h2>{L['assumptions']}</h2>{lst(assumed, [L['decision'], 'Status', L['date']])}
<h2>{L['open_q']}</h2>{lst(openq, [L['question'], L['blocks'], L['rec']])}
</body></html>"""
    out = os.path.join(project, "out")
    os.makedirs(out, exist_ok=True)
    hp = os.path.join(out, "review.html")
    open(hp, "w", encoding="utf-8").write(page)
    pdf = os.path.join(out, "review.pdf")
    if os.path.exists(pdf):
        os.remove(pdf)
    b = browser()
    if b:
        subprocess.run([b, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                        "file:///" + hp.replace("\\", "/")], timeout=120, capture_output=True)
        for _ in range(30):                                  # the browser returns before its child writes the file
            if os.path.exists(pdf) and os.path.getsize(pdf) > 0:
                break
            time.sleep(0.5)
    made = pdf if os.path.exists(pdf) else hp
    print(f"REVIEW {len(rows)} items, {n_ok} checks OK, {n_fail} FAILED, {len(skipped)} kinds skipped "
          f"(level {lv}) -> {made}")
    return made


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    lang = "he" if "--lang" in sys.argv and sys.argv[sys.argv.index("--lang") + 1] == "he" else "en"
    build(args[0] if args else None, lang)
