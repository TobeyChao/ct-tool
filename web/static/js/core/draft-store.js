/* Same-origin IndexedDB drafts. Unknown records are preserved, never overwritten. */
const DB_NAME = "ct-drafts";
const STORE = "drafts";
const FORMAT = "ct-draft-v2";
let dbPromise = null;
function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve,reject) => {
    if (!("indexedDB" in window)) {reject(new Error("indexedDB 不可用"));return;}
    const request=indexedDB.open(DB_NAME,1);
    request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains(STORE))request.result.createObjectStore(STORE,{keyPath:"key"});};
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(request.error);
  });
  dbPromise.catch(()=>{dbPromise=null;});return dbPromise;
}
function supported(record) {
  return record.format===FORMAT && Array.isArray(record.commands)
    && Number.isInteger(record.cursor) && record.cursor>=0 && record.cursor<=record.commands.length;
}
function unknown(record) {
  const error=new Error("本地草稿格式未知、损坏或路径别名记录冲突，已保留原记录；请先查看并备份，未覆盖保存。");
  error.record=record;return error;
}
function validateRecords(records) {
  if(records.some(record=>!supported(record)))throw unknown(records);
  if(records.length>1 && records.some(r=>JSON.stringify(r.commands)!==JSON.stringify(records[0].commands)||r.cursor!==records[0].cursor||r.schemaRevision!==records[0].schemaRevision))throw unknown(records);
}
function keys(path) {
  const normalized=path.replaceAll('\\','/').replace(/\/+$/,'') || '/';
  // Only separator/trailing-slash aliases; never guess that different roots are identical.
  const aliases=[path,normalized,normalized==='/'?normalized:normalized+'/'];
  if(/^[A-Za-z]:($|\/)/.test(normalized))aliases.push(normalized.replaceAll('/','\\'),normalized.replaceAll('/','\\')+'\\');
  return [...new Set(aliases)].map(p=>'draft:'+p);
}
export async function loadDraft(workspacePath) {
  const db=await openDb();
  const records=await new Promise((resolve,reject)=>{
    const tx=db.transaction(STORE,'readonly');const found=[];
    for(const key of keys(workspacePath)){const request=tx.objectStore(STORE).get(key);request.onsuccess=()=>{if(request.result)found.push(request.result);};}
    tx.oncomplete=()=>resolve(found);tx.onerror=()=>reject(tx.error);
  });
  if(!records.length)return null;
  validateRecords(records);
  const record=records[0];return {schemaRevision:record.schemaRevision||'',commands:record.commands,cursor:record.cursor,savedAt:record.savedAt||0};
}
// Read, validate and mutate every alias in one transaction. A conflicting record
// must survive both an autosave and an explicit discard of the in-memory draft.
async function mutateDraft(workspacePath,mutate) {
  const db=await openDb();
  await new Promise((resolve,reject)=>{
    const tx=db.transaction(STORE,'readwrite');const store=tx.objectStore(STORE);
    const aliases=keys(workspacePath),records=[];let pending=aliases.length;
    for(const key of aliases){const request=store.get(key);request.onsuccess=()=>{
      if(request.result)records.push(request.result);
      if(--pending===0){
        try{validateRecords(records);mutate(store,aliases);}
        catch(error){reject(error);tx.abort();}
      }
    };}
    tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error('草稿保存已取消'));
  });
}
export async function saveDraft(workspacePath,{schemaRevision,commands,cursor}) {
  await mutateDraft(workspacePath,(store,aliases)=>{
    for(const alias of aliases)store.delete(alias);
    store.put({key:aliases[0],format:FORMAT,schemaRevision,commands,cursor,savedAt:Date.now()});
  });
}
export async function clearDraft(workspacePath) {
  await mutateDraft(workspacePath,(store,aliases)=>{
    for(const alias of aliases)store.delete(alias);
  });
}
