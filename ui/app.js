"use strict";

const $ = (sel) => document.querySelector(sel);
const PAIRS = [["en","ru"],["ru","en"],["en","nl"],["nl","en"]];
const LANG_NAMES = {en:"English", ru:"Russian", nl:"Dutch"};

let currentProject = null;
let currentFile = null;
let activeSegId = null;
let segCache = [];

// ---------- helpers ----------

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    toast("Error: " + msg);
    throw new Error(msg);
  }
  return res.json();
}

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

// Render segment text with inline tags highlighted.
function renderText(s) {
  return esc(s).replace(/&lt;[^&]*?&gt;/g, (m) => `<span class="tag">${m}</span>`);
}

function pairLabel([s, t]) { return `${LANG_NAMES[s]} → ${LANG_NAMES[t]}`; }

function fillPairSelects() {
  document.querySelectorAll(".pair-select").forEach((sel) => {
    sel.innerHTML = PAIRS.map((p) =>
      `<option value="${p[0]}:${p[1]}">${pairLabel(p)}</option>`).join("");
  });
}

function show(viewId) {
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== viewId));
}

// ---------- home ----------

async function showHome() {
  show("view-home");
  $("#header-info").textContent = "local CAT tool · en↔ru · en↔nl";
  const projects = await api("/api/projects");
  $("#project-list").innerHTML = projects.length ? projects.map((p) => `
    <div class="plist-item">
      <a onclick="openProject(${p.id})">${esc(p.name)}</a>
      <span class="badge">${p.src_lang} → ${p.tgt_lang}</span>
      <span class="muted">${p.files} file(s), ${p.done}/${p.segments} segments</span>
      <div class="progress"><div style="width:${p.segments ? (100*p.done/p.segments) : 0}%"></div></div>
      <span class="grow"></span>
      <button class="del" onclick="deleteProject(${p.id})">✕</button>
    </div>`).join("") : `<div class="muted">No projects yet — create one above.</div>`;
  refreshTmStats();
}

async function refreshTmStats() {
  const s = await api("/api/tm/stats");
  const rows = s.pairs.map((p) =>
    `<div>${p.src_lang} → ${p.tgt_lang}: <b>${p.units}</b> TM units</div>`).join("");
  const argos = s.providers.argos
    ? `<div class="muted">Local NMT (Argos): available</div>`
    : `<div class="muted">Local NMT (Argos): not installed — TM + lexicon suggestions only</div>`;
  $("#tm-stats").innerHTML = (rows || `<div class="muted">TM is empty.</div>`) + argos;
}

async function deleteProject(id) {
  if (!confirm("Delete this project and its files?")) return;
  await api(`/api/projects/${id}`, { method: "DELETE" });
  showHome();
}

// ---------- project view ----------

async function openProject(id) {
  const p = await api(`/api/projects/${id}`);
  currentProject = p;
  show("view-project");
  $("#proj-title").textContent = `${p.name} (${pairLabel([p.src_lang, p.tgt_lang])})`;
  $("#file-list").innerHTML = p.files.length ? p.files.map((f) => `
    <div class="flist-item">
      <a onclick="openEditor(${f.id}, '${esc(f.name).replace(/'/g, "&#39;")}')">${esc(f.name)}</a>
      <span class="badge">${f.kind}</span>
      <span class="muted">${f.done}/${f.segments} segments</span>
      <div class="progress"><div style="width:${f.segments ? (100*f.done/f.segments) : 0}%"></div></div>
    </div>`).join("") : `<div class="muted">Upload an XLIFF or plain-text file to start translating.</div>`;
  $("#analysis").innerHTML = "";
  if (p.files.length) {
    const a = await api(`/api/projects/${id}/analysis`);
    const b = a.bands;
    $("#analysis").innerHTML = `<div class="muted" style="margin-top:10px">
      Analysis: ${a.total_words} words — ${b.exact} exact · ${b.fuzzy_75_99} fuzzy 75–99% ·
      ${b.fuzzy_50_74} fuzzy 50–74% · ${b.repetition} repetitions · ${b.new} new</div>`;
  }
}

// ---------- editor ----------

async function openEditor(fileId, name) {
  currentFile = { id: fileId, name };
  show("view-editor");
  $("#editor-file").textContent = name;
  $("#export-xliff").href = `/api/files/${fileId}/export`;
  $("#export-txt").href = `/api/files/${fileId}/export-txt`;
  $("#concord-panel").hidden = true;
  await loadSegments();
}

async function loadSegments() {
  segCache = await api(`/api/files/${currentFile.id}/segments`);
  updateProgress();
  $("#segments").innerHTML = segCache.map(segHtml).join("");
  $("#matches").innerHTML = `<div class="muted">Select a segment.</div>`;
  $("#qa-issues").innerHTML = "";
}

function segHtml(s) {
  return `
  <div class="seg state-${s.state}" id="seg-${s.id}" onclick="activateSeg(${s.id})">
    <div class="num">${s.seq + 1}</div>
    <div class="src">${renderText(s.source)}</div>
    <div><textarea id="tgt-${s.id}"
        onblur="saveSeg(${s.id}, null)"
        onkeydown="segKey(event, ${s.id})">${esc(s.target)}</textarea></div>
    <div class="ops">
      <button class="secondary" onclick="copySource(${s.id});event.stopPropagation()">Copy source</button>
      <button onclick="saveSeg(${s.id}, 'translated');event.stopPropagation()">Translated ✓</button>
      <button class="secondary" onclick="saveSeg(${s.id}, 'approved');event.stopPropagation()">Approve ✓✓</button>
      <button class="secondary" onclick="saveSeg(${s.id}, 'rejected');event.stopPropagation()">Reject</button>
    </div>
    <div class="qa-flags" id="qa-${s.id}"></div>
  </div>`;
}

function updateProgress() {
  const done = segCache.filter((s) => ["translated", "approved"].includes(s.state)).length;
  $("#editor-progress").textContent = `${done}/${segCache.length} confirmed`;
}

function segKey(ev, id) {
  if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
    ev.preventDefault();
    saveSeg(id, "translated");
    const idx = segCache.findIndex((s) => s.id === id);
    const next = segCache[idx + 1];
    if (next) {
      activateSeg(next.id);
      $(`#tgt-${next.id}`).focus();
    }
  }
}

async function activateSeg(id) {
  if (activeSegId === id) return;
  activeSegId = id;
  document.querySelectorAll(".seg.active").forEach((el) => el.classList.remove("active"));
  $(`#seg-${id}`)?.classList.add("active");
  $("#matches").innerHTML = `<div class="muted">Loading…</div>`;
  const m = await api(`/api/segments/${id}/matches`);
  if (activeSegId !== id) return;
  let html = "";
  if (m.mt) {
    html += `<div class="match"><span class="pct">${m.mt.percent}%</span>
      <span class="muted">${esc(m.mt.provider)}</span>
      <button class="apply" onclick="applyText(${id}, ${JSON.stringify(m.mt.text).replace(/"/g, "&quot;")})">Apply</button>
      <div>${esc(m.mt.text)}</div></div>`;
  }
  for (const t of m.tm) {
    html += `<div class="match"><span class="pct">${t.percent}%</span>
      <span class="muted">TM · ${esc(t.origin)}</span>
      <button class="apply" onclick="applyText(${id}, ${JSON.stringify(t.target).replace(/"/g, "&quot;")})">Apply</button>
      <div>${esc(t.target)}</div>
      <div class="match-src">${renderText(t.source)}</div></div>`;
  }
  if (m.terms.length) {
    html += `<h3 style="margin-top:10px">Learned terms</h3>` + m.terms.map((t) =>
      `<span class="term">${esc(t.word)} → ${esc(t.translations.join(", "))}</span>`).join("");
  }
  $("#matches").innerHTML = html || `<div class="muted">No suggestions yet — import a TMX or paired texts.</div>`;
  const qa = await api(`/api/segments/${id}/qa`);
  renderQa(id, qa, true);
}

function renderQa(id, issues, sidebar) {
  const html = issues.map((i) =>
    `<div class="issue ${i.severity}">${i.severity === "error" ? "⛔" : "⚠️"} ${esc(i.message)}</div>`).join("");
  $(`#qa-${id}`).innerHTML = html;
  if (sidebar) $("#qa-issues").innerHTML = html || `<div class="muted">No issues.</div>`;
}

function copySource(id) {
  const s = segCache.find((x) => x.id === id);
  $(`#tgt-${id}`).value = s.source;
  saveSeg(id, null);
}

function applyText(id, text) {
  $(`#tgt-${id}`).value = text;
  saveSeg(id, null);
}

async function saveSeg(id, state) {
  const target = $(`#tgt-${id}`).value;
  const s = segCache.find((x) => x.id === id);
  if (state === null && target === s.target) return;   // nothing changed on blur
  const body = { target };
  if (state) body.state = state;
  const res = await api(`/api/segments/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  s.target = target;
  if (state) s.state = state;
  const el = $(`#seg-${id}`);
  el.className = `seg state-${s.state}` + (activeSegId === id ? " active" : "");
  renderQa(id, res.qa, activeSegId === id);
  updateProgress();
}

// ---------- toolbar actions ----------

$("#pretranslate-btn").onclick = async () => {
  const r = await api(`/api/files/${currentFile.id}/pretranslate`, { method: "POST" });
  toast(`Pre-translated ${r.filled} segment(s)`);
  await loadSegments();
};

$("#qa-all-btn").onclick = async () => {
  const report = await api(`/api/files/${currentFile.id}/qa`, { method: "POST" });
  document.querySelectorAll(".qa-flags").forEach((el) => (el.innerHTML = ""));
  let total = 0;
  for (const r of report) {
    renderQa(r.segment_id, r.issues, false);
    total += r.issues.length;
  }
  toast(total ? `QA: ${total} issue(s) in ${report.length} segment(s)` : "QA: no issues found");
};

$("#editor-back").onclick = () => openProject(currentProject.id);

$("#concord-q").addEventListener("keydown", async (ev) => {
  if (ev.key !== "Enter") return;
  const q = ev.target.value.trim();
  if (!q) return;
  const p = currentProject;
  const rows = await api(`/api/tm/concordance?src_lang=${p.src_lang}&tgt_lang=${p.tgt_lang}&q=${encodeURIComponent(q)}`);
  $("#concord-panel").hidden = false;
  $("#concord-results").innerHTML = rows.length ? rows.map((r) =>
    `<div class="match"><div>${esc(r.source)}</div><div class="match-src">${esc(r.target)}</div></div>`).join("")
    : `<div class="muted">No TM hits for “${esc(q)}”.</div>`;
});

// ---------- home forms ----------

$("#project-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const [src_lang, tgt_lang] = $("#p-pair").value.split(":");
  await api("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: $("#p-name").value, src_lang, tgt_lang }),
  });
  $("#p-name").value = "";
  showHome();
};

$("#upload-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const fd = new FormData();
  fd.append("file", $("#upload-file").files[0]);
  const r = await api(`/api/projects/${currentProject.id}/files`, { method: "POST", body: fd });
  toast(`Imported ${r.segments} segment(s)`);
  openProject(currentProject.id);
};

$("#tmx-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const [s, t] = $("#tmx-pair").value.split(":");
  const fd = new FormData();
  fd.append("src_lang", s); fd.append("tgt_lang", t); fd.append("both_directions", "true");
  fd.append("file", $("#tmx-file").files[0]);
  const r = await api("/api/tm/import", { method: "POST", body: fd });
  toast(`TMX: ${r.pairs_found} pair(s) found, ${r.added} new`);
  refreshTmStats();
};

$("#pair-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const [s, t] = $("#pair-pair").value.split(":");
  const fd = new FormData();
  fd.append("src_lang", s); fd.append("tgt_lang", t); fd.append("train", "true");
  fd.append("src_file", $("#pair-src").files[0]);
  fd.append("tgt_file", $("#pair-tgt").files[0]);
  toast("Aligning and training…");
  const r = await api("/api/tm/pair-import", { method: "POST", body: fd });
  toast(`Aligned ${r.aligned_pairs} pair(s), TM +${r.added_to_tm}, lexicon ${r.lexicon_entries} entries`);
  refreshTmStats();
};

$("#tm-export-btn").onclick = () => {
  const [s, t] = $("#export-pair").value.split(":");
  window.location = `/api/tm/export?src_lang=${s}&tgt_lang=${t}`;
};

$("#ml-train-btn").onclick = async () => {
  const [s, t] = $("#export-pair").value.split(":");
  toast("Training lexicon…");
  const r = await api(`/api/ml/train?src_lang=${s}&tgt_lang=${t}`, { method: "POST" });
  toast(`Lexicon trained: ${r.lexicon_entries} entries`);
};

$("#gloss-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const [s, t] = $("#gloss-pair").value.split(":");
  await api("/api/glossary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ src_lang: s, tgt_lang: t,
      src_term: $("#gloss-src").value, tgt_term: $("#gloss-tgt").value }),
  });
  $("#gloss-src").value = ""; $("#gloss-tgt").value = "";
  toast("Glossary term added");
};

$("#brand").onclick = showHome;

fillPairSelects();
showHome();
