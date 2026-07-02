"""Translation memory: storage, exact/fuzzy matching, concordance.

Candidate retrieval uses the SQLite FTS5 index over TM sources; candidates
are then scored with word-level Levenshtein similarity, the standard CAT
fuzzy-match measure.
"""

import re
import sqlite3

from . import norm_lang
from .xliff import strip_tags

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(strip_tags(text).lower())


def _word_levenshtein(a: list[str], b: list[str]) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i]
        for j, wb in enumerate(b, 1):
            cost = 0 if wa == wb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """CAT-style fuzzy score in [0, 1] between two segment texts."""
    ta, tb = tokenize(a), tokenize(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    dist = _word_levenshtein(ta, tb)
    return max(0.0, 1.0 - dist / max(len(ta), len(tb)))


def add_unit(conn: sqlite3.Connection, src_lang: str, tgt_lang: str,
             source: str, target: str, origin: str = "manual") -> bool:
    """Store a TM unit. Returns True if a new row was inserted."""
    source = " ".join(source.split())
    target = " ".join(target.split())
    if not source or not target:
        return False
    cur = conn.execute(
        """INSERT INTO tm_units (src_lang, tgt_lang, source, target, origin)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(src_lang, tgt_lang, source, target)
           DO UPDATE SET use_count = use_count + 1, updated_at = datetime('now')""",
        (norm_lang(src_lang), norm_lang(tgt_lang), source, target, origin))
    conn.commit()
    return cur.lastrowid is not None


def add_units(conn: sqlite3.Connection, src_lang: str, tgt_lang: str,
              pairs: list[tuple[str, str]], origin: str) -> int:
    n = 0
    for s, t in pairs:
        if add_unit(conn, src_lang, tgt_lang, s, t, origin):
            n += 1
    return n


def _fts_query(text: str, max_terms: int = 12) -> str:
    """Build an OR query from the longest tokens of the text."""
    tokens = sorted(set(tokenize(text)), key=len, reverse=True)[:max_terms]
    return " OR ".join(f'"{t}"' for t in tokens)


def lookup(conn: sqlite3.Connection, src_lang: str, tgt_lang: str, text: str,
           limit: int = 5, min_score: float = 0.5) -> list[dict]:
    """Return TM matches sorted by score (1.0 = exact, aka 100%)."""
    src_lang, tgt_lang = norm_lang(src_lang), norm_lang(tgt_lang)
    plain = " ".join(strip_tags(text).split())
    if not plain:
        return []

    results: dict[int, dict] = {}

    for row in conn.execute(
            "SELECT id, source, target, origin, use_count FROM tm_units "
            "WHERE src_lang=? AND tgt_lang=? AND source=?",
            (src_lang, tgt_lang, plain)):
        results[row["id"]] = dict(row) | {"score": 1.0}

    query = _fts_query(plain)
    if query:
        rows = conn.execute(
            """SELECT t.id, t.source, t.target, t.origin, t.use_count
               FROM tm_fts f JOIN tm_units t ON t.id = f.rowid
               WHERE tm_fts MATCH ? AND t.src_lang=? AND t.tgt_lang=?
               ORDER BY bm25(tm_fts) LIMIT 80""",
            (query, src_lang, tgt_lang)).fetchall()
        for row in rows:
            if row["id"] in results:
                continue
            score = similarity(plain, row["source"])
            if score >= min_score:
                results[row["id"]] = dict(row) | {"score": round(score, 4)}

    matches = sorted(results.values(),
                     key=lambda m: (-m["score"], -m["use_count"]))[:limit]
    for m in matches:
        m["percent"] = int(round(m["score"] * 100))
    return matches


def concordance(conn: sqlite3.Connection, src_lang: str, tgt_lang: str,
                query: str, limit: int = 30) -> list[dict]:
    """Search TM sources and targets for a word or phrase."""
    src_lang, tgt_lang = norm_lang(src_lang), norm_lang(tgt_lang)
    like = f"%{query}%"
    rows = conn.execute(
        """SELECT source, target, origin FROM tm_units
           WHERE src_lang=? AND tgt_lang=? AND (source LIKE ? OR target LIKE ?)
           ORDER BY use_count DESC, updated_at DESC LIMIT ?""",
        (src_lang, tgt_lang, like, like, limit)).fetchall()
    return [dict(r) for r in rows]


def all_units(conn: sqlite3.Connection, src_lang: str, tgt_lang: str) -> list[dict]:
    rows = conn.execute(
        "SELECT source, target, origin, use_count FROM tm_units "
        "WHERE src_lang=? AND tgt_lang=? ORDER BY id",
        (norm_lang(src_lang), norm_lang(tgt_lang))).fetchall()
    return [dict(r) for r in rows]


def stats(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT src_lang, tgt_lang, COUNT(*) AS units FROM tm_units "
        "GROUP BY src_lang, tgt_lang ORDER BY units DESC").fetchall()
    return [dict(r) for r in rows]
