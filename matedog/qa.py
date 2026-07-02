"""Proofreading / QA checks, including RU- and NL-specific rules.

Deterministic checks run locally with no dependencies. If a local
LanguageTool server is configured (MATEDOG_LT_URL, e.g. http://localhost:8081),
its grammar/style findings for EN, RU and NL are merged in.
"""

import json
import os
import re
import urllib.parse
import urllib.request

from . import norm_lang
from .tm import tokenize

_TAG_RE = re.compile(r"<[^<>]+>")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_END_PUNct = ".!?:;…"

LT_LANG = {"en": "en-US", "ru": "ru-RU", "nl": "nl"}


def _tags(text: str) -> list[str]:
    out = []
    for t in _TAG_RE.findall(text):
        name = re.match(r"</?\s*([\w:-]+)", t)
        out.append(("/" if t.startswith("</") else "") + (name.group(1) if name else t))
    return sorted(out)


def _numbers(text: str, lang: str) -> list[str]:
    nums = []
    for n in _NUM_RE.findall(text):
        # RU and NL write decimals with a comma; normalize for comparison.
        nums.append(n.replace(",", ".").rstrip("."))
    return sorted(nums)


def check_segment(source: str, target: str, src_lang: str, tgt_lang: str,
                  glossary: list[dict] | None = None,
                  lexicon: list[tuple[str, list[str]]] | None = None) -> list[dict]:
    """Return a list of issues: {code, severity ('error'|'warning'), message}."""
    src_lang, tgt_lang = norm_lang(src_lang), norm_lang(tgt_lang)
    issues = []

    def add(code, severity, message):
        issues.append({"code": code, "severity": severity, "message": message})

    if not target.strip():
        add("empty", "error", "Target is empty")
        return issues

    if source.strip() == target.strip() and src_lang != tgt_lang and len(tokenize(source)) > 2:
        add("untranslated", "warning", "Target is identical to source")

    st, tt = _tags(source), _tags(target)
    if st != tt:
        add("tags", "error", f"Inline tag mismatch (source: {len(st)}, target: {len(tt)})")

    sn, tn = _numbers(source, src_lang), _numbers(target, tgt_lang)
    if sn != tn:
        missing = [n for n in sn if n not in tn]
        extra = [n for n in tn if n not in sn]
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing[:5]))
        if extra:
            detail.append("added " + ", ".join(extra[:5]))
        add("numbers", "error", "Number mismatch: " + "; ".join(detail))

    if target != target.strip():
        add("whitespace", "warning", "Leading or trailing whitespace in target")
    if "  " in target:
        add("double_space", "warning", "Double space in target")

    s_end = source.rstrip()[-1:] if source.rstrip() else ""
    t_end = target.rstrip()[-1:] if target.rstrip() else ""
    if (s_end in _END_PUNct) != (t_end in _END_PUNct):
        add("punct_end", "warning", "End punctuation differs from source")

    s_words, t_words = tokenize(source), tokenize(target)
    if s_words and t_words:
        ratio = len(target) / max(1, len(source))
        if ratio > 2.6 or ratio < 0.35:
            add("length", "warning", f"Unusual length ratio ({ratio:.1f}x source)")

    for i in range(1, len(t_words)):
        if t_words[i] == t_words[i - 1] and len(t_words[i]) > 1:
            add("repeated_word", "warning", f"Repeated word: “{t_words[i]}”")
            break

    if source[:1].isalpha() and target[:1].isalpha():
        if source[:1].isupper() != target[:1].isupper():
            add("capitalization", "warning", "First-letter capitalization differs from source")

    issues.extend(_lang_specific(target, tgt_lang))

    for g in glossary or []:
        if re.search(rf"(?i)\b{re.escape(g['src_term'])}\b", source) and \
           not re.search(rf"(?i){re.escape(g['tgt_term'])}", target):
            add("glossary", "warning",
                f"Glossary: “{g['src_term']}” should be translated as “{g['tgt_term']}”")

    # ML-assisted check: a confident lexicon translation of a source word is
    # absent from the target -> possible omission.
    if lexicon:
        t_set = set(t_words)
        flagged = [sw for sw, trans in lexicon if not any(t in t_set for t in trans)]
        if flagged:
            add("possible_omission", "warning",
                "Possibly untranslated: " + ", ".join(f"“{w}”" for w in flagged[:3]))

    return issues


def _lang_specific(target: str, tgt_lang: str) -> list[dict]:
    issues = []

    def add(code, severity, message):
        issues.append({"code": code, "severity": severity, "message": message})

    if tgt_lang == "ru":
        if re.search(r'"[^"]+"', target):
            add("ru_quotes", "warning", "Russian typography prefers «guillemets» over straight quotes")
        if re.search(r"\s-\s", target):
            add("ru_dash", "warning", "Use an em dash (—) instead of a hyphen between words")
        # Latin letters inside Cyrillic words usually mean a typo (е/e, о/o, ...).
        if re.search(r"[а-яА-ЯёЁ][a-zA-Z]|[a-zA-Z][а-яА-ЯёЁ]", target):
            add("ru_mixed_script", "error", "Latin and Cyrillic letters mixed inside a word")

    if tgt_lang == "nl":
        # Compounds are written as one word in Dutch; flag the frequent
        # anglicism of splitting them ("taal fout" vs "taalfout") only in the
        # obvious case of a repeated split pair matched against a joined form.
        if re.search(r"\bkomma\s+splitsing\b", target, re.I):
            add("nl_compound", "warning", "Dutch compounds are written as one word")
        if re.search(r"\bu\s+heeft\b", target, re.I):
            add("nl_style", "warning", "Formal style: “u hebt” is preferred over “u heeft”")

    return issues


def languagetool_check(text: str, lang: str, lt_url: str | None = None,
                       timeout: float = 5.0) -> list[dict]:
    """Query a local LanguageTool server, if configured. Returns [] otherwise."""
    lt_url = lt_url or os.environ.get("MATEDOG_LT_URL", "")
    lang = norm_lang(lang)
    if not lt_url or lang not in LT_LANG or not text.strip():
        return []
    data = urllib.parse.urlencode({"text": text, "language": LT_LANG[lang]}).encode()
    try:
        req = urllib.request.Request(lt_url.rstrip("/") + "/v2/check", data=data)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        return []
    issues = []
    for m in payload.get("matches", []):
        issues.append({
            "code": "lt_" + (m.get("rule", {}).get("id", "rule").lower()),
            "severity": "warning",
            "message": m.get("message", "LanguageTool issue"),
        })
    return issues
