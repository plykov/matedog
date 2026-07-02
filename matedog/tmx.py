"""TMX 1.4 import/export for translation memory exchange."""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from . import norm_lang

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _seg_text(seg: ET.Element) -> str:
    """Flatten a <seg>: keep text, drop inline TMX tags but keep their text content."""
    parts = [seg.text or ""]
    for child in seg:
        parts.append(_seg_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def parse_tmx(content: str, src_lang: str, tgt_lang: str) -> list[tuple[str, str]]:
    """Extract (source, target) pairs for the given language pair.

    Direction-tolerant: if a <tu> holds both languages, the pair is returned
    oriented as (src_lang text, tgt_lang text) regardless of TMX srclang.
    """
    src_lang, tgt_lang = norm_lang(src_lang), norm_lang(tgt_lang)
    root = ET.fromstring(content)
    pairs = []
    for tu in root.iter("tu"):
        by_lang: dict[str, str] = {}
        for tuv in tu.iter("tuv"):
            lang = norm_lang(tuv.get(XML_LANG) or tuv.get("lang") or "")
            seg = tuv.find("seg")
            if lang and seg is not None:
                text = " ".join(_seg_text(seg).split())
                if text:
                    by_lang.setdefault(lang, text)
        if src_lang in by_lang and tgt_lang in by_lang:
            pairs.append((by_lang[src_lang], by_lang[tgt_lang]))
    return pairs


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def generate_tmx(units: list[dict], src_lang: str, tgt_lang: str) -> str:
    """Serialize TM units ({'source':…, 'target':…}) to a TMX 1.4b document."""
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<tmx version="1.4">',
        f'  <header creationtool="MateDog" creationtoolversion="0.1" segtype="sentence" '
        f'o-tmf="MateDog" adminlang="en" srclang="{src_lang}" datatype="plaintext" '
        f'creationdate="{now}"/>',
        "  <body>",
    ]
    for u in units:
        lines.append("    <tu>")
        lines.append(f'      <tuv xml:lang="{src_lang}"><seg>{_esc(u["source"])}</seg></tuv>')
        lines.append(f'      <tuv xml:lang="{tgt_lang}"><seg>{_esc(u["target"])}</seg></tuv>')
        lines.append("    </tu>")
    lines += ["  </body>", "</tmx>"]
    return "\n".join(lines)
