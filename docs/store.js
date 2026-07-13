// MateDog web store: whole-app state persisted to IndexedDB.
//
// Two records: the working state (projects, segments, TM, lexicon, glossary)
// saved on every edit, and the original file contents (potentially megabytes
// of XLIFF, needed only for export) saved separately on upload/delete. This
// keeps the per-edit structured clone small, so typing stays responsive.
"use strict";

const Store = (() => {
  const DB_NAME = "matedog", STORE = "state", KEY = "v1", KEY_ORIG = "originals";
  let db = null;
  let saveTimer = null;

  const defaults = () => ({
    nextId: 1,
    projects: [],   // {id, name, s, t, created}
    files: [],      // {id, projectId, name, kind, original}
    segments: [],   // {id, fileId, seq, unitId, source, target, state}
    tm: [],         // {s, t, source, target, origin, use}
    lexicon: {},    // "s:t" -> {srcWord: [[tgtWord, prob], ...]}
    glossary: [],   // {id, s, t, srcTerm, tgtTerm}
  });

  let state = defaults();

  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function idbGet(key) {
    return new Promise((resolve, reject) => {
      const req = db.transaction(STORE, "readonly").objectStore(STORE).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function idbPut(key, value) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(value, key);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  async function load() {
    try {
      db = await openDb();
      const [loaded, originals] = await Promise.all([idbGet(KEY), idbGet(KEY_ORIG)]);
      if (loaded) state = Object.assign(defaults(), loaded);
      for (const f of state.files) {
        // Older records stored originals inline; keep whichever is present.
        if (!f.original) f.original = (originals && originals[f.id]) || "";
      }
    } catch (e) {
      console.warn("IndexedDB unavailable, state is in-memory only", e);
    }
    return state;
  }

  function saveNow() {
    if (!db) return Promise.resolve();
    const light = {
      ...state,
      files: state.files.map(({ original, ...rest }) => rest),
    };
    return idbPut(KEY, light);
  }

  // Persist original file contents. Call when files are added or removed.
  function saveOriginals() {
    if (!db) return Promise.resolve();
    const originals = {};
    for (const f of state.files) originals[f.id] = f.original;
    return Promise.all([idbPut(KEY_ORIG, originals), saveNow()])
      .catch((e) => console.error("save failed", e));
  }

  // Coalesced save: call after every mutation. The timer is NOT reset by
  // subsequent calls, so a burst of mutations still flushes within 150ms.
  function save() {
    if (saveTimer) return;
    saveTimer = setTimeout(() => {
      saveTimer = null;
      saveNow().catch((e) => console.error("save failed", e));
    }, 150);
  }

  // Flush before the page is hidden or unloaded (tab switch, app switch on
  // Android, reload) — the debounce timer may never fire otherwise.
  function flushOnHide() {
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
      saveNow().catch(() => {});
    }
  }
  window.addEventListener("pagehide", flushOnHide);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushOnHide();
  });

  const nextId = () => state.nextId++;

  return {
    load, save, saveNow, saveOriginals, nextId,
    get state() { return state; },
  };
})();
