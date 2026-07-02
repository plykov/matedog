# MateDog — Technical Specifications

A Windows desktop CAT (Computer-Assisted Translation) tool, in the spirit of
[matecat.com](https://www.matecat.com), scoped initially to the **English↔Russian**
and **English↔Dutch** language pairs.

<specifications>

<executive_summary>

MateDog is a native Windows desktop application that gives professional
translators and reviewers a MateCat-style workbench — segment-by-segment
editing against a bilingual source file, live translation-memory (TM)
leveraging, machine-translation (MT) pre-translation, and integrated
quality-assurance (QA) checks — without requiring a server or constant
internet connection.

The application imports industry-standard **XLIFF** files for translation
and **TMX** files for translation memory, stores all project and TM data
locally in an embedded **SQLite** database, and offers pluggable MT and
grammar-checking backends so translators can work fully offline for core
editing and opt in to cloud services (MT suggestions, cloud grammar
checking) only when desired.

The technical approach: **.NET 8 + WPF** for the desktop shell (mature,
native-Windows, long-term-supported), a custom **XLIFF/TMX parser** built
on `System.Xml.Linq`, a **trigram-indexed fuzzy-matching engine** backed by
SQLite FTS5 for TM lookups, and **LanguageTool** (self-hosted) plus
**Hunspell** dictionaries for Russian/Dutch grammar, style and spell
checking. A lightweight ML layer (local sentence embeddings via ONNX
Runtime) is planned as a later phase to improve fuzzy-match ranking and
learn from translator corrections over time.

</executive_summary>

<functional_requirements>

**Translation Memory Management**
- Import/export TM in TMX 1.4b format (and export in the same for
  interoperability with other CAT tools).
- Store aligned source/target segment pairs with metadata (creation date,
  author, project, domain/subject field, last-used date).
- Support multiple TMs per project (project TM, main/reference TM,
  read-only TM) with configurable lookup order and penalties.
- Exact-match and fuzzy-match retrieval (configurable threshold, e.g.
  ≥70%) against the active TM(s), ranked by match percentage.
- Auto-propagate 100%/exact matches to identical repeated segments within
  a project (with translator confirmation option).
- Concordance search: free-text search across TM source and target
  content.
- TM maintenance: edit, delete, merge duplicate entries; de-duplication on
  import.
- Segment-level context matching (ICE / 101% matches using preceding
  segment as additional context, matching MateCat/SDL conventions).

**File Format Support**
- Import/export **XLIFF 1.2 and 2.0** as the primary bilingual working
  format, preserving all inline tags, placeholders, and metadata on
  round-trip (import → edit → export must not corrupt markup).
- Import/export **TMX 1.4b** for translation memory exchange.
- Validate files against the relevant XLIFF/TMX XSD on import and surface
  actionable errors for malformed files.
- Preserve non-translatable content (tags, placeholders, `mrk`/`bpt`/`ept`
  elements) as protected, non-editable tokens in the segment editor.

**Translation Workflow**
- Segment grid (source/target bilingual table) as the primary editing
  surface, with segment status (untranslated, draft, translated,
  approved, rejected).
- MT pre-translation: batch-populate empty segments with MT suggestions
  the translator can accept, edit, or reject.
- TM/MT suggestion panel showing ranked candidates with match % and
  origin (TM vs. MT).
- Glossary/termbase lookup and inline terminology highlighting in the
  source segment.
- Auto-save and project-level save/restore (crash recovery).
- Filter/search segments by status, match %, or text content.
- Project-level progress tracking (word counts, % translated/approved).

**Proofreading and QA**
- Automated QA checks: empty target, untranslated segment, tag
  mismatch/loss, number mismatch, inconsistent terminology, duplicate
  source with inconsistent targets, leading/trailing whitespace,
  double spaces, punctuation mismatch (e.g. missing sentence-final
  punctuation).
- Language-specific **grammar, syntax, and style checking** for Russian
  and Dutch target text (and English source, secondarily), surfaced as
  inline warnings/underlines in the segment editor, similar to a spell
  checker.
- Spell-checking against Russian and Dutch dictionaries.
- A dedicated QA report view: list of all flagged issues across the
  project, filterable by severity/category, with jump-to-segment
  navigation.
- Reviewer/proofreading mode: track changes on target text, inline
  comments per segment, approve/reject workflow separate from
  translation.
- Export a QA/review report (CSV or HTML) for delivery to clients or PMs.

**User Interface**
- Windows-native desktop application with a segment-grid editing pane,
  collapsible TM/MT/glossary side panel, and a QA issues panel — matching
  familiar CAT-tool ergonomics (MateCat, memoQ, Trados).
- Keyboard-first segment navigation (next/previous segment, confirm and
  move on, insert TM match, insert tag).
- Visual match-quality indicators (color-coded % match badges).
- Project dashboard: list of projects, per-project language pair, word
  counts, progress.
- Settings UI for configuring TM sources, MT provider credentials, QA
  rule severity, and dictionaries.

</functional_requirements>

<technical_architecture>

**Technology stack**
- **Language/runtime:** C# on .NET 8 (LTS), Windows-only target
  (`net8.0-windows`).
- **UI framework:** WPF with the MVVM pattern
  (`CommunityToolkit.Mvvm`), using standard WPF `DataGrid`/virtualized
  list controls for the segment grid to keep large files responsive.
- **Packaging:** MSIX or an Inno Setup/Squirrel installer; code-signed
  build for distribution outside the Microsoft Store if needed.

**Data storage**
- **SQLite** (via `Microsoft.Data.Sqlite`) as the single embedded
  database for: project metadata, segments, TM entries, glossary
  entries, and QA results.
- SQLite **FTS5** virtual tables (trigram tokenizer) over TM source text
  to provide fast candidate pre-filtering before exact fuzzy scoring.
- Optional **SQLCipher**-based encryption at rest for TM/project
  databases, since TM content is frequently client-confidential.

**Key components**
- **Import/Export Engine** — parses XLIFF and TMX via `System.Xml.Linq`
  against the OASIS schemas; produces an internal segment model; exports
  back to XLIFF/TMX preserving markup fidelity.
- **TM Engine** — owns TM storage, FTS5-based candidate retrieval,
  Levenshtein/Damerau-Levenshtein scoring for final match percentage, and
  TM maintenance (dedupe, merge).
- **MT Provider Abstraction** — a common `IMachineTranslationProvider`
  interface with adapters for cloud MT APIs, so providers can be swapped
  or run offline-only.
- **QA Engine** — a rule pipeline combining format-agnostic checks (tag
  consistency, numbers, duplicates) with pluggable language-specific
  checkers (grammar/style/spelling) run per target language.
- **Editor/Workbench UI** — the WPF segment grid, suggestion panel,
  and QA panel, all bound via MVVM to the above engines.
- **Project Manager** — project creation, language-pair configuration,
  TM/glossary attachment, and progress tracking.

**Integration points**
- Cloud MT APIs (optional, user-configured, credentials stored via
  Windows Credential Manager/DPAPI, never written to disk in plaintext).
- Self-hosted **LanguageTool** server (bundled JRE + LanguageTool JAR,
  launched as a local background process) accessed over local HTTP for
  grammar/style checks — no external network call required.
- Hunspell dictionaries loaded locally for spell-checking.

**File format handlers**
- `XliffReader`/`XliffWriter` — round-trip XLIFF 1.2/2.0, protecting
  inline elements as opaque placeholder tokens in the editable segment
  text.
- `TmxReader`/`TmxWriter` — round-trip TMX 1.4b translation units.
- Both validated against bundled XSDs with structured error reporting on
  import failure.

</technical_architecture>

<implementation_phases>

**Phase 1 — Core editing & TM (MVP)**
- Project creation and XLIFF 1.2/2.0 import/export with markup-fidelity
  round-trip.
- Segment grid editor with status tracking and auto-save.
- SQLite-backed TM store; TMX import/export.
- Exact-match and fuzzy-match (Levenshtein-based) TM retrieval with
  FTS5 candidate pre-filtering; auto-propagation of exact repeats.
- Basic format QA checks: empty target, tag mismatch, number mismatch,
  duplicate source/inconsistent target.

**Phase 2 — MT, terminology & workflow**
- Pluggable MT provider integration and batch pre-translation.
- Glossary/termbase support with inline terminology highlighting.
- Concordance search across TM.
- QA report view (filterable, jump-to-segment) and export (CSV/HTML).
- Reviewer mode: track changes, inline comments, approve/reject.

**Phase 3 — Language-specific QA & ML improvements**
- LanguageTool integration for Russian and Dutch grammar/style/syntax
  checking, surfaced inline in the editor.
- Hunspell spell-checking for Russian and Dutch.
- TM match-ranking improvements via local sentence embeddings (ONNX
  Runtime) blended with edit-distance scoring, to better rank
  near-matches beyond pure string similarity.
- Learn-from-corrections loop: track translator edits to MT/TM
  suggestions to bias future ranking/glossary suggestions per project.
- TM database encryption at rest (SQLCipher) as an optional setting.

</implementation_phases>

<technical_considerations>

- **Windows compatibility:** target .NET 8 LTS with WPF for native
  look/feel and long support horizon; avoid any POSIX-only dependencies;
  bundle a JRE for LanguageTool so users don't need a separate Java
  install.
- **Performance of TM matching:** brute-force Levenshtein against every
  TM entry does not scale past a few thousand segments. Use SQLite FTS5
  trigram indexing to narrow candidates to a small set, then run precise
  fuzzy scoring only on that set; parallelize scoring with the Task
  Parallel Library for large batch pre-translation runs.
- **Data security and privacy:** TM/project content is often
  client-confidential — default to fully local processing; require
  explicit opt-in before any segment text is sent to a cloud MT or
  grammar API; store API keys via Windows Credential Manager/DPAPI, not
  in plaintext config files; offer at-rest database encryption
  (SQLCipher) as an option.
- **Scalability of translation memory:** schema should comfortably index
  millions of TM entries per database; support both per-project and
  shared/global TMs; design FTS5 indexes and pagination so UI responsiveness
  doesn't degrade as TM size grows.
- **Language-specific processing for RU and NL:** Russian benefits from
  morphological normalization (case/inflection) for better fuzzy-match
  and terminology recall — plan for a stemmer/lemmatizer (e.g. a Snowball
  Russian stemmer) rather than raw string matching alone. Dutch has
  productive compounding, which affects tokenization for TM indexing and
  spell-checking — use a Dutch-aware tokenizer/stemmer (Snowball Dutch)
  and a compound-aware Hunspell dictionary (`nl_NL`). Both languages
  should use LanguageTool's respective RU/NL rule sets for grammar/style,
  acknowledging RU rule coverage in LanguageTool is less mature than NL
  and may need supplementary rules or a commercial fallback later.

</technical_considerations>

<recommended_libraries>

- **XLIFF/TMX parsing:** `System.Xml.Linq` with custom readers/writers
  against the OASIS XLIFF 1.2/2.0 and TMX 1.4b XSDs (no mature
  off-the-shelf .NET library covers both robustly); use the Okapi
  Framework (Java, invoked out-of-process) as a reference implementation
  or interoperability fallback for edge-case format conversion.
- **Translation memory algorithms:** SQLite `FTS5` (trigram tokenizer)
  for candidate retrieval; `F23.StringSimilarity` (NuGet) for
  Levenshtein/Damerau-Levenshtein fuzzy scoring; ONNX Runtime +a small
  multilingual sentence-embedding model for later semantic re-ranking.
- **Grammar and style checking (Russian and Dutch):** self-hosted
  **LanguageTool** (open-source, supports `ru` and `nl`) via its local
  HTTP API; **Hunspell** dictionaries (`ru_RU`, `nl_NL`) via `NHunspell`
  or `WeCantSpell.Hunspell` for spell-checking; Snowball stemmers
  (Russian, Dutch) for TM tokenization/normalization.
- **UI framework:** WPF (.NET 8) with `CommunityToolkit.Mvvm` for MVVM
  plumbing; standard WPF `DataGrid` (virtualized) for the segment grid.
- **Database/storage:** `Microsoft.Data.Sqlite` (or `sqlite-net-pcl`) as
  the embedded store; optional `SQLCipher` for encryption at rest.

</recommended_libraries>

</specifications>
