/* core/draft-store: IndexedDB persistence for the schema Draft.

   Persists the whole editing state the editor needs to restore faithfully:
   the Schema baseline (schemaRevision), the command log and the undo
   cursor. Records whose format is not the current FORMAT are treated as
   "no draft"; the next save overwrites them.

   Quota/write failure keeps the in-memory draft and surfaces a persistent
   warning instead of pretending to save. */
const DB_NAME = "ct-drafts";
const STORE = "drafts";
const FORMAT = "ct-draft-v2";

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
  dbPromise.catch(() => { dbPromise = null; });
  return dbPromise;
}

export async function saveDraft(workspacePath, { schemaRevision, commands, cursor }) {
  const db = await openDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put({
      key: "draft:" + workspacePath,
      format: FORMAT,
      schemaRevision,
      commands,
      cursor,
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
  return {
    schemaRevision: record.schemaRevision || "",
    commands: record.commands || [],
    cursor: typeof record.cursor === "number" ? record.cursor : (record.commands || []).length,
    savedAt: record.savedAt || 0,
  };
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
