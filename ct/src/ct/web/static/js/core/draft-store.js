/* core/draft-store: IndexedDB persistence for the schema Draft.

   v2 persists the whole editing state the editor needs to restore faithfully:
   the Schema baseline (schemaRevision), the command log **and** the undo
   cursor. v1 records only stored commands, so replaying them would silently
   resurrect steps the user had undone; they are loaded with `cursor: null` and
   `legacy: true`, and the editor asks the user to check them instead of
   treating every command as pending.

   Quota/write failure keeps the in-memory draft and surfaces a persistent
   warning instead of pretending to save. */
const DB_NAME = "ct-drafts";
const STORE = "drafts";
const FORMAT = "ct-draft-v2";
const LEGACY_FORMATS = ["ct-draft-v1"];

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
  if (!record) return null;
  if (record.format === FORMAT) {
    return {
      schemaRevision: record.schemaRevision || "",
      commands: record.commands || [],
      cursor: typeof record.cursor === "number" ? record.cursor : (record.commands || []).length,
      legacy: false,
      savedAt: record.savedAt || 0,
    };
  }
  if (LEGACY_FORMATS.includes(record.format)) {
    return {
      schemaRevision: record.revision || "",
      commands: record.commands || [],
      cursor: null, // v1 never stored it: undo branch cannot be reconstructed
      legacy: true,
      savedAt: record.savedAt || 0,
    };
  }
  // Unknown format: keep the commands viewable, never treat them as pending.
  return {
    schemaRevision: "",
    commands: Array.isArray(record.commands) ? record.commands : [],
    cursor: null,
    legacy: true,
    unsupported: true,
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
