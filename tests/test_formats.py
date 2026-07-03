"""XLIFF / TMX round-trip and segmentation tests."""

from matedog import tmx, xliff
from matedog.segmenter import segment_text

XLIFF12 = """<?xml version="1.0" encoding="UTF-8"?>
<xliff xmlns="urn:oasis:names:tc:xliff:document:1.2" version="1.2">
 <file original="doc.txt" source-language="en" target-language="ru" datatype="plaintext">
  <body>
   <trans-unit id="1"><source>Hello <g id="1">world</g>.</source></trans-unit>
   <trans-unit id="2"><source>Second segment with 42 items.</source>
     <target state="translated">Второй сегмент с 42 элементами.</target></trans-unit>
  </body>
 </file>
</xliff>"""

XLIFF20 = """<?xml version="1.0" encoding="UTF-8"?>
<xliff xmlns="urn:oasis:names:tc:xliff:document:2.0" version="2.0" srcLang="en" trgLang="nl">
 <file id="f1">
  <unit id="u1">
   <segment id="s1"><source>Good morning.</source></segment>
  </unit>
 </file>
</xliff>"""

TMX = """<?xml version="1.0" encoding="UTF-8"?>
<tmx version="1.4">
 <header creationtool="x" creationtoolversion="1" segtype="sentence"
         o-tmf="x" adminlang="en" srclang="en" datatype="plaintext"/>
 <body>
  <tu>
   <tuv xml:lang="en"><seg>Good morning</seg></tuv>
   <tuv xml:lang="ru"><seg>Доброе утро</seg></tuv>
  </tu>
  <tu>
   <tuv xml:lang="en-US"><seg>Thank <bpt i="1">&lt;b&gt;</bpt>you<ept i="1">&lt;/b&gt;</ept></seg></tuv>
   <tuv xml:lang="nl-NL"><seg>Dank je</seg></tuv>
  </tu>
 </body>
</tmx>"""


def test_parse_xliff12():
    doc = xliff.parse_xliff(XLIFF12)
    assert doc.src_lang == "en" and doc.tgt_lang == "ru"
    assert len(doc.units) == 2
    assert doc.units[0].source == 'Hello <g id="1">world</g>.'
    assert doc.units[0].state == "new"
    assert doc.units[1].target == "Второй сегмент с 42 элементами."
    assert doc.units[1].state == "translated"


def test_roundtrip_xliff12_preserves_tags():
    translations = {"1": ('Привет, <g id="1">мир</g>.', "translated")}
    out = xliff.generate_xliff(XLIFF12, translations)
    doc = xliff.parse_xliff(out)
    assert doc.units[0].target == 'Привет, <g id="1">мир</g>.'
    assert doc.units[0].state == "translated"
    assert 'state="translated"' in out


def test_roundtrip_broken_markup_falls_back_to_text():
    translations = {"1": ("Broken <g id=1> tag", "translated")}
    out = xliff.generate_xliff(XLIFF12, translations)
    doc = xliff.parse_xliff(out)
    assert "Broken" in doc.units[0].target


def test_parse_xliff20():
    doc = xliff.parse_xliff(XLIFF20)
    assert doc.version == "2.0"
    assert doc.src_lang == "en" and doc.tgt_lang == "nl"
    assert doc.units[0].source == "Good morning."
    out = xliff.generate_xliff(XLIFF20, {doc.units[0].unit_id: ("Goedemorgen.", "translated")})
    doc2 = xliff.parse_xliff(out)
    assert doc2.units[0].target == "Goedemorgen."


def test_tmx_parse_normalizes_region_and_direction():
    pairs = tmx.parse_tmx(TMX, "en", "ru")
    assert pairs == [("Good morning", "Доброе утро")]
    nl = tmx.parse_tmx(TMX, "nl", "en")   # reversed direction
    assert nl == [("Dank je", "Thank <b>you</b>")]


def test_tmx_generate_roundtrip():
    units = [{"source": "A & B", "target": "А и Б"}]
    out = tmx.generate_tmx(units, "en", "ru")
    assert tmx.parse_tmx(out, "en", "ru") == [("A & B", "А и Б")]


def test_segmenter():
    text = "Dr. Smith arrived at 5 p.m. today. He was tired! Was he? Yes.\n\nNew paragraph."
    segs = segment_text(text)
    assert "He was tired!" in segs
    assert "Was he?" in segs
    assert segs[-1] == "New paragraph."
    assert not any(s.startswith("Smith") for s in segs)  # 'Dr.' did not split


def test_segmenter_russian():
    segs = segment_text("Привет, мир. Это второе предложение! А это т.д. и т.п. продолжение.")
    assert segs[0] == "Привет, мир."
    assert segs[1] == "Это второе предложение!"
