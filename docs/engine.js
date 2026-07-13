// MateDog web engine: formats, TM matching, learning, QA — all client-side.
"use strict";

const Engine = (() => {

  // ---------- text ----------

  const WORD_RE = /[\p{L}\p{N}_]+/gu;
  const TAG_RE = /<[^<>]+>/g;

  const stripTags = (text) => text.replace(TAG_RE, " ");
  const normSpace = (text) => text.replace(/\s+/g, " ").trim();
  const normLang = (code) => (code || "").trim().toLowerCase().replace("_", "-").split("-")[0];

  function tokenize(text) {
    return (stripTags(text).toLowerCase().match(WORD_RE)) || [];
  }

  function wordLevenshtein(a, b) {
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        cur.push(Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost));
      }
      prev = cur;
    }
    return prev[b.length];
  }

  function similarity(a, b) {
    const ta = tokenize(a), tb = tokenize(b);
    if (!ta.length && !tb.length) return 1;
    if (!ta.length || !tb.length) return 0;
    return Math.max(0, 1 - wordLevenshtein(ta, tb) / Math.max(ta.length, tb.length));
  }

  // ---------- segmenter ----------

  const ABBREV = new Set([
    "mr","mrs","ms","dr","prof","sr","jr","st","vs","etc","e.g","i.e","no","vol","fig","approx",
    "dhr","mevr","drs","ir","bv","nl","o.a","d.w.z","bijv","evt","ca",
    "т.е","т.д","т.п","и.о","г","гг","ул","им","др","проф","акад","стр","рис",
  ]);

  function isAbbrev(before) {
    const m = before.match(/([\p{L}\p{N}.]+?)\.?$/u);
    if (!m) return false;
    const word = m[1].toLowerCase().replace(/\.+$/, "");
    if (ABBREV.has(word)) return true;
    return word.length === 1 && /\p{L}/u.test(word);
  }

  function splitSentences(text) {
    const out = [];
    let start = 0;
    const re = /([.!?…]+)(\s+|$)/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      const end = m.index + m[1].length;
      const rest = text.slice(re.lastIndex);
      if (isAbbrev(text.slice(start, m.index))) continue;
      if (/^\p{Ll}/u.test(rest)) continue;
      const sentence = text.slice(start, end).trim();
      if (sentence) out.push(sentence);
      start = re.lastIndex;
    }
    const tail = text.slice(start).trim();
    if (tail) out.push(tail);
    return out;
  }

  function segmentText(text) {
    const segs = [];
    for (const para of text.split(/\n\s*\n|\r\n\s*\r\n/)) {
      const p = normSpace(para);
      if (p) segs.push(...splitSentences(p));
    }
    return segs;
  }

  // ---------- XML helpers ----------

  const escXml = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const escAttr = (t) => escXml(t).replace(/"/g, "&quot;");

  function parseXml(text) {
    const doc = new DOMParser().parseFromString(text, "application/xml");
    if (doc.querySelector("parsererror")) throw new Error("XML parse error");
    return doc;
  }

  function innerXml(elem) {
    let out = "";
    for (const node of elem.childNodes) {
      if (node.nodeType === Node.TEXT_NODE || node.nodeType === Node.CDATA_SECTION_NODE) {
        out += escXml(node.nodeValue);
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        const name = node.localName;
        let attrs = "";
        for (const a of node.attributes) attrs += ` ${a.localName}="${escAttr(a.value)}"`;
        const inner = innerXml(node);
        out += inner ? `<${name}${attrs}>${inner}</${name}>` : `<${name}${attrs}/>`;
      }
    }
    return out;
  }

  function fillElement(doc, el, text, ns) {
    while (el.firstChild) el.removeChild(el.firstChild);
    let frag = null;
    try {
      const wrapped = new DOMParser().parseFromString(
        `<wrap xmlns="${ns || ""}">${text}</wrap>`, "application/xml");
      if (!wrapped.querySelector("parsererror")) frag = wrapped.documentElement;
    } catch { /* fall through */ }
    if (!frag) {
      el.appendChild(doc.createTextNode(text));
      return;
    }
    for (const node of Array.from(frag.childNodes)) {
      el.appendChild(doc.importNode(node, true));
    }
  }

  // ---------- XLIFF ----------

  function parseXliff(content) {
    const doc = parseXml(content);
    const root = doc.documentElement;
    const version = root.getAttribute("version") || "1.2";
    const units = [];
    let srcLang = "", tgtLang = "";
    const doneStates12 = new Set(["translated", "signed-off", "final"]);

    if (version.startsWith("2")) {
      srcLang = root.getAttribute("srcLang") || "";
      tgtLang = root.getAttribute("trgLang") || "";
      for (const unit of root.getElementsByTagName("unit")) {
        const segs = unit.getElementsByTagName("segment");
        for (let i = 0; i < segs.length; i++) {
          const seg = segs[i];
          const src = seg.getElementsByTagName("source")[0];
          if (!src) continue;
          const tgt = seg.getElementsByTagName("target")[0];
          const targetText = tgt ? innerXml(tgt) : "";
          const st = seg.getAttribute("state") || "initial";
          units.push({
            unitId: `${unit.getAttribute("id") || ""}//${seg.getAttribute("id") || String(i)}`,
            source: innerXml(src),
            target: targetText,
            state: ["translated", "reviewed", "final"].includes(st)
              ? "translated" : (targetText ? "draft" : "new"),
          });
        }
      }
    } else {
      for (const f of root.getElementsByTagName("file")) {
        srcLang = srcLang || f.getAttribute("source-language") || "";
        tgtLang = tgtLang || f.getAttribute("target-language") || "";
        for (const tu of f.getElementsByTagName("trans-unit")) {
          if ((tu.getAttribute("translate") || "yes") === "no") continue;
          const src = tu.getElementsByTagName("source")[0];
          if (!src) continue;
          const tgt = tu.getElementsByTagName("target")[0];
          const targetText = tgt ? innerXml(tgt) : "";
          const st = tgt ? (tgt.getAttribute("state") || "") : "";
          units.push({
            unitId: tu.getAttribute("id") || "",
            source: innerXml(src),
            target: targetText,
            state: doneStates12.has(st) ? "translated" : (targetText ? "draft" : "new"),
          });
        }
      }
    }
    return { version: version.startsWith("2") ? "2.0" : "1.2", srcLang, tgtLang, units };
  }

  function generateXliff(original, translations, tgtLang) {
    const doc = parseXml(original);
    const root = doc.documentElement;
    const ns = root.namespaceURI || "";
    const version = root.getAttribute("version") || "1.2";
    const stateMap = { translated: "translated", approved: "final", draft: "new" };

    if (version.startsWith("2")) {
      for (const unit of root.getElementsByTagName("unit")) {
        const uid = unit.getAttribute("id") || "";
        const segs = unit.getElementsByTagName("segment");
        for (let i = 0; i < segs.length; i++) {
          const seg = segs[i];
          const key = `${uid}//${seg.getAttribute("id") || String(i)}`;
          if (!(key in translations)) continue;
          const [text, state] = translations[key];
          let tgt = seg.getElementsByTagName("target")[0];
          if (!tgt) {
            tgt = ns ? doc.createElementNS(ns, "target") : doc.createElement("target");
            seg.appendChild(tgt);
          }
          fillElement(doc, tgt, text, ns);
          if (state === "approved") seg.setAttribute("state", "final");
          else if (state === "translated") seg.setAttribute("state", "translated");
        }
      }
    } else {
      for (const f of root.getElementsByTagName("file")) {
        if (tgtLang && !f.getAttribute("target-language")) {
          f.setAttribute("target-language", tgtLang);
        }
        for (const tu of f.getElementsByTagName("trans-unit")) {
          const uid = tu.getAttribute("id") || "";
          if (!(uid in translations)) continue;
          const [text, state] = translations[uid];
          let tgt = tu.getElementsByTagName("target")[0];
          if (!tgt) {
            tgt = ns ? doc.createElementNS(ns, "target") : doc.createElement("target");
            const src = tu.getElementsByTagName("source")[0];
            if (src && src.nextSibling) tu.insertBefore(tgt, src.nextSibling);
            else tu.appendChild(tgt);
          }
          fillElement(doc, tgt, text, ns);
          if (stateMap[state]) tgt.setAttribute("state", stateMap[state]);
        }
      }
    }
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(root);
  }

  function makeXliffFromSegments(name, srcLang, tgtLang, sources) {
    const lines = [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<xliff xmlns="urn:oasis:names:tc:xliff:document:1.2" version="1.2">',
      `  <file original="${escAttr(name)}" source-language="${srcLang}" ` +
        `target-language="${tgtLang}" datatype="plaintext">`,
      "    <body>",
    ];
    sources.forEach((src, i) => {
      lines.push(`      <trans-unit id="${i + 1}">`,
                 `        <source>${escXml(src)}</source>`,
                 "        <target/>",
                 "      </trans-unit>");
    });
    lines.push("    </body>", "  </file>", "</xliff>");
    return lines.join("\n");
  }

  // ---------- TMX ----------

  function segTextFlat(seg) {
    let out = "";
    for (const node of seg.childNodes) {
      if (node.nodeType === Node.TEXT_NODE || node.nodeType === Node.CDATA_SECTION_NODE) {
        out += node.nodeValue;
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        out += segTextFlat(node);
      }
    }
    return out;
  }

  function parseTmx(content, srcLang, tgtLang) {
    const s = normLang(srcLang), t = normLang(tgtLang);
    const doc = parseXml(content);
    const pairs = [];
    for (const tu of doc.getElementsByTagName("tu")) {
      const byLang = {};
      for (const tuv of tu.getElementsByTagName("tuv")) {
        const lang = normLang(tuv.getAttribute("xml:lang") || tuv.getAttribute("lang") || "");
        const seg = tuv.getElementsByTagName("seg")[0];
        if (lang && seg && !(lang in byLang)) {
          const text = normSpace(segTextFlat(seg));
          if (text) byLang[lang] = text;
        }
      }
      if (byLang[s] && byLang[t]) pairs.push([byLang[s], byLang[t]]);
    }
    return pairs;
  }

  function generateTmx(units, srcLang, tgtLang) {
    const now = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
    const lines = [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<tmx version="1.4">',
      `  <header creationtool="MateDog" creationtoolversion="0.1" segtype="sentence" ` +
        `o-tmf="MateDog" adminlang="en" srclang="${srcLang}" datatype="plaintext" ` +
        `creationdate="${now}"/>`,
      "  <body>",
    ];
    for (const u of units) {
      lines.push("    <tu>",
        `      <tuv xml:lang="${srcLang}"><seg>${escXml(u.source)}</seg></tuv>`,
        `      <tuv xml:lang="${tgtLang}"><seg>${escXml(u.target)}</seg></tuv>`,
        "    </tu>");
    }
    lines.push("  </body>", "</tmx>");
    return lines.join("\n");
  }

  // ---------- TM ----------
  // TM units live in state.tm: {s, t, source, target, origin, use}
  //
  // Lookups go through an inverted token index (token -> units) with a
  // tokenization cache, both keyed on the state.tm array via WeakMap and
  // updated incrementally by tmAdd. This keeps segment switches O(candidates)
  // instead of O(whole TM) — the difference between instant and laggy typing
  // on a phone once the TM has thousands of units.

  const _tokCache = new WeakMap();   // unit -> tokens
  const _tmIndexes = new WeakMap();  // state.tm array -> {map, byKey, size}

  function _unitToks(u) {
    let toks = _tokCache.get(u);
    if (!toks) { toks = tokenize(u.source); _tokCache.set(u, toks); }
    return toks;
  }

  const _unitKey = (u) => `${u.s}\x00${u.t}\x00${u.source}\x00${u.target}`;

  function _indexUnit(idx, u) {
    for (const tok of new Set(_unitToks(u))) {
      const key = `${u.s}:${u.t}:${tok}`;
      let arr = idx.map.get(key);
      if (!arr) idx.map.set(key, arr = []);
      arr.push(u);
    }
    idx.byKey.set(_unitKey(u), u);
  }

  function _getIndex(state) {
    let idx = _tmIndexes.get(state.tm);
    if (!idx || idx.size !== state.tm.length) {
      idx = { map: new Map(), byKey: new Map(), size: state.tm.length };
      for (const u of state.tm) _indexUnit(idx, u);
      _tmIndexes.set(state.tm, idx);
    }
    return idx;
  }

  function tmAdd(state, s, t, source, target, origin) {
    source = normSpace(source); target = normSpace(target);
    if (!source || !target) return false;
    s = normLang(s); t = normLang(t);
    const idx = _getIndex(state);
    const unit = { s, t, source, target, origin, use: 0 };
    const existing = idx.byKey.get(_unitKey(unit));
    if (existing) { existing.use++; return false; }
    state.tm.push(unit);
    _indexUnit(idx, unit);
    idx.size++;
    return true;
  }

  function tmLookup(state, s, t, text, limit = 5, minScore = 0.5) {
    s = normLang(s); t = normLang(t);
    const plain = normSpace(stripTags(text));
    if (!plain) return [];
    const queryToks = tokenize(plain);
    const querySet = new Set(queryToks);
    const idx = _getIndex(state);

    // Collect candidates rarest-token-first, so stop-words ("the", "и", "de")
    // whose posting lists span the whole TM don't flood the scoring loop. A
    // real fuzzy match shares content words, which are in the rare lists.
    const lists = [];
    for (const tok of querySet) {
      const arr = idx.map.get(`${s}:${t}:${tok}`);
      if (arr) lists.push(arr);
    }
    lists.sort((a, b) => a.length - b.length);
    const candidates = new Set();
    for (const arr of lists) {
      if (candidates.size >= 1500 && arr.length > state.tm.length * 0.2) break;
      for (const u of arr) candidates.add(u);
      if (candidates.size >= 4000) break;
    }

    const results = [];
    for (const u of candidates) {
      if (u.source === plain) { results.push({ ...u, score: 1 }); continue; }
      const utoks = _unitToks(u);
      if (utoks.length > queryToks.length * 3 + 4 || queryToks.length > utoks.length * 3 + 4) continue;
      const score = tokenSimilarity(queryToks, utoks);
      if (score >= minScore) results.push({ ...u, score });
    }
    results.sort((a, b) => b.score - a.score || b.use - a.use);
    return results.slice(0, limit).map((m) => ({ ...m, percent: Math.round(m.score * 100) }));
  }

  function tokenSimilarity(ta, tb) {
    if (!ta.length && !tb.length) return 1;
    if (!ta.length || !tb.length) return 0;
    return Math.max(0, 1 - wordLevenshtein(ta, tb) / Math.max(ta.length, tb.length));
  }

  function tmConcordance(state, s, t, query, limit = 30) {
    s = normLang(s); t = normLang(t);
    const q = query.toLowerCase();
    return state.tm
      .filter((u) => u.s === s && u.t === t &&
        (u.source.toLowerCase().includes(q) || u.target.toLowerCase().includes(q)))
      .sort((a, b) => b.use - a.use)
      .slice(0, limit);
  }

  // ---------- learning (IBM Model 1) ----------

  const MIN_PROB = 0.15, TOP_K = 4, EM_ITERS = 6, MAX_PAIRS = 50000;

  function trainLexicon(state, s, t) {
    s = normLang(s); t = normLang(t);
    const pairs = [];
    for (const u of state.tm) {
      if (u.s !== s || u.t !== t) continue;
      const st = tokenize(u.source), tt = tokenize(u.target);
      if (st.length && tt.length && st.length < 80 && tt.length < 80) pairs.push([st, tt]);
      if (pairs.length >= MAX_PAIRS) break;
    }
    if (!pairs.length) return 0;

    const tProb = new Map(); // srcWord -> Map(tgtWord -> prob)
    for (const [st, tt] of pairs) {
      for (const sw of st) {
        if (!tProb.has(sw)) tProb.set(sw, new Map());
        const m = tProb.get(sw);
        for (const tw of tt) if (!m.has(tw)) m.set(tw, 0);
      }
    }
    for (const m of tProb.values()) {
      const p = 1 / m.size;
      for (const k of m.keys()) m.set(k, p);
    }

    for (let iter = 0; iter < EM_ITERS; iter++) {
      const count = new Map(); // "sw tw" -> n
      const total = new Map(); // sw -> n
      for (const [st, tt] of pairs) {
        for (const tw of tt) {
          let denom = 0;
          for (const sw of st) denom += tProb.get(sw).get(tw) || 0;
          if (denom <= 0) continue;
          for (const sw of st) {
            const d = (tProb.get(sw).get(tw) || 0) / denom;
            if (d > 0) {
              const key = sw + " " + tw;
              count.set(key, (count.get(key) || 0) + d);
              total.set(sw, (total.get(sw) || 0) + d);
            }
          }
        }
      }
      for (const [key, c] of count) {
        const [sw, tw] = key.split(" ");
        const tot = total.get(sw);
        if (tot > 0) tProb.get(sw).set(tw, c / tot);
      }
    }

    const lexKey = `${s}:${t}`;
    const lex = {};
    let n = 0;
    for (const [sw, m] of tProb) {
      if (sw.length < 2) continue;
      const best = [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, TOP_K)
        .filter(([tw, p]) => p >= MIN_PROB && tw.length > 1)
        .map(([tw, p]) => [tw, Math.round(p * 10000) / 10000]);
      if (best.length) { lex[sw] = best; n += best.length; }
    }
    state.lexicon[lexKey] = lex;
    return n;
  }

  function lexiconLookup(state, s, t, word) {
    const lex = state.lexicon[`${normLang(s)}:${normLang(t)}`];
    return (lex && lex[word.toLowerCase()]) || [];
  }

  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  function repairFuzzy(state, s, t, newSource, matchSource, matchTarget) {
    const newToks = tokenize(newSource), oldToks = tokenize(matchSource);
    const newSet = new Set(newToks), oldSet = new Set(oldToks);
    const removed = oldToks.filter((w) => !newSet.has(w));
    const added = newToks.filter((w) => !oldSet.has(w));
    if (!removed.length || removed.length !== added.length || removed.length > 2) return null;

    let target = matchTarget;
    let tgtToks = tokenize(target);
    for (let i = 0; i < removed.length; i++) {
      const oldTrans = lexiconLookup(state, s, t, removed[i])
        .filter(([, p]) => p >= 0.25).map(([w]) => w);
      const newTrans = lexiconLookup(state, s, t, added[i]);
      const hit = oldTrans.find((w) => tgtToks.includes(w));
      if (!hit || !newTrans.length) return null;
      const re = new RegExp(`(^|[^\\p{L}\\p{N}_])(${escRe(hit)})(?=$|[^\\p{L}\\p{N}_])`, "iu");
      if (!re.test(target)) return null;
      target = target.replace(re, (m, pre) => pre + newTrans[0][0]);
      tgtToks = tokenize(target);
    }
    return target !== matchTarget ? target : null;
  }

  // ---------- alignment ----------

  function alignCorpus(srcText, tgtText) {
    const srcLines = srcText.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const tgtLines = tgtText.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    if (srcLines.length > 1 && srcLines.length === tgtLines.length) {
      return srcLines.map((l, i) => [l, tgtLines[i]]);
    }
    const ss = segmentText(srcText), ts = segmentText(tgtText);
    if (!ss.length || !ts.length) return [];

    const cost = (sChunk, tChunk) => {
      const ls = sChunk.reduce((a, x) => a + x.length, 0);
      const lt = tChunk.reduce((a, x) => a + x.length, 0);
      if (!ls || !lt) return 10;
      return Math.abs(Math.log(ls / lt)) + 0.4 * (sChunk.length + tChunk.length - 2);
    };

    const n = ss.length, m = ts.length;
    const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(Infinity));
    const back = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(null));
    dp[0][0] = 0;
    const beads = [[1, 1], [1, 2], [2, 1]];
    for (let i = 0; i <= n; i++) {
      for (let j = 0; j <= m; j++) {
        if (dp[i][j] === Infinity) continue;
        for (const [di, dj] of beads) {
          const ni = i + di, nj = j + dj;
          if (ni <= n && nj <= m) {
            const c = dp[i][j] + cost(ss.slice(i, ni), ts.slice(j, nj));
            if (c < dp[ni][nj]) { dp[ni][nj] = c; back[ni][nj] = [di, dj]; }
          }
        }
      }
    }
    if (dp[n][m] === Infinity) return ss.map((x, i) => [x, ts[i]]).filter((p) => p[1]);
    const pairs = [];
    let i = n, j = m;
    while (i > 0 || j > 0) {
      const step = back[i][j];
      if (!step) break;
      const [di, dj] = step;
      pairs.push([ss.slice(i - di, i).join(" "), ts.slice(j - dj, j).join(" ")]);
      i -= di; j -= dj;
    }
    return pairs.reverse();
  }

  // ---------- QA ----------

  const END_PUNCT = ".!?:;…";

  function extractTags(text) {
    const out = [];
    for (const t of text.match(TAG_RE) || []) {
      const m = t.match(/^<\/?\s*([\w:-]+)/);
      out.push((t.startsWith("</") ? "/" : "") + (m ? m[1] : t));
    }
    return out.sort();
  }

  function extractNumbers(text) {
    return (text.match(/\d+(?:[.,]\d+)*/g) || [])
      .map((n) => n.replace(/,/g, ".").replace(/\.$/, "")).sort();
  }

  function checkSegment(state, source, target, srcLang, tgtLang, glossary) {
    const s = normLang(srcLang), t = normLang(tgtLang);
    const issues = [];
    const add = (code, severity, message) => issues.push({ code, severity, message });

    if (!target.trim()) { add("empty", "error", "Target is empty"); return issues; }

    const sWords = tokenize(source), tWords = tokenize(target);

    if (source.trim() === target.trim() && s !== t && sWords.length > 2) {
      add("untranslated", "warning", "Target is identical to source");
    }

    const st = extractTags(source), tt = extractTags(target);
    if (JSON.stringify(st) !== JSON.stringify(tt)) {
      add("tags", "error", `Inline tag mismatch (source: ${st.length}, target: ${tt.length})`);
    }

    const sn = extractNumbers(source), tn = extractNumbers(target);
    if (JSON.stringify(sn) !== JSON.stringify(tn)) {
      const missing = sn.filter((n) => !tn.includes(n));
      const extra = tn.filter((n) => !sn.includes(n));
      const parts = [];
      if (missing.length) parts.push("missing " + missing.slice(0, 5).join(", "));
      if (extra.length) parts.push("added " + extra.slice(0, 5).join(", "));
      add("numbers", "error", "Number mismatch: " + parts.join("; "));
    }

    if (target !== target.trim()) add("whitespace", "warning", "Leading or trailing whitespace in target");
    if (target.includes("  ")) add("double_space", "warning", "Double space in target");

    const sEnd = source.trimEnd().slice(-1), tEnd = target.trimEnd().slice(-1);
    if (END_PUNCT.includes(sEnd) !== END_PUNCT.includes(tEnd)) {
      add("punct_end", "warning", "End punctuation differs from source");
    }

    if (sWords.length && tWords.length) {
      const ratio = target.length / Math.max(1, source.length);
      if (ratio > 2.6 || ratio < 0.35) {
        add("length", "warning", `Unusual length ratio (${ratio.toFixed(1)}x source)`);
      }
    }

    for (let i = 1; i < tWords.length; i++) {
      if (tWords[i] === tWords[i - 1] && tWords[i].length > 1) {
        add("repeated_word", "warning", `Repeated word: “${tWords[i]}”`);
        break;
      }
    }

    const sFirst = source.charAt(0), tFirst = target.charAt(0);
    if (/\p{L}/u.test(sFirst) && /\p{L}/u.test(tFirst)) {
      if ((sFirst === sFirst.toUpperCase()) !== (tFirst === tFirst.toUpperCase())) {
        add("capitalization", "warning", "First-letter capitalization differs from source");
      }
    }

    if (t === "ru") {
      if (/"[^"]+"/.test(target)) add("ru_quotes", "warning",
        "Russian typography prefers «guillemets» over straight quotes");
      if (/\s-\s/.test(target)) add("ru_dash", "warning",
        "Use an em dash (—) instead of a hyphen between words");
      if (/[а-яА-ЯёЁ][a-zA-Z]|[a-zA-Z][а-яА-ЯёЁ]/.test(target)) add("ru_mixed_script", "error",
        "Latin and Cyrillic letters mixed inside a word");
    }
    if (t === "nl") {
      if (/\bu\s+heeft\b/i.test(target)) add("nl_style", "warning",
        "Formal style: “u hebt” is preferred over “u heeft”");
    }

    for (const g of glossary || []) {
      const srcRe = new RegExp(`(^|[^\\p{L}\\p{N}_])${escRe(g.srcTerm)}($|[^\\p{L}\\p{N}_])`, "iu");
      const tgtRe = new RegExp(escRe(g.tgtTerm), "iu");
      if (srcRe.test(source) && !tgtRe.test(target)) {
        add("glossary", "warning",
          `Glossary: “${g.srcTerm}” should be translated as “${g.tgtTerm}”`);
      }
    }

    return issues;
  }

  // ---------- machine suggestion ----------

  function glossDraft(state, s, t, text) {
    let translatedAny = false;
    const out = text.replace(/[\p{L}\p{N}_]+/gu, (w) => {
      const trans = lexiconLookup(state, s, t, w);
      if (!trans.length) return w;
      translatedAny = true;
      let word = trans[0][0];
      if (w.charAt(0) === w.charAt(0).toUpperCase()) {
        word = word.charAt(0).toUpperCase() + word.slice(1);
      }
      return word;
    });
    return translatedAny ? out : null;
  }

  function mtSuggest(state, s, t, text, precomputed) {
    // precomputed: optional tmLookup results for the same text, so callers
    // that already fetched matches don't trigger a second lookup.
    const matches = precomputed !== undefined
      ? precomputed.filter((m) => m.score >= 0.6).slice(0, 1)
      : tmLookup(state, s, t, text, 1, 0.6);
    if (matches.length && matches[0].percent >= 100) {
      return { text: matches[0].target, provider: "TM (exact)", percent: 100 };
    }
    if (matches.length) {
      const best = matches[0];
      const repaired = repairFuzzy(state, s, t, text, best.source, best.target);
      if (repaired) {
        return { text: repaired, provider: "TM + lexicon repair",
                 percent: Math.min(99, best.percent + 5) };
      }
    }
    if (matches.length) {
      return { text: matches[0].target, provider: "TM (fuzzy)", percent: matches[0].percent };
    }
    const gloss = glossDraft(state, s, t, text);
    if (gloss) return { text: gloss, provider: "Lexicon gloss (rough draft)", percent: 30 };
    return null;
  }

  return {
    normLang, normSpace, stripTags, tokenize, similarity,
    segmentText, splitSentences,
    parseXliff, generateXliff, makeXliffFromSegments,
    parseTmx, generateTmx,
    tmAdd, tmLookup, tmConcordance,
    trainLexicon, lexiconLookup, repairFuzzy, alignCorpus,
    checkSegment, mtSuggest, glossDraft,
  };
})();

if (typeof module !== "undefined") module.exports = Engine;  // for tests
