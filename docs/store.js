// MateDog web store: whole-app state persisted to IndexedDB (single record).
"use strict";

const Store = (() => {
  const DB_NAME = "matedog", STORE = "state", KEY = "v1";
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

  async function load() {
    try {
      db = await openDb();
      const loaded = await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, "readonly");
        const req = tx.objectStore(STORE).get(KEY);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
      if (loaded) state = Object.assign(defaults(), loaded);
    } catch (e) {
      console.warn("IndexedDB unavailable, state is in-memory only", e);
    }
    return state;
  }

  function saveNow() {
    if (!db) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(state, KEY);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
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
    load, save, saveNow, nextId,
    get state() { return state; },
  };
})();
