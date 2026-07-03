"""XLIFF 1.2 / 2.0 parsing and round-trip generation.

Inline markup (<g>, <x>, <ph>, <bpt>, <ept>, <pc>, ...) is preserved by
serializing it as literal tags inside the segment text, the way CAT editors
display placeholder tags. On export the edited target text is parsed back
into real XML; if the user broke the markup the text is exported escaped.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

NS12 = "urn:oasis:names:tc:xliff:document:1.2"
NS20 = "urn:oasis:names:tc:xliff:document:2.0"

_STATE_TO_X12 = {"translated": "translated", "approved": "final", "draft": "new"}
_X12_DONE_STATES = {"translated", "signed-off", "final"}


@dataclass
class Unit:
    unit_id: str
    source: str
    target: str = ""
    state: str = "new"


@dataclass
class XliffDoc:
    version: str
    src_lang: str
    tgt_lang: str
    units: list[Unit] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _attr_str(elem: ET.Element) -> str:
    parts = []
    for k, v in elem.attrib.items():
        k = _local(k)
        v = v.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        parts.append(f'{k}="{v}"')
    return (" " + " ".join(parts)) if parts else ""


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inner_xml(elem: ET.Element) -> str:
    """Serialize element content: text plus inline children as literal tags."""
    out = [_esc(elem.text or "")]
    for child in elem:
        name = _local(child.tag)
        inner = inner_xml(child)
        if inner:
            out.append(f"<{name}{_attr_str(child)}>{inner}</{name}>")
        else:
            out.append(f"<{name}{_attr_str(child)}/>")
        out.append(_esc(child.tail or ""))
    return "".join(out)


def _parse_inline(text: str, ns: str) -> ET.Element:
    """Parse editor text (with literal inline tags) back into an XML fragment.

    Returns a <wrap> element whose content is the parsed fragment.
    Raises ET.ParseError if the markup is not well-formed.
    """
    wrapped = f'<wrap xmlns="{ns}">{text}</wrap>'
    return ET.fromstring(wrapped)


def _fill(target_el: ET.Element, text: str, ns: str) -> None:
    """Set element content from editor text, preserving inline tags when valid."""
    for child in list(target_el):
        target_el.remove(child)
    target_el.text = None
    try:
        frag = _parse_inline(text, ns)
    except ET.ParseError:
        target_el.text = text
        return
    target_el.text = frag.text
    for child in list(frag):
        target_el.append(child)


def parse_xliff(content: str) -> XliffDoc:
    root = ET.fromstring(content)
    ns = root.tag.split("}")[0].strip("{") if root.tag.startswith("{") else ""
    version = root.get("version", "1.2")

    if version.startswith("2"):
        return _parse_20(root, ns)
    return _parse_12(root, ns)


def _parse_12(root: ET.Element, ns: str) -> XliffDoc:
    q = lambda t: f"{{{ns}}}{t}" if ns else t
    doc = XliffDoc(version="1.2", src_lang="", tgt_lang="")
    for f in root.iter(q("file")):
        doc.src_lang = doc.src_lang or f.get("source-language", "")
        doc.tgt_lang = doc.tgt_lang or f.get("target-language", "")
        for tu in f.iter(q("trans-unit")):
            if tu.get("translate", "yes") == "no":
                continue
            src = tu.find(q("source"))
            if src is None:
                continue
            tgt = tu.find(q("target"))
            target_text = inner_xml(tgt) if tgt is not None else ""
            x_state = tgt.get("state", "") if tgt is not None else ""
            state = "translated" if x_state in _X12_DONE_STATES else ("draft" if target_text else "new")
            doc.units.append(Unit(tu.get("id", ""), inner_xml(src), target_text, state))
    return doc


def _parse_20(root: ET.Element, ns: str) -> XliffDoc:
    q = lambda t: f"{{{ns}}}{t}" if ns else t
    doc = XliffDoc(version="2.0", src_lang=root.get("srcLang", ""), tgt_lang=root.get("trgLang", ""))
    for unit in root.iter(q("unit")):
        for i, seg in enumerate(unit.iter(q("segment"))):
            src = seg.find(q("source"))
            if src is None:
                continue
            tgt = seg.find(q("target"))
            target_text = inner_xml(tgt) if tgt is not None else ""
            seg_state = seg.get("state", "initial")
            state = "translated" if seg_state in ("translated", "reviewed", "final") else (
                "draft" if target_text else "new")
            uid = unit.get("id", "")
            seg_id = seg.get("id", str(i))
            doc.units.append(Unit(f"{uid}//{seg_id}", inner_xml(src), target_text, state))
    return doc


def generate_xliff(original: str, translations: dict[str, tuple[str, str]],
                   tgt_lang: str = "") -> str:
    """Write translations back into the original XLIFF.

    translations maps unit_id -> (target_text, state). Returns the new XLIFF string.
    """
    root = ET.fromstring(original)
    ns = root.tag.split("}")[0].strip("{") if root.tag.startswith("{") else ""
    if ns:
        ET.register_namespace("", ns)
    version = root.get("version", "1.2")
    if version.startswith("2"):
        _generate_20(root, ns, translations)
    else:
        _generate_12(root, ns, translations, tgt_lang)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def _generate_12(root: ET.Element, ns: str, translations: dict, tgt_lang: str) -> None:
    q = lambda t: f"{{{ns}}}{t}" if ns else t
    for f in root.iter(q("file")):
        if tgt_lang and not f.get("target-language"):
            f.set("target-language", tgt_lang)
        for tu in f.iter(q("trans-unit")):
            uid = tu.get("id", "")
            if uid not in translations:
                continue
            text, state = translations[uid]
            tgt = tu.find(q("target"))
            if tgt is None:
                tgt = ET.SubElement(tu, q("target"))
                # place target right after source for readability
                src = tu.find(q("source"))
                if src is not None:
                    tu.remove(tgt)
                    tu.insert(list(tu).index(src) + 1, tgt)
            _fill(tgt, text, ns)
            if state in _STATE_TO_X12:
                tgt.set("state", _STATE_TO_X12[state])


def _generate_20(root: ET.Element, ns: str, translations: dict) -> None:
    q = lambda t: f"{{{ns}}}{t}" if ns else t
    for unit in root.iter(q("unit")):
        uid = unit.get("id", "")
        for i, seg in enumerate(unit.iter(q("segment"))):
            seg_id = seg.get("id", str(i))
            key = f"{uid}//{seg_id}"
            if key not in translations:
                continue
            text, state = translations[key]
            tgt = seg.find(q("target"))
            if tgt is None:
                tgt = ET.SubElement(seg, q("target"))
            _fill(tgt, text, ns)
            if state == "approved":
                seg.set("state", "final")
            elif state == "translated":
                seg.set("state", "translated")


def make_xliff_from_segments(name: str, src_lang: str, tgt_lang: str,
                             sources: list[str]) -> str:
    """Build a fresh XLIFF 1.2 document from plain-text segments."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<xliff xmlns="{NS12}" version="1.2">',
        f'  <file original="{_esc(name)}" source-language="{src_lang}" '
        f'target-language="{tgt_lang}" datatype="plaintext">',
        "    <body>",
    ]
    for i, src in enumerate(sources, 1):
        lines.append(f'      <trans-unit id="{i}">')
        lines.append(f"        <source>{_esc(src)}</source>")
        lines.append("        <target/>")
        lines.append("      </trans-unit>")
    lines += ["    </body>", "  </file>", "</xliff>"]
    return "\n".join(lines)


TAG_RE = re.compile(r"<[^<>]+>")


def strip_tags(text: str) -> str:
    """Remove inline placeholder tags, for TM/QA text comparison."""
    return TAG_RE.sub(" ", text)
