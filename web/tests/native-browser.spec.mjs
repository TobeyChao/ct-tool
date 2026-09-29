import {test,expect} from '@playwright/test';
import {startPanel} from './panel-helper.mjs';
import {readFile,stat,appendFile,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';

test('native five modules, resource creation, YAML save, template and export',async({page})=>{
 const p=await startPanel();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
 await page.goto(p.url);
 await page.locator('.ct-sitem[data-module="schema"]').click();
 await page.locator(".ct-workspace-layout").waitFor();
 if((await page.locator(".ct-workspace-layout").getAttribute("data-resource-open"))!=="true") await page.locator('#resource-toggle').click();
 await page.locator('.ct-resource-row[data-name="Item"]').click();
 await expect(page.locator('#editor-title')).toHaveText('Item');
 await page.locator('#head-create-resource').click();
 await page.locator('[data-cr-name]').fill('Quest');
 await page.locator('[data-submit]').click();
 await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
 await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源有未保存修改');
 await assertAbsent(join(p.root,'config/schemas/Quest.yaml'));
 await page.locator('#ct-draft-save').click();
 await expect.poll(async()=>{try{return await readFile(join(p.root,'config/schemas/Quest.yaml'),'utf8')}catch{return ''}}).toContain('Quest');
 for(const module of ['export','i18n','logs','history','schema']){
  await page.locator(`.ct-sitem[data-module="${module}"]`).click();
  await expect(page.locator(`#page-${module}`)).toBeVisible();
 }
 for(const table of ['Item','Quest']) expect((await p.request('/api/schema-workspace/gen-template',{table})).ok).toBe(true);
 await page.locator('.ct-sitem[data-module="export"]').click();
 await page.locator('#export-start').click();
 await expect(page.locator('#export-badge')).toContainText('成功');
 await page.locator('.ct-sitem[data-module="history"]').click();
 await expect(page.locator('#page-history')).toContainText('2');
 expect(errors).toEqual([]);
 }finally{await p.close();}
});
async function assertAbsent(path){try{await stat(path);throw new Error('unexpected file '+path)}catch(e){if(e.code!=='ENOENT')throw e;}}

for(const width of [740,900,1280])test(`native shell layout ${width}`,async({page})=>{
 const p=await startPanel();try{
 await page.emulateMedia({reducedMotion:"reduce"});await page.setViewportSize({width,height:900});await page.goto(p.url);
 await page.locator('.ct-sitem[data-module="schema"]').click();
 await page.locator(".ct-workspace-layout").waitFor();
 if((await page.locator(".ct-workspace-layout").getAttribute("data-resource-open"))!=="true") await page.locator('#resource-toggle').click();
 await page.locator('.ct-resource-row[data-name="Item"]').click();
 await expect(page.locator('#editor-title')).toHaveText('Item');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:resolve(import.meta.dirname,`../test-results/native-schema-${width}.png`),fullPage:true});
 }finally{await p.close();}
});

test('save retains edits made while response is in flight',async({page})=>{
 const p=await startPanel();let release;
 try{
  await page.goto(p.url);await page.locator('.ct-sitem[data-module="schema"]').click();
  await page.locator('.ct-workspace-layout').waitFor();
  if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
  await page.locator('.ct-resource-row[data-name="Item"]').click();
  async function comment(text){await page.locator('[data-field="Name"] [data-act="comment"]').click();await page.locator('[data-comment-input]').fill(text);await page.locator('[data-submit]').click();}
  await comment('first');await expect(page.locator('#ct-draft-save')).toBeEnabled();
  const held=new Promise(resolve=>release=resolve);
  let reached;const arrived=new Promise(resolve=>reached=resolve);
  await page.route('**/api/schema-workspace/save',async route=>{const response=await route.fetch();reached();await held;await route.fulfill({response});});
  await page.locator('#ct-draft-save').click();await arrived;
  await comment('second');release();
  await expect(page.locator('#ct-draft-save')).toBeEnabled();
  expect(await readFile(join(p.root,'config/schemas/Item.yaml'),'utf8')).toContain('first');
  const state=await page.evaluate(()=>window.__ct.getPageState('schema'));
  expect(state.commands).toHaveLength(1);expect(state.commands[0].payload.value).toBe('second');
  await page.unroute('**/api/schema-workspace/save');await page.locator('#ct-draft-save').click();
  await expect.poll(()=>readFile(join(p.root,'config/schemas/Item.yaml'),'utf8')).toContain('second');
 }finally{release?.();await p.close();}
});

test('failed save keeps the command history, cursor and old baseline across reload',async({page})=>{
 const p=await startPanel();try{
  const quest=join(p.root,'config/schemas/Quest.yaml');
  await writeFile(quest,'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n');
  await page.goto(p.url);await page.locator('.ct-sitem[data-module="schema"]').click();
  await page.locator('.ct-workspace-layout').waitFor();
  if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
  await page.locator('.ct-resource-row[data-name="Item"]').click();
  await page.locator('[data-field="Name"] [data-act="comment"]').click();
  await page.locator('[data-comment-input]').fill('未提交的注释');await page.locator('[data-submit]').click();
  await expect.poll(()=>page.evaluate(()=>Boolean(window.__ct.getPageState('schema').candidateHash))).toBe(true);
  const before=await page.evaluate(()=>{const s=window.__ct.getPageState('schema');return {commands:s.commands,cursor:s.cursor,schemaRevision:s.schemaRevision};});
  const yaml=join(p.root,'config/schemas/Item.yaml'),itemBefore=await readFile(yaml);
  await appendFile(quest,'\n# external edit\n');
  await page.locator('#ct-draft-save').click();
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').saveError?.message||'')).toContain('基线');
  const after=await page.evaluate(()=>{const s=window.__ct.getPageState('schema');return {commands:s.commands,cursor:s.cursor,schemaRevision:s.schemaRevision};});
  expect(after).toEqual(before);
  const disk=await readFile(quest,'utf8');expect(disk).toContain('# external edit');
  expect(await readFile(yaml)).toEqual(itemBefore);
  await page.reload();await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').commands.length)).toBe(1);
  const restored=await page.evaluate(()=>{const s=window.__ct.getPageState('schema');return {commands:s.commands,cursor:s.cursor,schemaRevision:s.schemaRevision};});
  expect(restored).toEqual(before);
  expect(await readFile(quest,'utf8')).toBe(disk);
  expect(await readFile(yaml)).toEqual(itemBefore);
 }finally{await p.close();}
});

test('legacy IndexedDB keeps history and redo; unknown drafts survive writes and discard',async({page})=>{
 const p=await startPanel();try{await page.goto(p.url);
 const result=await page.evaluate(async()=>{
  const store=await import('/static/js/core/draft-store.js');
  const commands=[{type:'one'},{type:'two'}];
  await store.saveDraft('C:\\Data\\Game',{schemaRevision:'old',commands,cursor:1});
  const loaded=await store.loadDraft('C:/Data/Game');
  const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('ct-drafts',1);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
  await new Promise(resolve=>{const tx=db.transaction('drafts','readwrite');tx.objectStore('drafts').put({key:'draft:/unknown',format:'future/99',secret:'keep'});tx.oncomplete=resolve;});
  let rejected=false;try{await store.saveDraft('/unknown',{schemaRevision:'x',commands:[],cursor:0})}catch{rejected=true}
  await store.clearDraft('/unknown').catch(()=>{});
  let preserved;try{await store.loadDraft('/unknown')}catch(e){preserved=e.record}
  db.close();return {loaded,rejected,preserved};
 });
 expect(result.loaded.cursor).toBe(1);expect(result.loaded.commands).toHaveLength(2);expect(result.loaded.schemaRevision).toBe('old');expect(result.rejected).toBe(true);expect(result.preserved[0].secret).toBe('keep');
 }finally{await p.close();}
});

async function openSchema(page,p){
 await page.goto(p.url);await page.locator('.ct-sitem[data-module="schema"]').click();await page.locator('.ct-workspace-layout').waitFor();
}
async function createResource(page,kind,name,first=''){
 await page.locator('#head-create-resource').click();await page.locator(`[data-cr-kind="${kind}"]`).click();await page.locator('[data-cr-name]').fill(name);
 if(kind==='record')await page.locator('[data-cr-field-name]').fill(first);
 if(kind==='enum')await page.locator('[data-cr-item-name]').fill(first);
 await page.locator('[data-submit]').click();await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
}
test('create table, record and enum; selection follows undo and draft survives refresh',async({page})=>{
 const p=await startPanel();try{
 await openSchema(page,p);
 for(const [kind,name,first] of [['table','Quest',''],['record','Reward','Amount'],['enum','Rarity','Common']]){
  await createResource(page,kind,name,first);await expect(page.locator('#editor-title')).toHaveText(name);
 }
 await expect(page.locator('#ct-draft-save')).toBeEnabled();
 await page.locator('#ct-draft-undo').click();await expect(page.locator('#editor-title')).not.toHaveText('Rarity');
 await page.locator('#ct-draft-redo').click();await expect(page.locator('#ct-draft-txt')).toContainText('3 个资源');
 await page.reload();await expect(page.locator('#ct-draft-txt')).toContainText('3 个资源');
 const state=await page.evaluate(()=>window.__ct.getPageState('schema'));expect(state.commands).toHaveLength(3);expect(state.cursor).toBe(3);
 await page.locator('#ct-draft-save').click();await expect.poll(()=>readFile(join(p.root,'config/types/Rarity.yaml'),'utf8').catch(()=>'' )).toContain('Common');
 await assertAbsent(join(p.root,'excel/Quest.xlsx'));
 }finally{await p.close();}
});
test('creation forms retain incomplete, invalid and duplicate input without commands',async({page})=>{
 const p=await startPanel();try{
 await openSchema(page,p);await page.locator('#head-create-resource').click();
 for(const [kind,name,expected] of [['record','Reward','首个字段'],['enum','Rarity','枚举项']]){
  await page.locator(`[data-cr-kind="${kind}"]`).click();await page.locator('[data-cr-name]').fill(name);await page.locator('[data-submit]').click();
  await expect(page.locator('[data-cr-err]')).toContainText(expected);await expect(page.locator('[data-cr-name]')).toHaveValue(name);
 }
 await page.locator('[data-cr-kind="table"]').click();
 for(const name of ['../Bad','Item']){
  await page.locator('[data-cr-name]').fill(name);await page.locator('[data-submit]').click();await expect(page.locator('[data-cr-err]')).not.toBeEmpty();
  expect(await page.evaluate(()=>window.__ct.getPageState('schema').commands.length)).toBe(0);
 }
 }finally{await p.close();}
});
