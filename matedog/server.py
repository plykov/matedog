"""MateDog HTTP server: REST API + static editor UI. Localhost only by default."""

import os
import sqlite3
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import SUPPORTED_PAIRS, __version__, norm_lang
from . import db, mlx, mt, pdfx, qa, tm, tmx, xliff
from .segmenter import segment_text

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")

app = FastAPI(title="MateDog", version=__version__)


@contextmanager
def get_db():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _check_pair(src: str, tgt: str) -> tuple[str, str]:
    s, t = norm_lang(src), norm_lang(tgt)
    if (s, t) not in SUPPORTED_PAIRS:
        raise HTTPException(400, f"Unsupported language pair {s}->{t}. "
                                 f"Supported: en<->ru, en<->nl")
    return s, t


# ---------- projects ----------

class ProjectIn(BaseModel):
    name: str
    src_lang: str
    tgt_lang: str


@app.post("/api/projects")
def create_project(p: ProjectIn):
    s, t = _check_pair(p.src_lang, p.tgt_lang)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, src_lang, tgt_lang) VALUES (?, ?, ?)",
            (p.name.strip() or "Untitled", s, t))
        conn.commit()
        return {"id": cur.lastrowid, "name": p.name, "src_lang": s, "tgt_lang": t}


@app.get("/api/projects")
def list_projects():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM files f WHERE f.project_id = p.id) AS files,
                      (SELECT COUNT(*) FROM segments s JOIN files f ON s.file_id = f.id
                       WHERE f.project_id = p.id) AS segments,
                      (SELECT COUNT(*) FROM segments s JOIN files f ON s.file_id = f.id
                       WHERE f.project_id = p.id AND s.state IN ('translated','approved')) AS done
               FROM projects p ORDER BY p.id DESC""").fetchall()
        return [dict(r) for r in rows]


@app.get("/api/projects/{pid}")
def get_project(pid: int):
    with get_db() as conn:
        p = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if not p:
            raise HTTPException(404, "Project not found")
        files = conn.execute(
            """SELECT f.id, f.name, f.kind,
                      (SELECT COUNT(*) FROM segments s WHERE s.file_id=f.id) AS segments,
                      (SELECT COUNT(*) FROM segments s WHERE s.file_id=f.id
                       AND s.state IN ('translated','approved')) AS done
               FROM files f WHERE f.project_id=? ORDER BY f.id""", (pid,)).fetchall()
        return dict(p) | {"files": [dict(f) for f in files]}


@app.delete("/api/projects/{pid}")
def delete_project(pid: int):
    with get_db() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        conn.commit()
    return {"ok": True}


# ---------- file import / export ----------

@app.post("/api/projects/{pid}/files")
async def upload_file(pid: int, file: UploadFile = File(...)):
    with get_db() as conn:
        p = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if not p:
            raise HTTPException(404, "Project not found")
        payload = await file.read()
        name = file.filename or "file"
        lower = name.lower()

        if lower.endswith((".xlf", ".xliff")):
            kind = "xliff"
            raw = payload.decode("utf-8", errors="replace")
            try:
                doc = xliff.parse_xliff(raw)
            except Exception as e:
                raise HTTPException(400, f"Invalid XLIFF: {e}")
            units = doc.units
        elif lower.endswith((".txt", ".pdf")):
            if lower.endswith(".pdf"):
                kind = "pdf"
                try:
                    text = pdfx.extract_text(payload)
                except ValueError as e:
                    raise HTTPException(400, str(e))
            else:
                kind = "txt"
                text = payload.decode("utf-8", errors="replace")
            sources = segment_text(text)
            raw = xliff.make_xliff_from_segments(name, p["src_lang"], p["tgt_lang"], sources)
            units = xliff.parse_xliff(raw).units
        else:
            raise HTTPException(400, "Only .xliff, .xlf, .txt and .pdf files are supported. "
                                     "Convert other formats to XLIFF first.")

        if not units:
            raise HTTPException(400, "No translatable segments found in file")

        cur = conn.execute(
            "INSERT INTO files (project_id, name, kind, original) VALUES (?, ?, ?, ?)",
            (pid, name, kind, raw))
        fid = cur.lastrowid
        for i, u in enumerate(units):
            conn.execute(
                "INSERT INTO segments (file_id, seq, unit_id, source, target, state) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (fid, i, u.unit_id, u.source, u.target,
                 u.state if u.target else "new"))
        conn.commit()
        return {"file_id": fid, "segments": len(units)}


@app.get("/api/files/{fid}/export")
def export_file(fid: int):
    with get_db() as conn:
        f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not f:
            raise HTTPException(404, "File not found")
        segs = conn.execute(
            "SELECT unit_id, target, state FROM segments WHERE file_id=? ORDER BY seq",
            (fid,)).fetchall()
        p = conn.execute(
            "SELECT * FROM projects WHERE id=?", (f["project_id"],)).fetchone()
        translations = {s["unit_id"]: (s["target"], s["state"]) for s in segs}
        out = xliff.generate_xliff(f["original"], translations, p["tgt_lang"])
        base = os.path.splitext(f["name"])[0]
        return Response(
            out, media_type="application/xml",
            headers={"Content-Disposition":
                     f'attachment; filename="{base}.{p["tgt_lang"]}.xliff"'})


@app.get("/api/files/{fid}/export-txt")
def export_txt(fid: int):
    with get_db() as conn:
        f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not f:
            raise HTTPException(404, "File not found")
        segs = conn.execute(
            "SELECT source, target FROM segments WHERE file_id=? ORDER BY seq",
            (fid,)).fetchall()
        text = "\n".join((s["target"] or s["source"]) for s in segs)
        base = os.path.splitext(f["name"])[0]
        return Response(
            text, media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{base}.translated.txt"'})


# ---------- segments / editor ----------

@app.get("/api/files/{fid}/segments")
def list_segments(fid: int):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, seq, source, target, state FROM segments "
            "WHERE file_id=? ORDER BY seq", (fid,)).fetchall()
        return [dict(r) for r in rows]


class SegmentIn(BaseModel):
    target: str | None = None
    state: str | None = None


def _seg_context(conn: sqlite3.Connection, sid: int):
    row = conn.execute(
        """SELECT s.*, p.src_lang, p.tgt_lang FROM segments s
           JOIN files f ON s.file_id = f.id JOIN projects p ON f.project_id = p.id
           WHERE s.id=?""", (sid,)).fetchone()
    if not row:
        raise HTTPException(404, "Segment not found")
    return row


@app.patch("/api/segments/{sid}")
def update_segment(sid: int, body: SegmentIn):
    with get_db() as conn:
        row = _seg_context(conn, sid)
        target = body.target if body.target is not None else row["target"]
        state = body.state or row["state"]
        if state not in ("new", "draft", "translated", "approved", "rejected"):
            raise HTTPException(400, "Invalid state")
        conn.execute(
            "UPDATE segments SET target=?, state=?, updated_at=datetime('now') WHERE id=?",
            (target, state, sid))
        conn.commit()
        # Learning: confirmed segments feed the TM.
        if state in ("translated", "approved") and target.strip():
            tm.add_unit(conn, row["src_lang"], row["tgt_lang"],
                        xliff.strip_tags(row["source"]), xliff.strip_tags(target),
                        origin="editor")
        issues = qa.check_segment(row["source"], target, row["src_lang"], row["tgt_lang"],
                                  glossary=_glossary(conn, row["src_lang"], row["tgt_lang"]))
        return {"ok": True, "qa": issues}


@app.get("/api/segments/{sid}/matches")
def segment_matches(sid: int):
    with get_db() as conn:
        row = _seg_context(conn, sid)
        src, tgt = row["src_lang"], row["tgt_lang"]
        plain = xliff.strip_tags(row["source"])
        matches = tm.lookup(conn, src, tgt, plain, limit=4, min_score=0.5)
        suggestion = mt.suggest(conn, src, tgt, plain)
        terms = []
        for w in set(tm.tokenize(plain)):
            found = mlx.lexicon_lookup(conn, src, tgt, w)
            if found:
                terms.append({"word": w, "translations": [t for t, _ in found[:3]]})
        return {"tm": matches, "mt": suggestion, "terms": terms[:12]}


@app.get("/api/segments/{sid}/qa")
def segment_qa(sid: int):
    with get_db() as conn:
        row = _seg_context(conn, sid)
        issues = qa.check_segment(row["source"], row["target"],
                                  row["src_lang"], row["tgt_lang"],
                                  glossary=_glossary(conn, row["src_lang"], row["tgt_lang"]))
        issues += qa.languagetool_check(xliff.strip_tags(row["target"]), row["tgt_lang"])
        return issues


@app.post("/api/files/{fid}/qa")
def file_qa(fid: int):
    with get_db() as conn:
        f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not f:
            raise HTTPException(404, "File not found")
        p = conn.execute("SELECT * FROM projects WHERE id=?", (f["project_id"],)).fetchone()
        gl = _glossary(conn, p["src_lang"], p["tgt_lang"])
        report = []
        for s in conn.execute(
                "SELECT id, seq, source, target FROM segments WHERE file_id=? ORDER BY seq",
                (fid,)):
            issues = qa.check_segment(s["source"], s["target"],
                                      p["src_lang"], p["tgt_lang"], glossary=gl)
            if issues:
                report.append({"segment_id": s["id"], "seq": s["seq"], "issues": issues})
        return report


@app.post("/api/files/{fid}/pretranslate")
def pretranslate(fid: int, min_percent: int = 50):
    """Fill empty segments from TM/MT, MateCat-style pre-translation.

    Suggestions below min_percent (e.g. rough lexicon glosses) are skipped;
    they remain available per-segment in the suggestions panel.
    """
    with get_db() as conn:
        f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not f:
            raise HTTPException(404, "File not found")
        p = conn.execute("SELECT * FROM projects WHERE id=?", (f["project_id"],)).fetchone()
        filled = 0
        for s in conn.execute(
                "SELECT id, source FROM segments WHERE file_id=? AND state='new' "
                "AND target=''", (fid,)).fetchall():
            sug = mt.suggest(conn, p["src_lang"], p["tgt_lang"], xliff.strip_tags(s["source"]))
            if sug and sug["percent"] >= min_percent:
                conn.execute("UPDATE segments SET target=?, state='draft' WHERE id=?",
                             (sug["text"], s["id"]))
                filled += 1
        conn.commit()
        return {"filled": filled}


# ---------- TM / corpus / ML ----------

@app.post("/api/tm/import")
async def tm_import(src_lang: str = Form(...), tgt_lang: str = Form(...),
                    both_directions: bool = Form(True),
                    file: UploadFile = File(...)):
    s, t = _check_pair(src_lang, tgt_lang)
    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        pairs = tmx.parse_tmx(raw, s, t)
    except Exception as e:
        raise HTTPException(400, f"Invalid TMX: {e}")
    with get_db() as conn:
        added = tm.add_units(conn, s, t, pairs, origin="tmx")
        if both_directions:
            tm.add_units(conn, t, s, [(b, a) for a, b in pairs], origin="tmx")
    return {"pairs_found": len(pairs), "added": added}


@app.get("/api/tm/export")
def tm_export(src_lang: str, tgt_lang: str):
    s, t = _check_pair(src_lang, tgt_lang)
    with get_db() as conn:
        units = tm.all_units(conn, s, t)
    out = tmx.generate_tmx(units, s, t)
    return Response(out, media_type="application/xml",
                    headers={"Content-Disposition":
                             f'attachment; filename="matedog-{s}-{t}.tmx"'})


@app.post("/api/tm/pair-import")
async def pair_import(src_lang: str = Form(...), tgt_lang: str = Form(...),
                      train: bool = Form(True),
                      src_file: UploadFile = File(...),
                      tgt_file: UploadFile = File(...)):
    """Learn from a paired corpus: align sentences, store in TM, train lexicon."""
    s, t = _check_pair(src_lang, tgt_lang)
    src_text = (await src_file.read()).decode("utf-8", errors="replace")
    tgt_text = (await tgt_file.read()).decode("utf-8", errors="replace")
    pairs = mlx.align_corpus(src_text, tgt_text)
    if not pairs:
        raise HTTPException(400, "Could not align the two files")
    with get_db() as conn:
        added = tm.add_units(conn, s, t, pairs, origin="corpus")
        lex = mlx.train_lexicon(conn, s, t) if train else 0
    return {"aligned_pairs": len(pairs), "added_to_tm": added, "lexicon_entries": lex}


@app.post("/api/ml/train")
def ml_train(src_lang: str, tgt_lang: str):
    s, t = _check_pair(src_lang, tgt_lang)
    with get_db() as conn:
        n = mlx.train_lexicon(conn, s, t)
    return {"lexicon_entries": n}


@app.get("/api/tm/concordance")
def tm_concordance(src_lang: str, tgt_lang: str, q: str):
    s, t = _check_pair(src_lang, tgt_lang)
    with get_db() as conn:
        return tm.concordance(conn, s, t, q)


@app.get("/api/tm/stats")
def tm_stats():
    with get_db() as conn:
        return {"pairs": tm.stats(conn), "providers": mt.providers_status()}


# ---------- glossary ----------

def _glossary(conn: sqlite3.Connection, src: str, tgt: str) -> list[dict]:
    rows = conn.execute(
        "SELECT src_term, tgt_term FROM glossary WHERE src_lang=? AND tgt_lang=?",
        (src, tgt)).fetchall()
    return [dict(r) for r in rows]


class GlossaryIn(BaseModel):
    src_lang: str
    tgt_lang: str
    src_term: str
    tgt_term: str


@app.post("/api/glossary")
def glossary_add(g: GlossaryIn):
    s, t = _check_pair(g.src_lang, g.tgt_lang)
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO glossary (src_lang, tgt_lang, src_term, tgt_term) "
            "VALUES (?, ?, ?, ?)", (s, t, g.src_term.strip(), g.tgt_term.strip()))
        conn.commit()
    return {"ok": True}


@app.get("/api/glossary")
def glossary_list(src_lang: str, tgt_lang: str):
    s, t = _check_pair(src_lang, tgt_lang)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, src_term, tgt_term FROM glossary WHERE src_lang=? AND tgt_lang=?",
            (s, t)).fetchall()
        return [dict(r) for r in rows]


# ---------- analysis (MateCat-style volume analysis) ----------

@app.get("/api/projects/{pid}/analysis")
def analysis(pid: int):
    with get_db() as conn:
        p = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if not p:
            raise HTTPException(404, "Project not found")
        bands = {"exact": 0, "fuzzy_75_99": 0, "fuzzy_50_74": 0, "new": 0, "repetition": 0}
        words = 0
        seen: set[str] = set()
        for s in conn.execute(
                """SELECT s.source FROM segments s JOIN files f ON s.file_id=f.id
                   WHERE f.project_id=?""", (pid,)):
            plain = xliff.strip_tags(s["source"])
            w = len(tm.tokenize(plain))
            words += w
            key = " ".join(tm.tokenize(plain))
            if key in seen:
                bands["repetition"] += w
                continue
            seen.add(key)
            matches = tm.lookup(conn, p["src_lang"], p["tgt_lang"], plain,
                                limit=1, min_score=0.5)
            pct = matches[0]["percent"] if matches else 0
            if pct >= 100:
                bands["exact"] += w
            elif pct >= 75:
                bands["fuzzy_75_99"] += w
            elif pct >= 50:
                bands["fuzzy_50_74"] += w
            else:
                bands["new"] += w
        return {"total_words": words, "bands": bands}


# ---------- UI ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(UI_DIR, "index.html"))


app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")


def main():
    import uvicorn
    host = os.environ.get("MATEDOG_HOST", "127.0.0.1")
    port = int(os.environ.get("MATEDOG_PORT", "8123"))
    print(f"MateDog running at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
