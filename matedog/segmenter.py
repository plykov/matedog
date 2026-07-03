"""Sentence segmentation for plain-text import (EN / RU / NL)."""

import re

# Abbreviations that should not end a sentence.
_ABBREV = {
    # English
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e",
    "no", "vol", "fig", "approx",
    # Dutch
    "dhr", "mevr", "drs", "ir", "mr", "bv", "nl", "o.a", "d.w.z", "bijv", "evt", "ca",
    # Russian (transliterated forms appear rarely; Cyrillic ones below)
    "т.е", "т.д", "т.п", "и.о", "г", "гг", "ул", "им", "др", "проф", "акад", "стр", "рис",
}

_SENT_END = re.compile(r"([.!?…]+)(\s+|$)")


def _is_abbrev(text_before: str) -> bool:
    m = re.search(r"([\w.]+?)\.?$", text_before, re.UNICODE)
    if not m:
        return False
    word = m.group(1).lower().rstrip(".")
    if word in _ABBREV:
        return True
    # Single letter followed by period: initials like "J." or "А."
    return len(word) == 1 and word.isalpha()


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences."""
    sentences = []
    start = 0
    for m in _SENT_END.finditer(text):
        end = m.end(1)
        candidate = text[start:end]
        rest = text[m.end():]
        # Don't split after abbreviations, or when the next char is lowercase.
        if _is_abbrev(text[start:m.start(1)]):
            continue
        if rest[:1].islower():
            continue
        sentence = candidate.strip()
        if sentence:
            sentences.append(sentence)
        start = m.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def segment_text(text: str) -> list[str]:
    """Split full document text into translation segments (by paragraph, then sentence)."""
    segments = []
    for para in re.split(r"\n\s*\n|\r\n\s*\r\n", text):
        para = re.sub(r"\s+", " ", para).strip()
        if para:
            segments.extend(split_sentences(para))
    return segments
