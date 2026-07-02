"""SQLite storage layer. Single-file database, FTS5 index for TM candidate retrieval."""

import os
import sqlite3

DEFAULT_DB_PATH = os.environ.get("MATEDOG_DB", os.path.join(os.path.expanduser("~"), ".matedog", "matedog.db"))

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    src_lang TEXT NOT NULL,
    tgt_lang TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,              -- 'xliff' | 'txt'
    original TEXT NOT NULL,          -- original file content, for round-trip export
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    unit_id TEXT NOT NULL DEFAULT '',   -- trans-unit id in the original XLIFF
    source TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'new',  -- new | draft | translated | approved | rejected
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_segments_file ON segments(file_id, seq);

CREATE TABLE IF NOT EXISTS tm_units (
    id INTEGER PRIMARY KEY,
    src_lang TEXT NOT NULL,
    tgt_lang TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'manual',  -- manual | tmx | corpus | editor
    use_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(src_lang, tgt_lang, source, target)
);
CREATE INDEX IF NOT EXISTS idx_tm_langs ON tm_units(src_lang, tgt_lang);

CREATE VIRTUAL TABLE IF NOT EXISTS tm_fts USING fts5(
    source,
    content='tm_units',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS tm_ai AFTER INSERT ON tm_units BEGIN
    INSERT INTO tm_fts(rowid, source) VALUES (new.id, new.source);
END;
CREATE TRIGGER IF NOT EXISTS tm_ad AFTER DELETE ON tm_units BEGIN
    INSERT INTO tm_fts(tm_fts, rowid, source) VALUES ('delete', old.id, old.source);
END;
CREATE TRIGGER IF NOT EXISTS tm_au AFTER UPDATE ON tm_units BEGIN
    INSERT INTO tm_fts(tm_fts, rowid, source) VALUES ('delete', old.id, old.source);
    INSERT INTO tm_fts(rowid, source) VALUES (new.id, new.source);
END;

CREATE TABLE IF NOT EXISTS lexicon (
    src_lang TEXT NOT NULL,
    tgt_lang TEXT NOT NULL,
    src_word TEXT NOT NULL,
    tgt_word TEXT NOT NULL,
    prob REAL NOT NULL,
    PRIMARY KEY (src_lang, tgt_lang, src_word, tgt_word)
);

CREATE TABLE IF NOT EXISTS glossary (
    id INTEGER PRIMARY KEY,
    src_lang TEXT NOT NULL,
    tgt_lang TEXT NOT NULL,
    src_term TEXT NOT NULL,
    tgt_term TEXT NOT NULL,
    UNIQUE(src_lang, tgt_lang, src_term, tgt_term)
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    path = path or DEFAULT_DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
