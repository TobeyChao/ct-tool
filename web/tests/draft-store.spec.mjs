import {test,expect} from '@playwright/test';
import {startPanel} from './panel-helper.mjs';
import {readFile,appendFile} from 'node:fs/promises';
import {join} from 'node:path';

for(const difference of ['commands','cursor','schemaRevision','format']) {
 test(`conflicting draft aliases preserve every record on ${difference}`,async({page})=>{
  const p=await startPanel();try{
   await page.goto(p.url);
   const result=await page.evaluate(async difference=>{
    const draft=await import('/static/js/core/draft-store.js');
    // The two keys were both possible in the old same-origin panel.
    const a={key:'draft:C:\\Data\\Game\\',format:'ct-draft-v2',schemaRevision:'r1',commands:[{type:'one'}],cursor:1,savedAt:1};
    const b={...a,key:'draft:C:/Data/Game'};
    b[difference]=({commands:[{type:'other'}],cursor:0,schemaRevision:'r2',format:'future/99'})[difference];
    const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('ct-drafts',1);r.onupgradeneeded=()=>r.result.createObjectStore('drafts',{keyPath:'key'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    await new Promise(resolve=>{const tx=db.transaction('drafts','readwrite');for(const r of [a,b])tx.objectStore('drafts').put(r);tx.oncomplete=resolve;});
    const errors=[];
    for(const operation of [()=>draft.loadDraft('C:/Data/Game'),()=>draft.saveDraft('C:/Data/Game',{schemaRevision:'new',commands:[],cursor:0}),()=>draft.clearDraft('C:/Data/Game')]){
     try{await operation();errors.push(null);}catch(e){errors.push(e.record);}
    }
    const remaining=await new Promise(resolve=>{const r=db.transaction('drafts').objectStore('drafts').getAll();r.onsuccess=()=>resolve(r.result);});
    db.close();return {errors,remaining,original:[a,b]};
   },difference);
   for(const error of result.errors)expect(error).toHaveLength(2);
   expect(result.remaining.sort((a,b)=>a.key.localeCompare(b.key))).toEqual(result.original.sort((a,b)=>a.key.localeCompare(b.key)));
  }finally{await p.close();}
 });
}

test('identical aliases consolidate safely with full redo history',async({page})=>{
 const p=await startPanel();try{
  await page.goto(p.url);
  const result=await page.evaluate(async()=>{
   const draft=await import('/static/js/core/draft-store.js');
   await draft.saveDraft('/game/',{schemaRevision:'r',commands:[{type:'one'},{type:'two'}],cursor:1});
   const restored=await draft.loadDraft('/game');
   await draft.saveDraft('/game',restored);
   const db=await new Promise(resolve=>{const r=indexedDB.open('ct-drafts',1);r.onsuccess=()=>resolve(r.result);});
   const records=await new Promise(resolve=>{const r=db.transaction('drafts').objectStore('drafts').getAll();r.onsuccess=()=>resolve(r.result);});
   await draft.clearDraft('/game/');const after=await draft.loadDraft('/game');db.close();return {restored,records,after};
  });
  expect(result.restored.commands).toHaveLength(2);expect(result.restored.cursor).toBe(1);
  expect(result.records).toHaveLength(1);expect(result.records[0].key).toBe('draft:/game');expect(result.after).toBeNull();
 }finally{await p.close();}
});

test('unavailable IndexedDB keeps editable draft and a persistent warning across modules',async({page})=>{
 const p=await startPanel();try{
  await page.addInitScript(()=>{indexedDB.open=()=>{throw new DOMException('storage blocked','SecurityError');};});
  await page.goto(p.url);await page.locator('.ct-sitem[data-module="schema"]').click();
  await page.locator('#head-create-resource').click();await page.locator('[data-cr-name]').fill('Quest');await page.locator('[data-submit]').click();
  await expect(page.locator('#ct-draft-txt')).toContainText('草稿未持久化');
  await expect(page.locator('#ct-draft-save')).toBeEnabled();
  await page.locator('.ct-sitem[data-module="logs"]').click();await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect(page.locator('#ct-draft-txt')).toContainText('草稿未持久化');
  const state=await page.evaluate(()=>window.__ct.getPageState('schema'));expect(state.commands).toHaveLength(1);expect(state.cursor).toBe(1);
 }finally{await p.close();}
});

for(const stale of [false,true])test(`legacy draft is recomputed with redo and original baseline; stale=${stale}`,async({page})=>{
 const p=await startPanel();try{
  const snapshot=(await p.request('/api/schema-workspace')).data;
  const workspace=(await p.request('/api/workspace')).data;
  const commands=['first','redo'].map(value=>({type:'set_property',payload:{owner:'table:Item',name:'Name',property:'comment',value}}));
  await page.goto(p.url);
  await page.evaluate(async({root,revision,commands})=>{
   const draft=await import('/static/js/core/draft-store.js');
   await draft.saveDraft(root+'/',{schemaRevision:revision,commands,cursor:1});
  },{root:workspace.root,revision:snapshot.schemaRevision,commands});
  if(stale)await appendFile(join(p.root,'config/schemas/Item.yaml'),'\n# external change\n');
  await page.reload();await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').commands.length)).toBe(2);
  const restored=await page.evaluate(()=>window.__ct.getPageState('schema'));
  expect(restored.schemaRevision).toBe(snapshot.schemaRevision);expect(restored.cursor).toBe(1);
  if(stale){
   await expect(page.locator('#ct-draft-save')).toBeDisabled();await expect(page.locator('#ct-draftbar')).toContainText('基线');
   expect(await readFile(join(p.root,'config/schemas/Item.yaml'),'utf8')).toContain('# external change');
  }else{
   await expect(page.locator('#ct-draft-save')).toBeEnabled();
   const prefix=await page.evaluate(()=>window.__ct.getPageState('schema').candidate);
   expect(prefix.find(r=>r.name==='Item').fields.find(f=>f.name==='Name').comment).toBe('first');
   await page.locator('#ct-draft-redo').click();
   await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').candidate?.find(r=>r.name==='Item')?.fields.find(f=>f.name==='Name')?.comment)).toBe('redo');
  }
 }finally{await p.close();}
});

test('transient database open failure retries and clears warning after persistence',async({page})=>{
 const p=await startPanel();try{
  await page.addInitScript(()=>{const original=indexedDB.open.bind(indexedDB);indexedDB.open=(...args)=>{if(!sessionStorage.getItem('storage-failure-injected')){sessionStorage.setItem('storage-failure-injected','yes');throw new Error('temporary storage failure');}return original(...args);};});
  await page.goto(p.url);await page.locator('.ct-sitem[data-module="schema"]').click();
  await page.locator('#head-create-resource').click();await page.locator('[data-cr-name]').fill('Quest');await page.locator('[data-submit]').click();
  await expect(page.locator('#ct-draft-save')).toBeEnabled();await expect(page.locator('#ct-draft-txt')).not.toContainText('草稿未持久化');
  await page.reload();await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
 }finally{await p.close();}
});

test('unknown stored draft has a visible original-record viewer',async({page})=>{
 const p=await startPanel();try{
  const workspace=(await p.request('/api/workspace')).data;
  await page.goto(p.url);
  await page.evaluate(async root=>{
   const db=await new Promise(resolve=>{const r=indexedDB.open('ct-drafts',1);r.onupgradeneeded=()=>r.result.createObjectStore('drafts',{keyPath:'key'});r.onsuccess=()=>resolve(r.result);});
   await new Promise(resolve=>{const tx=db.transaction('drafts','readwrite');tx.objectStore('drafts').put({key:'draft:'+root,format:'future/99',original:'keep <original>'});tx.oncomplete=resolve;});db.close();
  },workspace.root);
  await page.locator('.ct-sitem[data-module="schema"]').click();await page.locator('.ct-workspace-layout').waitFor();
  if(await page.locator('.ct-workspace-layout').getAttribute('data-resource-open')!=='true')await page.locator('#resource-toggle').click();
  await page.locator('.ct-resource-row[data-name="Item"]').click();
  await expect(page.locator('#ct-draft-txt')).toContainText('草稿未持久化');
  await page.getByText('查看保留的草稿记录',{exact:true}).click();await expect(page.locator('#page-schema details pre')).toContainText('keep <original>');
  expect(await page.locator('#page-schema details original').count()).toBe(0);
 }finally{await p.close();}
});

test('actual old Web IndexedDB record replays only its active prefix',async({page})=>{
 const p=await startPanel();try{
  const fixture=JSON.parse(await readFile(new URL('../../native/docs/baseline/web-http-python.json',import.meta.url)));
  const saved=fixture.data.legacyDraft;
  const workspace=(await p.request('/api/workspace')).data;
  const snapshot=(await p.request('/api/schema-workspace')).data;
  await page.goto(p.url);
  await page.evaluate(async({saved,root,revision})=>{
   const db=await new Promise((resolve,reject)=>{const r=indexedDB.open(saved.db,1);r.onupgradeneeded=()=>r.result.createObjectStore(saved.store,{keyPath:'key'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
   const record={...saved.record,key:'draft:'+root,schemaRevision:revision};
   await new Promise(resolve=>{const tx=db.transaction(saved.store,'readwrite');tx.objectStore(saved.store).put(record);tx.oncomplete=resolve;});db.close();
  },{saved,root:workspace.root,revision:snapshot.schemaRevision});
  await page.reload();await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').candidate?.find(r=>r.name==='Item')?.fields.find(f=>f.name==='Id')?.comment)).toBe('active');
  const state=await page.evaluate(()=>window.__ct.getPageState('schema'));
  expect(state.cursor).toBe(1);expect(state.commands).toEqual(saved.record.commands);
  await page.locator('#ct-draft-redo').click();
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').candidate?.find(r=>r.name==='Item')?.fields.find(f=>f.name==='Id')?.comment)).toBe('redo');
 }finally{await p.close();}
});
