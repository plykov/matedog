"""Machine translation suggestions, fully local.

Provider chain (best available wins):

1. TM exact/fuzzy match, optionally repaired with the learned lexicon
   (adaptive suggestion, in the spirit of ModernMT's adaptation).
2. Argos Translate neural MT, if the optional `argostranslate` package and
   the en<->ru / en<->nl models are installed.
3. Lexicon gloss: word-by-word translation from the trained IBM Model 1
   lexicon — a rough draft, clearly marked low quality.
"""

import re
import sqlite3

from . import norm_lang
from . import mlx, tm

try:  # optional dependency
    from argostranslate import translate as _argos
except ImportError:
    _argos = None


def _argos_translate(text: str, src: str, tgt: str) -> str | None:
    if _argos is None:
        return None
    try:
        langs = _argos.get_installed_languages()
        src_l = next((l for l in langs if l.code == src), None)
        tgt_l = next((l for l in langs if l.code == tgt), None)
        if not src_l or not tgt_l:
            return None
        translation = src_l.get_translation(tgt_l)
        return translation.translate(text) if translation else None
    except Exception:
        return None


def _gloss(conn: sqlite3.Connection, text: str, src: str, tgt: str) -> str | None:
    words = re.findall(r"\w+|\W+", text, re.UNICODE)
    out, translated_any = [], False
    for w in words:
        if w.strip() and re.match(r"\w", w, re.UNICODE):
            trans = mlx.lexicon_lookup(conn, src, tgt, w)
            if trans:
                word = trans[0][0]
                if w[:1].isupper():
                    word = word[:1].upper() + word[1:]
                out.append(word)
                translated_any = True
                continue
        out.append(w)
    return "".join(out) if translated_any else None


def suggest(conn: sqlite3.Connection, src_lang: str, tgt_lang: str,
            text: str) -> dict | None:
    """Return the best machine suggestion: {text, provider, percent}."""
    src, tgt = norm_lang(src_lang), norm_lang(tgt_lang)

    matches = tm.lookup(conn, src, tgt, text, limit=1, min_score=0.6)
    if matches:
        best = matches[0]
        if best["percent"] >= 100:
            return {"text": best["target"], "provider": "TM (exact)", "percent": 100}
        repaired = mlx.repair_fuzzy(conn, src, tgt, text, best["source"], best["target"])
        if repaired:
            return {"text": repaired, "provider": "TM + lexicon repair",
                    "percent": min(99, best["percent"] + 5)}

    nmt = _argos_translate(text, src, tgt)
    if nmt:
        return {"text": nmt, "provider": "Argos Translate (local NMT)", "percent": 85}

    if matches:
        best = matches[0]
        return {"text": best["target"], "provider": "TM (fuzzy)", "percent": best["percent"]}

    gloss = _gloss(conn, text, src, tgt)
    if gloss:
        return {"text": gloss, "provider": "Lexicon gloss (rough draft)", "percent": 30}
    return None


def providers_status() -> dict:
    return {
        "tm": True,
        "lexicon": True,
        "argos": _argos is not None,
    }
