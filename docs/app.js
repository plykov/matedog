"use strict";

const $ = (sel) => document.querySelector(sel);
const PAIRS = [["en","ru"],["ru","en"],["en","nl"],["nl","en"]];
const LANG_NAMES = {en:"English", ru:"Russian", nl:"Dutch"};

let S = null;              // Store.state, set on init
let currentProject = null;
let currentFile = null;
let activeSegId = null;

// ---------- helpers ----------

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.hidden = true), 3500);
}

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderText(s) {
  return esc(s).replace(/&lt;[^&]*?&gt;/g, (m) => `<span class="tag">${m}</span>`);
}

function pairLabel(s, t) { return `${LANG_NAMES[s]} → ${LANG_NAMES[t]}`; }

function fillPairSelects() {
  document.querySelectorAll(".pair-select").forEach((sel) => {
    sel.innerHTML = PAIRS.map((p) =>
      `<option value="${p[0]}:${p[1]}">${pairLabel(p[0], p[1])}</option>`).join("");
  });
}

function show(viewId) {
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== viewId));
  window.scrollTo(0, 0);
}

function download(name, text, type = "application/xml") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

const fileSegments = (fid) =>
  S.segments.filter((x) => x.fileId === fid).sort((a, b) => a.seq - b.seq);
const projectGlossary = (p) =>
  S.glossary.filter((g) => g.s === p.s && g.t === p.t);

// ---------- home ----------

function showHome() {
  show("view-home");
  $("#header-info").textContent = "runs in your browser · en↔ru · en↔nl";
  const items = S.projects.slice().reverse().map((p) => {
    const files = S.files.filter((f) => f.projectId === p.id);
    const segs = S.segments.filter((x) => files.some((f) => f.id === x.fileId));
    const done = segs.filter((x) => ["translated", "approved"].includes(x.state)).length;
    return `<div class="plist-item">
      <a data-open-project="${p.id}">${esc(p.name)}</a>
      <span class="badge">${p.s} → ${p.t}</span>
      <span class="muted">${files.length} file(s), ${done}/${segs.length} segments</span>
      <div class="progress"><div style="width:${segs.length ? (100*done/segs.length) : 0}%"></div></div>
      <span class="grow"></span>
      <button class="del" data-del-project="${p.id}">✕</button>
    </div>`;
  });
  $("#project-list").innerHTML = items.join("") ||
    `<div class="muted">No projects yet — create one above.</div>`;
  refreshTmStats();
}

function refreshTmStats() {
  const counts = {};
  for (const u of S.tm) {
    const k = `${u.s} → ${u.t}`;
    counts[k] = (counts[k] || 0) + 1;
  }
  const rows = Object.entries(counts).map(([k, n]) => `<div>${k}: <b>${n}</b> TM units</div>`);
  $("#tm-stats").innerHTML = (rows.join("") || `<div class="muted">TM is empty.</div>`) +
    `<div class="muted">Suggestions: TM + learned lexicon (all offline, in-browser)</div>`;
}

// ---------- project view ----------

function openProject(id) {
  const p = S.projects.find((x) => x.id === id);
  if (!p) return;
  currentProject = p;
  show("view-project");
  $("#proj-title").textContent = `${p.name} (${pairLabel(p.s, p.t)})`;
  const files = S.files.filter((f) => f.projectId === id);
  $("#file-list").innerHTML = files.map((f) => {
    const segs = fileSegments(f.id);
    const done = segs.filter((x) => ["translated", "approved"].includes(x.state)).length;
    return `<div class="flist-item">
      <a data-open-file="${f.id}">${esc(f.name)}</a>
      <span class="badge">${f.kind}</span>
      <span class="muted">${done}/${segs.length} segments</span>
      <div class="progress"><div style="width:${segs.length ? (100*done/segs.length) : 0}%"></div></div>
    </div>`;
  }).join("") || `<div class="muted">Upload an XLIFF or plain-text file to start translating.</div>`;

  // Volume analysis is TM-lookup-heavy: run it after the view has painted.
  $("#analysis").innerHTML = files.length
    ? `<div class="muted" style="margin-top:10px">Analyzing…</div>` : "";
  if (files.length) {
    setTimeout(() => {
      if (currentProject !== p) return;
      const bands = { exact: 0, f75: 0, f50: 0, rep: 0, nw: 0 };
      let words = 0;
      const seen = new Set();
      for (const f of files) {
        for (const seg of fileSegments(f.id)) {
          const plain = Engine.stripTags(seg.source);
          const toks = Engine.tokenize(plain);
          words += toks.length;
          const key = toks.join(" ");
          if (seen.has(key)) { bands.rep += toks.length; continue; }
          seen.add(key);
          const m = Engine.tmLookup(S, p.s, p.t, plain, 1, 0.5);
          const pct = m.length ? m[0].percent : 0;
          if (pct >= 100) bands.exact += toks.length;
          else if (pct >= 75) bands.f75 += toks.length;
          else if (pct >= 50) bands.f50 += toks.length;
          else bands.nw += toks.length;
        }
      }
      $("#analysis").innerHTML = `<div class="muted" style="margin-top:10px">
        Analysis: ${words} words — ${bands.exact} exact · ${bands.f75} fuzzy 75–99% ·
        ${bands.f50} fuzzy 50–74% · ${bands.rep} repetitions · ${bands.nw} new</div>`;
    }, 0);
  }
}

// ---------- editor ----------

function openEditor(fileId) {
  const f = S.files.find((x) => x.id === fileId);
  if (!f) return;
  currentFile = f;
  show("view-editor");
  $("#editor-file").textContent = f.name;
  $("#concord-panel").hidden = true;
  renderSegments();
}

let renderJob = 0;

function renderSegments() {
  const segs = fileSegments(currentFile.id);
  updateProgress();
  // Render the first screenful synchronously, the rest in idle chunks so
  // large files (e.g. imported PDFs) don't block the UI.
  const FIRST = 150, CHUNK = 300;
  const job = ++renderJob;
  const box = $("#segments");
  box.innerHTML = segs.slice(0, FIRST).map(segHtml).join("");
  let i = FIRST;
  const appendChunk = () => {
    if (job !== renderJob || i >= segs.length) return;
    box.insertAdjacentHTML("beforeend", segs.slice(i, i + CHUNK).map(segHtml).join(""));
    i += CHUNK;
    requestAnimationFrame(appendChunk);
  };
  if (i < segs.length) requestAnimationFrame(appendChunk);
  $("#matches").innerHTML = `<div class="muted">Select a segment.</div>`;
  $("#qa-issues").innerHTML = "";
  activeSegId = null;
}

function segHtml(s) {
  return `
  <div class="seg state-${s.state}" id="seg-${s.id}" data-seg="${s.id}">
    <div class="num">${s.seq + 1}</div>
    <div class="src">${renderText(s.source)}</div>
    <div><textarea id="tgt-${s.id}" data-seg-ta="${s.id}">${esc(s.target)}</textarea></div>
    <div class="ops">
      <button class="secondary" data-copy="${s.id}">Copy source</button>
      <button data-state="translated" data-seg-btn="${s.id}">Translated ✓</button>
      <button class="secondary" data-state="approved" data-seg-btn="${s.id}">Approve ✓✓</button>
      <button class="secondary" data-state="rejected" data-seg-btn="${s.id}">Reject</button>
    </div>
    <div class="qa-flags" id="qa-${s.id}"></div>
  </div>`;
}

function updateProgress() {
  const segs = fileSegments(currentFile.id);
  const done = segs.filter((s) => ["translated", "approved"].includes(s.state)).length;
  $("#editor-progress").textContent = `${done}/${segs.length} confirmed`;
}

function activateSeg(id) {
  if (activeSegId === id) return;
  activeSegId = id;
  document.querySelectorAll(".seg.active").forEach((el) => el.classList.remove("active"));
  $(`#seg-${id}`)?.classList.add("active");
  // Defer suggestion lookup past the paint so focusing a segment (and the
  // keyboard opening on mobile) never waits on TM work.
  setTimeout(() => {
    if (activeSegId !== id) return;
    const seg = S.segments.find((x) => x.id === id);
    const p = currentProject;
    const plain = Engine.stripTags(seg.source);

    let html = "";
    const tmMatches = Engine.tmLookup(S, p.s, p.t, plain, 4, 0.5);
    const mt = Engine.mtSuggest(S, p.s, p.t, plain, tmMatches);
    if (mt) {
      html += `<div class="match"><span class="pct">${mt.percent}%</span>
        <span class="muted">${esc(mt.provider)}</span>
        <button class="apply" data-apply="${id}" data-text="${esc(mt.text)}">Apply</button>
        <div>${esc(mt.text)}</div></div>`;
    }
    for (const t of tmMatches) {
      html += `<div class="match"><span class="pct">${t.percent}%</span>
        <span class="muted">TM · ${esc(t.origin)}</span>
        <button class="apply" data-apply="${id}" data-text="${esc(t.target)}">Apply</button>
        <div>${esc(t.target)}</div>
        <div class="match-src">${renderText(t.source)}</div></div>`;
    }
    const terms = [];
    for (const w of new Set(Engine.tokenize(plain))) {
      const found = Engine.lexiconLookup(S, p.s, p.t, w);
      if (found.length) terms.push({ word: w, translations: found.slice(0, 3).map(([x]) => x) });
      if (terms.length >= 12) break;
    }
    if (terms.length) {
      html += `<h3 style="margin-top:10px">Learned terms</h3>` + terms.map((t) =>
        `<span class="term">${esc(t.word)} → ${esc(t.translations.join(", "))}</span>`).join("");
    }
    $("#matches").innerHTML = html ||
      `<div class="muted">No suggestions yet — import a TMX or paired texts on the home screen.</div>`;
    runSegQa(id, true);
  }, 0);
}

function runSegQa(id, sidebar) {
  const seg = S.segments.find((x) => x.id === id);
  const issues = Engine.checkSegment(S, seg.source, seg.target,
    currentProject.s, currentProject.t, projectGlossary(currentProject));
  renderQa(id, issues, sidebar);
}

function renderQa(id, issues, sidebar) {
  const html = issues.map((i) =>
    `<div class="issue ${i.severity}">${i.severity === "error" ? "⛔" : "⚠️"} ${esc(i.message)}</div>`).join("");
  const flags = $(`#qa-${id}`);
  if (flags) flags.innerHTML = html;
  if (sidebar) $("#qa-issues").innerHTML = html || `<div class="muted">No issues.</div>`;
}

function saveSeg(id, state) {
  const seg = S.segments.find((x) => x.id === id);
  const target = $(`#tgt-${id}`).value;
  if (state === null && target === seg.target) return;
  seg.target = target;
  if (state) seg.state = state;
  else if (seg.state === "new" && target.trim()) seg.state = "draft";
  if (["translated", "approved"].includes(seg.state) && target.trim()) {
    Engine.tmAdd(S, currentProject.s, currentProject.t,
      Engine.stripTags(seg.source), Engine.stripTags(target), "editor");
  }
  Store.save();
  const el = $(`#seg-${id}`);
  el.className = `seg state-${seg.state}` + (activeSegId === id ? " active" : "");
  runSegQa(id, activeSegId === id);
  updateProgress();
}

// ---------- event delegation ----------

document.addEventListener("click", (ev) => {
  const t = ev.target.closest("[data-open-project],[data-del-project],[data-open-file],[data-copy],[data-seg-btn],[data-apply],[data-seg]");
  if (!t) return;
  if (t.dataset.openProject) return openProject(+t.dataset.openProject);
  if (t.dataset.delProject) {
    if (!confirm("Delete this project and its files?")) return;
    const pid = +t.dataset.delProject;
    const fids = S.files.filter((f) => f.projectId === pid).map((f) => f.id);
    S.projects = S.projects.filter((p) => p.id !== pid);
    S.files = S.files.filter((f) => f.projectId !== pid);
    S.segments = S.segments.filter((x) => !fids.includes(x.fileId));
    Store.saveOriginals();
    return showHome();
  }
  if (t.dataset.openFile) return openEditor(+t.dataset.openFile);
  if (t.dataset.copy) {
    const id = +t.dataset.copy;
    $(`#tgt-${id}`).value = S.segments.find((x) => x.id === id).source;
    return saveSeg(id, null);
  }
  if (t.dataset.segBtn) return saveSeg(+t.dataset.segBtn, t.dataset.state);
  if (t.dataset.apply) {
    const id = +t.dataset.apply;
    $(`#tgt-${id}`).value = t.dataset.text;
    return saveSeg(id, null);
  }
  if (t.dataset.seg) return activateSeg(+t.dataset.seg);
});

document.addEventListener("focusin", (ev) => {
  const ta = ev.target.closest("[data-seg-ta]");
  if (ta) activateSeg(+ta.dataset.segTa);
});

document.addEventListener("focusout", (ev) => {
  const ta = ev.target.closest("[data-seg-ta]");
  if (ta) saveSeg(+ta.dataset.segTa, null);
});

document.addEventListener("keydown", (ev) => {
  const ta = ev.target.closest("[data-seg-ta]");
  if (!ta || ev.key !== "Enter" || !(ev.ctrlKey || ev.metaKey)) return;
  ev.preventDefault();
  const id = +ta.dataset.segTa;
  saveSeg(id, "translated");
  const segs = fileSegments(currentFile.id);
  const idx = segs.findIndex((s) => s.id === id);
  const next = segs[idx + 1];
  if (next) {
    activateSeg(next.id);
    const nextTa = $(`#tgt-${next.id}`);
    nextTa.focus();
    nextTa.scrollIntoView({ block: "center", behavior: "smooth" });
  }
});

// ---------- toolbar ----------

$("#pretranslate-btn").onclick = () => {
  let filled = 0;
  for (const seg of fileSegments(currentFile.id)) {
    if (seg.state !== "new" || seg.target) continue;
    const sug = Engine.mtSuggest(S, currentProject.s, currentProject.t,
      Engine.stripTags(seg.source));
    if (sug && sug.percent >= 50) {
      seg.target = sug.text;
      seg.state = "draft";
      filled++;
    }
  }
  Store.save();
  toast(`Pre-translated ${filled} segment(s)`);
  renderSegments();
};

$("#qa-all-btn").onclick = () => {
  let total = 0, flagged = 0;
  for (const seg of fileSegments(currentFile.id)) {
    const issues = Engine.checkSegment(S, seg.source, seg.target,
      currentProject.s, currentProject.t, projectGlossary(currentProject));
    renderQa(seg.id, issues, false);
    if (issues.length) { flagged++; total += issues.length; }
  }
  toast(total ? `QA: ${total} issue(s) in ${flagged} segment(s)` : "QA: no issues found");
};

$("#export-xliff").onclick = () => {
  const translations = {};
  for (const seg of fileSegments(currentFile.id)) {
    translations[seg.unitId] = [seg.target, seg.state];
  }
  const out = Engine.generateXliff(currentFile.original, translations, currentProject.t);
  const base = currentFile.name.replace(/\.[^.]+$/, "");
  download(`${base}.${currentProject.t}.xliff`, out);
};

$("#export-txt").onclick = () => {
  const text = fileSegments(currentFile.id).map((s) => s.target || s.source).join("\n");
  const base = currentFile.name.replace(/\.[^.]+$/, "");
  download(`${base}.translated.txt`, text, "text/plain");
};

$("#editor-back").onclick = () => openProject(currentProject.id);
$("#proj-back").onclick = showHome;
$("#brand").onclick = showHome;

$("#concord-q").addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter") return;
  ev.preventDefault();
  const q = ev.target.value.trim();
  if (!q) return;
  const rows = Engine.tmConcordance(S, currentProject.s, currentProject.t, q);
  $("#concord-panel").hidden = false;
  $("#concord-results").innerHTML = rows.length ? rows.map((r) =>
    `<div class="match"><div>${esc(r.source)}</div><div class="match-src">${esc(r.target)}</div></div>`).join("")
    : `<div class="muted">No TM hits for “${esc(q)}”.</div>`;
});

// ---------- home forms ----------

$("#project-form").onsubmit = (ev) => {
  ev.preventDefault();
  const [s, t] = $("#p-pair").value.split(":");
  S.projects.push({ id: Store.nextId(), name: $("#p-name").value.trim() || "Untitled",
                    s, t, created: Date.now() });
  Store.save();
  $("#p-name").value = "";
  showHome();
};

async function extractPdfText(file) {
  if (typeof pdfjsLib === "undefined") {
    throw new Error("PDF support not loaded (vendor/pdfjs missing)");
  }
  pdfjsLib.GlobalWorkerOptions.workerSrc = "./vendor/pdfjs/pdf.worker.min.js";
  const data = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data }).promise;
  const pages = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    let text = "";
    for (const item of content.items) {
      text += item.str;
      text += item.hasEOL ? "\n" : " ";
    }
    if (text.trim()) pages.push(text.trim());
  }
  const full = pages.join("\n\n");
  if (!full.trim()) {
    throw new Error("No extractable text — this looks like a scanned " +
      "(image-only) PDF. Run OCR on it first.");
  }
  return full;
}

$("#upload-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const file = $("#upload-file").files[0];
  if (!file) return;
  const name = file.name;
  const p = currentProject;
  let raw, kind, units;
  try {
    if (/\.(xlf|xliff)$/i.test(name)) {
      kind = "xliff";
      raw = await file.text();
      units = Engine.parseXliff(raw).units;
    } else if (/\.(txt|pdf)$/i.test(name)) {
      let text;
      if (/\.pdf$/i.test(name)) {
        kind = "pdf";
        toast("Extracting PDF text…");
        text = await extractPdfText(file);
      } else {
        kind = "txt";
        text = await file.text();
      }
      const sources = Engine.segmentText(text);
      raw = Engine.makeXliffFromSegments(name, p.s, p.t, sources);
      units = Engine.parseXliff(raw).units;
    } else {
      return toast("Only .xliff, .xlf, .txt and .pdf files are supported");
    }
  } catch (e) {
    return toast("Import failed: " + (e.message || e));
  }
  if (!units.length) return toast("No translatable segments found in file");
  const fid = Store.nextId();
  S.files.push({ id: fid, projectId: p.id, name, kind, original: raw });
  units.forEach((u, i) => {
    S.segments.push({ id: Store.nextId(), fileId: fid, seq: i, unitId: u.unitId,
      source: u.source, target: u.target, state: u.target ? u.state : "new" });
  });
  Store.saveOriginals();
  toast(`Imported ${units.length} segment(s)`);
  openProject(p.id);
};

$("#tmx-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const [s, t] = $("#tmx-pair").value.split(":");
  const raw = await $("#tmx-file").files[0].text();
  let pairs;
  try { pairs = Engine.parseTmx(raw, s, t); }
  catch (e) { return toast("Invalid TMX: " + e.message); }
  let added = 0;
  for (const [a, b] of pairs) {
    if (Engine.tmAdd(S, s, t, a, b, "tmx")) added++;
    Engine.tmAdd(S, t, s, b, a, "tmx");   // both directions
  }
  Store.save();
  toast(`TMX: ${pairs.length} pair(s) found, ${added} new`);
  refreshTmStats();
};

$("#pair-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const [s, t] = $("#pair-pair").value.split(":");
  const srcText = await $("#pair-src").files[0].text();
  const tgtText = await $("#pair-tgt").files[0].text();
  toast("Aligning and training…");
  setTimeout(() => {   // let the toast paint before the CPU-bound work
    const pairs = Engine.alignCorpus(srcText, tgtText);
    if (!pairs.length) return toast("Could not align the two files");
    let added = 0;
    for (const [a, b] of pairs) if (Engine.tmAdd(S, s, t, a, b, "corpus")) added++;
    const lex = Engine.trainLexicon(S, s, t);
    Store.save();
    toast(`Aligned ${pairs.length} pair(s), TM +${added}, lexicon ${lex} entries`);
    refreshTmStats();
  }, 50);
};

$("#tm-export-btn").onclick = () => {
  const [s, t] = $("#export-pair").value.split(":");
  const units = S.tm.filter((u) => u.s === s && u.t === t);
  if (!units.length) return toast("TM is empty for this pair");
  download(`matedog-${s}-${t}.tmx`, Engine.generateTmx(units, s, t));
};

$("#ml-train-btn").onclick = () => {
  const [s, t] = $("#export-pair").value.split(":");
  toast("Training lexicon…");
  setTimeout(() => {
    const n = Engine.trainLexicon(S, s, t);
    Store.save();
    toast(`Lexicon trained: ${n} entries`);
  }, 50);
};

$("#gloss-form").onsubmit = (ev) => {
  ev.preventDefault();
  const [s, t] = $("#gloss-pair").value.split(":");
  S.glossary.push({ id: Store.nextId(), s, t,
    srcTerm: $("#gloss-src").value.trim(), tgtTerm: $("#gloss-tgt").value.trim() });
  Store.save();
  $("#gloss-src").value = ""; $("#gloss-tgt").value = "";
  toast("Glossary term added");
};

// ---------- init ----------

fillPairSelects();
Store.load().then((state) => {
  S = state;
  showHome();
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("./sw.js").catch(() => {});
}
