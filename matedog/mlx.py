"""Machine learning from paired source/target texts.

Two mechanisms, both fully local:

1. A word-translation lexicon trained with IBM Model 1 EM over all TM units
   for a language pair. It powers term suggestions, fuzzy-match repair and
   the "possible missing translation" QA check, and improves as the TM grows
   (every confirmed segment is new training data).

2. Paired-corpus import: two plain-text files (source + target). Sentences
   are aligned with a Gale-Church-style length-based DP alignment, stored in
   the TM, and used to (re)train the lexicon.
"""

import math
import sqlite3
from collections import defaultdict

from . import norm_lang
from .segmenter import segment_text
from .tm import tokenize

MIN_PROB = 0.15      # keep only reasonably confident lexicon entries
TOP_K = 4            # translations kept per source word
EM_ITERS = 6
MAX_PAIRS = 50_000   # training cap to bound memory


def train_lexicon(conn: sqlite3.Connection, src_lang: str, tgt_lang: str) -> int:
    """(Re)train the IBM Model 1 lexicon from all TM units for the pair.

    Returns the number of lexicon entries stored.
    """
    src_lang, tgt_lang = norm_lang(src_lang), norm_lang(tgt_lang)
    rows = conn.execute(
        "SELECT source, target FROM tm_units WHERE src_lang=? AND tgt_lang=? LIMIT ?",
        (src_lang, tgt_lang, MAX_PAIRS)).fetchall()
    pairs = [(tokenize(r["source"]), tokenize(r["target"])) for r in rows]
    pairs = [(s, t) for s, t in pairs if s and t and len(s) < 80 and len(t) < 80]
    if not pairs:
        return 0

    # IBM Model 1: t(target_word | source_word), uniform init, EM.
    cooc: dict[str, set] = defaultdict(set)
    for s_toks, t_toks in pairs:
        for sw in s_toks:
            cooc[sw].update(t_toks)
    t_prob = {sw: {tw: 1.0 / len(tws) for tw in tws} for sw, tws in cooc.items()}

    for _ in range(EM_ITERS):
        count = defaultdict(float)
        total = defaultdict(float)
        for s_toks, t_toks in pairs:
            for tw in t_toks:
                denom = sum(t_prob[sw].get(tw, 0.0) for sw in s_toks)
                if denom <= 0:
                    continue
                for sw in s_toks:
                    delta = t_prob[sw].get(tw, 0.0) / denom
                    if delta > 0:
                        count[(sw, tw)] += delta
                        total[sw] += delta
        for (sw, tw), c in count.items():
            if total[sw] > 0:
                t_prob[sw][tw] = c / total[sw]

    conn.execute("DELETE FROM lexicon WHERE src_lang=? AND tgt_lang=?", (src_lang, tgt_lang))
    n = 0
    for sw, tws in t_prob.items():
        best = sorted(tws.items(), key=lambda kv: -kv[1])[:TOP_K]
        for tw, p in best:
            if p >= MIN_PROB and len(sw) > 1 and len(tw) > 1:
                conn.execute(
                    "INSERT OR REPLACE INTO lexicon (src_lang, tgt_lang, src_word, tgt_word, prob) "
                    "VALUES (?, ?, ?, ?, ?)", (src_lang, tgt_lang, sw, tw, round(p, 4)))
                n += 1
    conn.commit()
    return n


def lexicon_lookup(conn: sqlite3.Connection, src_lang: str, tgt_lang: str,
                   word: str) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT tgt_word, prob FROM lexicon "
        "WHERE src_lang=? AND tgt_lang=? AND src_word=? ORDER BY prob DESC",
        (norm_lang(src_lang), norm_lang(tgt_lang), word.lower())).fetchall()
    return [(r["tgt_word"], r["prob"]) for r in rows]


def repair_fuzzy(conn: sqlite3.Connection, src_lang: str, tgt_lang: str,
                 new_source: str, match_source: str, match_target: str) -> str | None:
    """Try to patch a fuzzy match's target using the learned lexicon.

    If the new source differs from the matched source by word substitutions,
    and the lexicon confidently maps both the removed word's translation and
    the added word's translation, swap them in the target. Conservative:
    returns None unless every difference can be repaired.
    """
    new_toks, old_toks = tokenize(new_source), tokenize(match_source)
    removed = [w for w in old_toks if w not in new_toks]
    added = [w for w in new_toks if w not in old_toks]
    if not removed or len(removed) != len(added) or len(removed) > 2:
        return None

    target = match_target
    tgt_lower = tokenize(target)
    for old_w, new_w in zip(removed, added):
        old_trans = [t for t, p in lexicon_lookup(conn, src_lang, tgt_lang, old_w) if p >= 0.25]
        new_trans = lexicon_lookup(conn, src_lang, tgt_lang, new_w)
        hit = next((t for t in old_trans if t in tgt_lower), None)
        if hit is None or not new_trans:
            return None
        replacement = new_trans[0][0]
        # Replace the first case-insensitive whole-word occurrence.
        import re
        pattern = re.compile(rf"(?i)\b{re.escape(hit)}\b")
        new_target, n = pattern.subn(replacement, target, count=1)
        if n == 0:
            return None
        target = new_target
        tgt_lower = tokenize(target)
    return target if target != match_target else None


def align_corpus(src_text: str, tgt_text: str) -> list[tuple[str, str]]:
    """Align two plain-text documents sentence-by-sentence.

    Line-aligned input (same non-empty line counts) is zipped directly.
    Otherwise sentences are aligned with a length-ratio DP allowing
    1-1, 1-2 and 2-1 beads (Gale-Church style, simplified).
    """
    src_lines = [ln.strip() for ln in src_text.splitlines() if ln.strip()]
    tgt_lines = [ln.strip() for ln in tgt_text.splitlines() if ln.strip()]
    if len(src_lines) > 1 and len(src_lines) == len(tgt_lines):
        return list(zip(src_lines, tgt_lines))

    ss, ts = segment_text(src_text), segment_text(tgt_text)
    if not ss or not ts:
        return []

    def cost(s_chunk: list[str], t_chunk: list[str]) -> float:
        ls = sum(len(x) for x in s_chunk)
        lt = sum(len(x) for x in t_chunk)
        if ls == 0 or lt == 0:
            return 10.0
        ratio = ls / lt
        penalty = 0.4 * (len(s_chunk) + len(t_chunk) - 2)  # prefer 1-1 beads
        return abs(math.log(ratio)) + penalty

    n, m = len(ss), len(ts)
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    beads = [(1, 1), (1, 2), (2, 1)]
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] == INF:
                continue
            for di, dj in beads:
                ni, nj = i + di, j + dj
                if ni <= n and nj <= m:
                    c = dp[i][j] + cost(ss[i:ni], ts[j:nj])
                    if c < dp[ni][nj]:
                        dp[ni][nj] = c
                        back[ni][nj] = (di, dj)

    if dp[n][m] == INF:
        # Fallback: pair up to the shorter length.
        return list(zip(ss, ts))

    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        step = back[i][j]
        if step is None:
            break
        di, dj = step
        pairs.append((" ".join(ss[i - di:i]), " ".join(ts[j - dj:j])))
        i, j = i - di, j - dj
    pairs.reverse()
    return pairs
