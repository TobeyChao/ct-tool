import {test,expect} from '@playwright/test';
import {readFile,stat} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

async function openItem(page,panel){
 await page.goto(panel.url);
 await page.locator('.ct-sitem[data-module="schema"]').click();
 await page.locator('.ct-workspace-layout').waitFor();
 if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
 await page.locator('.ct-resource-row[data-name="Item"]').click();
 await expect(page.locator('#editor-title')).toHaveText('Item');
}
async function selectItem(page){
 if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
 await page.locator('.ct-resource-row[data-name="Item"]').click();
 await expect(page.locator('#editor-title')).toHaveText('Item');
}
async function addPrice(page){
 await page.locator('#add-field').click();
 await page.locator('[data-af-name]').fill('Price');
 await page.locator('[data-af-add]').click();
 await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
 await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
}
async function storedDraft(page){
 return page.evaluate(async()=>{
  const store=await import('/static/js/core/draft-store.js');
  return store.loadDraft(window.__ct.getPageState('schema').root);
 });
}

test('global draftbar saves a field to YAML without a mandatory review dialog',async({page})=>{
 const panel=await startPanel();try{
  await openItem(page,panel);await addPrice(page);
  await expect(page.locator('#review-plan')).toHaveCount(0);
  await page.locator('#ct-draft-txt').click();
  await expect(page.locator('.ct-dialog-mask.open')).toContainText('1 个资源');
  await page.locator('.ct-dialog-mask.open [data-close]').last().click();
  await page.locator('#ct-draft-save').click();
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
  await expect(page.locator('#ct-draftbar')).toBeHidden();
  await expect.poll(()=>readFile(join(panel.root,'config/schemas/Item.yaml'),'utf8')).toContain('Price');
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await selectItem(page);
  await expect(page.locator('.ct-field-grid')).toContainText('Price');
  await expect.poll(async()=>(await storedDraft(page))?.commands||[]).toEqual([]);
 }finally{await panel.close();}
});

test('discard confirmation removes an unsaved field and clears the command history',async({page})=>{
 const panel=await startPanel();try{
  await openItem(page,panel);await addPrice(page);
  await expect(page.locator('#discard-draft')).toHaveCount(0);
  await page.locator('#ct-draft-discard').click();
  await expect(page.locator('.ct-dialog-mask.open')).toContainText('1 个资源');
  await page.locator('.ct-dialog-mask.open [data-confirm]').click();
  await expect(page.locator('#ct-draftbar')).toBeHidden();
  await expect(page.locator('.ct-field-grid')).not.toContainText('Price');
  expect(await page.evaluate(()=>window.__ct.getPageState('schema').commands)).toEqual([]);
  expect(await readFile(join(panel.root,'config/schemas/Item.yaml'),'utf8')).not.toContain('Price');
 }finally{await panel.close();}
});

test('an unsaved field and its undo cursor survive reload without applying the redo branch',async({page})=>{
 const panel=await startPanel();try{
  await openItem(page,panel);await addPrice(page);
  await expect.poll(async()=>(await storedDraft(page))?.commands?.length).toBe(1);
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await selectItem(page);
  await expect(page.locator('.ct-field-grid')).toContainText('Price');
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await page.locator('#ct-draft-undo').click();
  await expect.poll(async()=>(await storedDraft(page))?.cursor).toBe(0);
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await selectItem(page);
  await expect(page.locator('.ct-field-grid')).not.toContainText('Price');
  await expect(page.locator('#ct-draft-redo')).toBeEnabled();
  const state=await page.evaluate(()=>window.__ct.getPageState('schema'));
  expect(state.commands).toHaveLength(1);
  expect(state.cursor).toBe(0);
  expect(await readFile(join(panel.root,'config/schemas/Item.yaml'),'utf8')).not.toContain('Price');
 }finally{await panel.close();}
});

test('saving Schema refreshes drift status without rebuilding Excel until explicit template update',async({page})=>{
 const panel=await startPanel();try{
  expect((await panel.request('/api/schema-workspace/gen-template',{table:'Item'})).status).toBe(200);
  const book=join(panel.root,'excel/Item.xlsx');
  await openItem(page,panel);await addPrice(page);
  const before={bytes:await readFile(book),mtime:(await stat(book,{bigint:true})).mtimeNs};
  await page.locator('#ct-draft-save').click();
  await expect(page.locator('#ct-draftbar')).toBeHidden();
  await expect(page.locator('#template-note')).toContainText('Item');
  expect(await readFile(book)).toEqual(before.bytes);
  expect((await stat(book,{bigint:true})).mtimeNs).toBe(before.mtime);
  await page.locator('.banner-gen-template[data-table="Item"]').click();
  await expect(page.locator('.banner-gen-template[data-table="Item"]')).toHaveCount(0);
  expect(await readFile(book)).not.toEqual(before.bytes);
  await expect(page.locator('#ct-toast')).toContainText('模板已更新：Item');
  await expect(page.locator('#ct-draftbar')).toBeHidden();
 }finally{await panel.close();}
});

test('a clean workspace status after Schema save does not show a false template drift notice',async({page})=>{
 const panel=await startPanel();try{
  await openItem(page,panel);await addPrice(page);
  await page.route('**/api/workspace',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,data:{root:panel.root,status:{changed:[],drifted:[],missing:[]}}})}));
  await page.locator('#ct-draft-save').click();
  await expect(page.locator('#ct-draftbar')).toBeHidden();
  await expect(page.locator('#template-note')).toHaveCount(0);
  await expect.poll(()=>readFile(join(panel.root,'config/schemas/Item.yaml'),'utf8')).toContain('Price');
 }finally{await panel.close();}
});

test('a busy Schema save response keeps the draft and original YAML for retry',async({page})=>{
 const panel=await startPanel();try{
  await openItem(page,panel);await addPrice(page);
  const path=join(panel.root,'config/schemas/Item.yaml');
  const original=await readFile(path);
  let saves=0;
  await page.route('**/api/schema-workspace/save',route=>{
   saves++;
   return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({ok:false,error:'工作区正在保存、导出或部署',busy:true})});
  });
  await page.locator('#ct-draft-save').click();
  await expect(page.locator('#ct-draft-txt')).toContainText('工作区正在导出或部署');
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await expect(page.locator('.ct-field-grid')).toContainText('Price');
  expect(await readFile(path)).toEqual(original);
  expect(saves).toBe(1);
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await selectItem(page);
  await expect(page.locator('.ct-field-grid')).toContainText('Price');
  expect(await readFile(path)).toEqual(original);
 }finally{await panel.close();}
});
