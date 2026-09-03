/* core/draft-store: IndexedDB persistence for the schema Draft command log.
   Keyed by workspace path + base revision; restores only when the source
   revision still matches. Quota/write failure keeps the in-memory draft and
   surfaces a persistent warning instead of pretending to save. */
const DB_NAME = "ct-v4-drafts";
const STORE = "drafts";
const FORMAT = "ct-draft-v1";

let dbPromise = null;

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) { reject(new Error("indexedDB 不可用")); return; }
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return dbPromise;
}

export async function saveDraft(workspacePath, baseRevision, commands) {
  const db = await openDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put({
      key: "draft:" + workspacePath,
      format: FORMAT,
      revision: baseRevision,
      commands,
      savedAt: Date.now(),
    });
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

export async function loadDraft(workspacePath) {
  const db = await openDb();
  const record = await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const request = tx.objectStore(STORE).get("draft:" + workspacePath);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
  if (!record || record.format !== FORMAT) return null;
  return { revision: record.revision, commands: record.commands || [] };
}

export async function clearDraft(workspacePath) {
  const db = await openDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete("draft:" + workspacePath);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}
