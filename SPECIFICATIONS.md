# MateDog — Technical Specifications

A **private, fully local** CAT (Computer-Assisted Translation) tool in the
spirit of [matecat.com](https://www.matecat.com), scoped to the
**English↔Russian** and **English↔Dutch** language pairs, running entirely on
the user's Windows laptop.

> **Status:** the architecture described here is implemented in this
> repository. Items marked *(roadmap)* are planned but not yet built.

<specifications>

<executive_summary>

MateDog gives a translator a MateCat-style workbench — segment-by-segment
editing of a bilingual file, live translation-memory (TM) leveraging,
machine-generated suggestions, pre-translation, and integrated
quality-assurance (QA) checks — with **no cloud services and no data leaving
the machine**.

MateCat itself is a web application (PHP + MySQL + Redis + ActiveMQ, the
MyMemory cloud TM, pluggable cloud MT, and Okapi-based format filters).
MateDog keeps the ergonomics of that model — a browser-based editor — but
collapses the entire stack into **one local Python process**: a FastAPI
server bound to `127.0.0.1` serving a single-page editor UI, with all data
in one embedded SQLite database. This is both faithful to the original
(the UI is a web editor, XLIFF is the pivot format) and trivially portable:
the only prerequisite on Windows is a Python install, with no compilation,
services, or admin rights required.

Machine learning is local too: MateDog aligns paired source/target texts,
stores them in the TM, and trains an IBM Model 1 word-translation lexicon
(EM algorithm) from all accumulated pairs. The lexicon powers term
suggestions, adaptive *fuzzy-match repair* (patching a fuzzy TM match with
the correct learned word), rough gloss drafts, and an omission-detection QA
check. Every segment the translator confirms becomes new training data, so
the system improves with use — the same feedback loop that ModernMT provides
for MateCat, at a laptop scale. Optionally, Argos Translate provides full
neural MT for en↔ru and en↔nl, still 100% offline.

</executive_summary>

<functional_requirements>

**Translation Memory Management**
- Import/export TM in TMX 1.4 format; language-region codes (`en-US`) and
  reversed tu direction handled on import; optional simultaneous import of
  the reverse direction.
- Exact-match and fuzzy-match retrieval ranked by match percentage
  (word-level Levenshtein), with FTS5 candidate pre-filtering.
- Learn-on-confirm: every segment confirmed in the editor is stored as a TM
  unit (origin `editor`).
- Paired-corpus learning: upload source + target `.txt`; sentence alignment
  (line-based or Gale–Church-style length DP) populates the TM (origin
  `corpus`) and retrains the lexicon.
- Concordance search across TM source and target text.
- MateCat-style volume analysis per project: total words, exact matches,
  fuzzy bands (75–99%, 50–74%), repetitions, new words.
- *(roadmap)* TM maintenance UI (edit/delete/merge units), multiple TMs per
  project with penalties, ICE/context matches.

**File Format Support**
- Import/export **XLIFF 1.2 and 2.0** with inline tags (`g`, `x`, `ph`,
  `bpt`/`ept`, `pc`, …) preserved on round-trip; broken user-entered markup
  degrades safely to escaped text rather than corrupting the file.
- Import plain **`.txt`** with automatic sentence segmentation (EN/RU/NL
  abbreviation-aware); export translated `.txt`.
- Import/export **TMX 1.4** for TM exchange.
- Other formats (Office, PDF, …) are converted to XLIFF externally (e.g.
  Okapi Rainbow), mirroring MateCat's Filters-based design.
- *(roadmap)* XSD validation with structured import errors; protected
  (non-editable) tag tokens in the editor.

**Translation Workflow**
- Segment grid (source | editable target) with per-segment status: new,
  draft, translated, approved, rejected.
- Suggestion panel per active segment: ranked TM matches with %, best
  machine suggestion with provenance, learned term translations.
- Pre-translation: batch-fill empty segments from the suggestion chain.
- Keyboard flow: `Ctrl+Enter` confirms and jumps to the next segment.
- Copy-source, apply-match, per-project progress tracking.
- *(roadmap)* segment filtering by status/text, auto-propagation of repeats.

**Proofreading and QA**
- Automated checks: empty target, untranslated target, inline-tag mismatch,
  number mismatch (decimal-comma aware, `42.5` ≙ `42,5` for RU/NL),
  leading/trailing whitespace, double spaces, end-punctuation mismatch,
  first-letter capitalization, unusual length ratio, repeated words.
- Glossary compliance: flags source terms whose approved target translation
  is missing.
- ML-assisted omission check: source words with a confidently learned
  translation absent from the target.
- Russian typography: straight quotes vs «guillemets», hyphen vs em dash,
  mixed Latin/Cyrillic script inside words (error).
- Dutch style checks (e.g. formal `u hebt` preference); compound-splitting
  detection *(roadmap: broader rule set)*.
- Optional grammar/style/syntax checking for EN/RU/NL through a
  **self-hosted LanguageTool server** (`MATEDOG_LT_URL`), merged into the
  QA panel; no external network involved.
- Whole-file QA report endpoint + per-segment inline flags in the editor.
- Review workflow: approve/reject states distinct from translated.
- *(roadmap)* Hunspell spell-checking, track changes, inline comments,
  exportable QA report (CSV/HTML).

**User Interface**
- Browser-based editor served from `http://127.0.0.1:8123` (local only by
  default); no installation beyond Python + `pip install`.
- Home dashboard: project list with progress, TMX import, paired-text
  learning, TM status/export, lexicon retraining, glossary entry.
- Editor: segment grid, sticky suggestion/QA sidebar, concordance search,
  pre-translate / QA / export toolbar, color-coded segment states and
  highlighted inline tags.

</functional_requirements>

<technical_architecture>

**Technology stack**
- **Language/runtime:** Python 3.11+ (works on Windows, macOS, Linux).
- **Server:** FastAPI + Uvicorn, single process, bound to `127.0.0.1`.
- **UI:** static single-page app (vanilla JS/CSS, no build step) served by
  the same process; `matedog.bat` / `run.py` launches the server and opens
  the default browser.
- **No external services:** no MySQL/Redis/ActiveMQ equivalents needed at
  laptop scale; SQLite WAL mode covers concurrency.

**Data storage**
- Single **SQLite** database (`%USERPROFILE%\.matedog\matedog.db`):
  projects, files (with original XLIFF for round-trip), segments, TM units,
  learned lexicon, glossary.
- **FTS5** virtual table (unicode61 tokenizer, diacritics-folded) over TM
  source text, trigger-synchronized, for fuzzy-match candidate retrieval.

**Key components** (one module each, `matedog/`)
- `xliff.py` — XLIFF 1.2/2.0 reader/writer; inline tags surface as literal
  placeholder tokens in the editor and are re-parsed into XML on export.
- `tmx.py` — TMX 1.4 reader/writer, region-code and direction tolerant.
- `segmenter.py` — abbreviation-aware sentence splitter (EN/RU/NL).
- `tm.py` — TM store; exact + fuzzy lookup (FTS5 candidates → word-level
  Levenshtein), concordance, per-pair stats.
- `mlx.py` — ML layer: Gale–Church-style corpus alignment, IBM Model 1 EM
  lexicon training, lexicon lookup, conservative fuzzy-match repair.
- `qa.py` — deterministic QA rule pipeline + RU/NL-specific rules +
  LanguageTool HTTP adapter.
- `mt.py` — suggestion chain: TM exact → TM + lexicon repair → Argos
  Translate local NMT (optional import) → lexicon gloss.
- `server.py` — REST API (projects, files, segments, matches, QA, TM,
  corpus learning, glossary, analysis, export) + static UI.

**Integration points**
- **LanguageTool** (optional): local HTTP server, `MATEDOG_LT_URL`.
- **Argos Translate** (optional): `pip install argostranslate` + en↔ru /
  en↔nl model packages; auto-detected at import time.
- Everything else is self-contained.

</technical_architecture>

<implementation_phases>

**Phase 1 — Core editing & TM (implemented)**
- Project management, XLIFF 1.2/2.0 and TXT import, round-trip export.
- Segment editor with states, progress, Ctrl+Enter flow.
- SQLite TM with TMX import/export, exact/fuzzy matching, concordance,
  learn-on-confirm, volume analysis.
- Format QA checks (tags, numbers, whitespace, punctuation, length, …).

**Phase 2 — Learning, MT & terminology (implemented)**
- Paired-corpus import with sentence alignment.
- IBM Model 1 lexicon training; term suggestions; fuzzy-match repair;
  gloss drafts; omission QA check.
- Suggestion chain with optional Argos NMT; batch pre-translation.
- Glossary with QA enforcement; RU/NL-specific QA rules; LanguageTool
  adapter.

**Phase 3 — Depth & polish (roadmap)**
- Hunspell spell-checking (`ru_RU`, `nl_NL`) and richer NL compound checks.
- TM maintenance UI; segment filters; auto-propagation; ICE matches.
- Review mode extras: track changes, comments, exportable QA report.
- Match re-ranking with local sentence embeddings (ONNX Runtime) blended
  with edit distance; per-project adaptation weighting.
- Packaging as a single Windows executable (PyInstaller) and optional
  SQLCipher encryption at rest.

</implementation_phases>

<technical_considerations>

- **Windows compatibility:** pure-Python with binary-wheel-only
  dependencies (FastAPI/uvicorn/pydantic) — no compiler, services, or admin
  rights needed; `matedog.bat` gives one-click startup; data lives under
  `%USERPROFILE%\.matedog`. The same code runs on macOS/Linux.
- **TM matching performance:** brute-force Levenshtein does not scale;
  FTS5 (BM25-ranked, capped candidate set) narrows the search before
  precise word-level Levenshtein scoring. Adequate for hundreds of
  thousands of TM units on laptop hardware.
- **Privacy:** the server binds to localhost by default; no telemetry, no
  cloud calls. The optional NMT and grammar checking are explicitly local
  (Argos models on disk, self-hosted LanguageTool). Back up or hand off TM
  data via TMX export. *(roadmap: SQLCipher at-rest encryption.)*
- **Learning quality scales with data:** IBM Model 1 lexicons are noisy on
  tiny corpora; MIN_PROB/TOP_K thresholds keep only confident entries, and
  repair is deliberately conservative (only word-substitution diffs, all
  differences must be resolvable). Retraining is exposed as an explicit
  action and runs in seconds at laptop scale.
- **RU/NL specifics:** number QA normalizes decimal commas; Russian QA
  enforces typography and detects mixed-script typos; the FTS tokenizer
  folds diacritics for Dutch. Morphological normalization (Snowball
  stemming) for better fuzzy recall on inflected Russian is roadmap work,
  as are compound-aware Dutch checks beyond the current heuristics.

</technical_considerations>

<recommended_libraries>

**In use**
- **Server/UI:** FastAPI, Uvicorn, python-multipart; vanilla JS UI (no
  build toolchain).
- **XLIFF/TMX:** Python stdlib `xml.etree.ElementTree` with custom
  readers/writers (no dependency risk; formats are simple enough).
- **TM algorithms:** SQLite FTS5 (stdlib `sqlite3`) + custom word-level
  Levenshtein; IBM Model 1 EM implemented directly (`mlx.py`).
- **Testing:** pytest + FastAPI TestClient (30 tests).

**Optional, local-only**
- **Argos Translate** (CTranslate2-based) — offline NMT for en↔ru, en↔nl.
- **LanguageTool** (self-hosted JAR) — grammar/style for EN, RU, NL.

**Roadmap**
- `WeCantSpell`-equivalent for Python: `spylls` (pure-Python Hunspell) with
  `ru_RU`/`nl_NL` dictionaries.
- Snowball stemmers (`PyStemmer`) for RU/NL-aware TM indexing.
- ONNX Runtime + a small multilingual sentence-embedding model for
  semantic match re-ranking.
- PyInstaller for single-EXE Windows distribution.

</recommended_libraries>

</specifications>
