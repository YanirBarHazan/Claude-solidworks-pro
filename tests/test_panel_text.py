"""The Claude tab: both languages complete, markup escaped, insight tags in both languages."""
import os
import re

import swpanel_taskpane as tp

HTML = os.path.join(os.path.dirname(tp.HERE), "swpanel", "html", "panel.html")


def test_both_languages_have_every_line():
    assert set(tp.TXT) == {"he", "en"}
    assert set(tp.TXT["he"]) == set(tp.TXT["en"])
    src = open(tp.__file__, encoding="utf-8").read()
    for key in set(re.findall(r'self\.t\("(\w+)"', src)):
        assert key in tp.TXT["he"], key


def test_ui_lang():
    assert tp.ui_lang({"lang": "en"}) == "en"
    assert tp.ui_lang({"lang": "he"}) == "he"
    assert tp.ui_lang({"lang": "fr"}) in tp.LANGS
    assert tp.ui_lang({}) in tp.LANGS


def test_rich_escapes_and_tags():
    out = tp.Bridge.rich("<script>alert(1)</script>")
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert 'class="ins mfg"' in tp.Bridge.rich("[ייצור] כיפוף R1 ייסדק")
    assert 'class="ins mfg"' in tp.Bridge.rich("[Manufacturing] an R1 bend will crack")
    assert 'class="ins warn"' in tp.Bridge.rich("[Note] wall 0.8 mm")
    assert '<span class="num">3.5 mm</span>' in tp.Bridge.rich("wall 3.5 mm")


def test_panel_html_has_both_languages():
    html = open(HTML, encoding="utf-8").read()
    assert 'id="fl_he"' in html and 'id="fl_en"' in html
    blocks = re.findall(r"\n    (he|en): \{(.*?)\] \}", html, re.S)
    keys = {lang: set(re.findall(r"(?:[{,]|^)\s*([a-z0-9]+):", body, re.M)) for lang, body in blocks}
    assert set(keys) == {"he", "en"} and keys["he"] == keys["en"], keys
    for i in re.findall(r"byId\('(\w+)'\)", html):
        assert f'id="{i}"' in html, i
