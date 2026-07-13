# 🐶 MateDog

A **private, fully local** MateCat-style CAT (computer-assisted translation) tool.
Everything — the server, the translation memory, the learning — runs on your own
machine. No cloud services, no data leaves your laptop.

**Language pairs:** English ↔ Russian, English ↔ Dutch.

## Features

- **Translation memory (machine memory)** — every segment you confirm is stored
  and reused. Exact and fuzzy matches (word-level Levenshtein scoring, FTS5-indexed
  candidate retrieval), concordance search, MateCat-style volume analysis
  (exact / fuzzy bands / repetitions / new words).
- **Machine learning from paired texts** — feed it a source text and its existing
  translation (two `.txt` files): sentences are aligned (Gale–Church-style),
  stored in the TM, and an IBM Model 1 word-translation lexicon is trained with EM.
  The lexicon powers term suggestions, *fuzzy-match repair* (adaptive suggestions
  that patch a fuzzy match with the right word), gloss drafts, and a
  "possible omission" QA check. It improves continuously: confirmed segments are
  new training data.
- **XLIFF integration** — import XLIFF 1.2 and 2.0, translate, export a valid
  translated XLIFF with inline tags (`<g>`, `<x>`, `<ph>`, …) preserved.
  Plain `.txt` files are sentence-segmented and imported too.
- **PDF import** — text is extracted from `.pdf` files (per page) and
  sentence-segmented for translation; export the result as XLIFF or TXT.
  Layout is not reproduced, and scanned (image-only) PDFs need OCR first.
- **TMX integration** — import/export translation memories as TMX 1.4
  (region codes and reversed direction handled).
- **Proofreading & editing** — segment editor with translate / approve / reject
  workflow, pre-translation, and a QA engine: tag mismatches, number mismatches
  (decimal-comma aware for RU/NL), punctuation, whitespace, capitalization,
  length ratio, repeated words, glossary compliance, Russian typography
  («guillemets», em dash, mixed Cyrillic/Latin script), Dutch style checks.
  Optional grammar checking via a local LanguageTool server.
- **Optional local neural MT** — install [Argos Translate](https://github.com/argosopentech/argos-translate)
  models for en↔ru / en↔nl and MateDog uses them automatically. Still 100% offline.

## Quick start (Windows)

1. Install [Python 3.11+](https://www.python.org/downloads/windows/)
   (check *"Add python.exe to PATH"* in the installer).
2. In the repository folder:

   ```bat
   pip install -r requirements.txt
   ```

3. Double-click **`matedog.bat`** (or run `python run.py`).
   Your browser opens `http://127.0.0.1:8123` — the app is local-only by default.

Your data is stored in a single SQLite file at `%USERPROFILE%\.matedog\matedog.db`.
Back it up by copying that file, or export your TM as TMX from the home screen.

### Optional: local neural MT

```bat
pip install argostranslate
argospm update
argospm install translate-en_ru translate-ru_en translate-en_nl translate-nl_en
```

### Optional: grammar checking (Russian/Dutch/English)

Run a local [LanguageTool](https://languagetool.org/download/) server and point
MateDog at it:

```bat
set MATEDOG_LT_URL=http://localhost:8081
python run.py
```

## Typical workflow

1. **Create a project** with the language pair.
2. **Teach it** (optional, recommended): import a TMX, or upload paired
   source/target `.txt` files under *Learn from paired texts* — this fills the
   TM and trains the lexicon.
3. **Upload** an XLIFF (export one from any tool/format converter) or a plain
   `.txt` file.
4. **Pre-translate** to fill segments from TM/MT, then edit. `Ctrl+Enter`
   confirms a segment and jumps to the next. Every confirmation feeds the TM.
5. **QA check** the file, fix flagged issues, **Approve** in review.
6. **Export** the translated XLIFF (or TXT), and optionally the TM as TMX.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest tests/
MATEDOG_NO_BROWSER=1 python run.py
```

Configuration via environment variables: `MATEDOG_DB` (database path),
`MATEDOG_HOST` / `MATEDOG_PORT` (default `127.0.0.1:8123`), `MATEDOG_LT_URL`
(LanguageTool server), `MATEDOG_NO_BROWSER=1` (don't open a browser).

## Architecture

Inspired by [MateCat](https://site.matecat.com) (web CAT editor + MySQL + MyMemory
TM + pluggable MT + Okapi-based format filters), collapsed into a single local
process:

| MateCat (SaaS) | MateDog (local) |
|---|---|
| PHP web app + MySQL/Redis/ActiveMQ | FastAPI + SQLite (FTS5), one process |
| MyMemory cloud TM | Local TM in SQLite, TMX import/export |
| ModernMT / Google Translate | TM + trained lexicon repair, optional Argos NMT |
| MateCat Filters (Okapi) for any format | XLIFF 1.2/2.0 + TXT natively; convert other formats to XLIFF externally |
| Web editor with revise mode | Same idea: browser editor served from localhost |

Modules: `matedog/xliff.py`, `tmx.py` (formats) · `tm.py` (memory & matching) ·
`mlx.py` (alignment + IBM Model 1 learning) · `qa.py` (proofreading) ·
`mt.py` (suggestion chain) · `server.py` (API + UI) · `ui/` (editor).

See [SPECIFICATIONS.md](SPECIFICATIONS.md) for the full technical specification.
