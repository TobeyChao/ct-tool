import {test,expect} from '@playwright/test';
import {readFile,appendFile} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

async function openItem(page,panel){
 await page.goto(panel.url);
 await page.locator('.ct-sitem[data-module="schema"]').click();
 await page.locator('.ct-workspace-layout').waitFor();
 if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
 await page.locator('.ct-resource-row[data-name="Item"]').click();
}
async function comment(page,text){
 await page.locator('[data-field="Name"] [data-act="comment"]').click();
 await page.locator('[data-comment-input]').fill(text);
 await page.locator('[data-submit]').click();
 await expect.poll(()=>page.evaluate(()=>Boolean(window.__ct.getPageState('schema').candidateHash))).toBe(true);
}

test('candidate and save send the original baseline, full history and active cursor through undo and redo',async({page})=>{
 const p=await startPanel();try{
  await openItem(page,p);
  const original=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const candidates=[];let saveBody;
  await page.route('**/api/schema-workspace/candidate',async route=>{
   candidates.push(route.request().postDataJSON());await route.continue();
  });
  await page.route('**/api/schema-workspace/save',async route=>{
   saveBody=route.request().postDataJSON();await route.continue();
  });
  await comment(page,'first-stage');await comment(page,'second-stage');
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').netDiff?.changedResources)).toBe(1);
  await page.locator('#ct-draft-undo').click();
  await expect.poll(()=>page.evaluate(()=>{const s=window.__ct.getPageState('schema');return s.cursor===1&&Boolean(s.candidateHash);})).toBe(true);
  await page.locator('#ct-draft-undo').click();
  await expect.poll(()=>page.evaluate(()=>{const s=window.__ct.getPageState('schema');return s.cursor===0&&s.netDiff?.isNoOp===true;})).toBe(true);
  await expect(page.locator('#ct-draft-save')).toBeDisabled();
  await expect(page.locator('#ct-draft-redo')).toBeEnabled();
  await page.locator('#ct-draft-redo').click();
  await page.locator('#ct-draft-redo').click();
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').cursor)).toBe(2);
  await page.keyboard.press('Control+z');await page.keyboard.press('Control+z');
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').cursor)).toBe(0);
  await page.keyboard.press('Control+Shift+z');
  await expect.poll(()=>page.evaluate(()=>{const s=window.__ct.getPageState('schema');return s.cursor===1&&Boolean(s.candidateHash);})).toBe(true);
  await page.locator('#ct-draft-redo').click();
  await expect.poll(()=>page.evaluate(()=>{const s=window.__ct.getPageState('schema');return s.cursor===2&&Boolean(s.candidateHash);})).toBe(true);
  await page.locator('#ct-draft-undo').click();
  await expect.poll(()=>page.evaluate(()=>{const s=window.__ct.getPageState('schema');return s.cursor===1&&Boolean(s.candidateHash);})).toBe(true);
  const undone=candidates.findLast(body=>body.cursor===1&&body.commands.length===2);
  expect(undone).toBeTruthy();expect(undone.schemaRevision).toBe(original);
  expect(Number.isInteger(undone.draftGeneration)).toBe(true);
  await page.locator('#ct-draft-save').click();
  await expect.poll(()=>saveBody).toBeTruthy();
  expect(saveBody.schemaRevision).toBe(original);
  expect(saveBody.commands).toHaveLength(2);expect(saveBody.cursor).toBe(1);
  expect(saveBody.candidateHash).toMatch(/^[0-9a-f]{64}$/);
  const path=join(p.root,'config/schemas/Item.yaml');
  await expect.poll(()=>readFile(path,'utf8')).toContain('first-stage');
  expect(await readFile(path,'utf8')).not.toContain('second-stage');
 }finally{await p.close();}
});

test('discard invalidates a delayed candidate response',async({page})=>{
 const p=await startPanel();let release;try{
  await openItem(page,p);
  let arrived;const intercepted=new Promise(resolve=>arrived=resolve);
  const held=new Promise(resolve=>release=resolve);
  await page.route('**/api/schema-workspace/candidate',async route=>{
   arrived();await held;await route.continue();
  });
  await page.locator('[data-field="Name"] [data-act="comment"]').click();
  await page.locator('[data-comment-input]').fill('discard-me');
  await page.locator('[data-submit]').click();await intercepted;
  await page.evaluate(()=>window.dispatchEvent(new CustomEvent('ct:draft-action',{detail:{type:'discard'}})));
  await page.locator('.ct-dialog-mask.open [data-confirm]').click();
  const done=page.waitForResponse(response=>response.url().endsWith('/api/schema-workspace/candidate'));
  release();await done;
  await page.waitForTimeout(60); // let the response handler finish after fetch resolves
  const state=await page.evaluate(()=>{const s=window.__ct.getPageState('schema');return {commands:s.commands,cursor:s.cursor,hash:s.candidateHash,netDiff:s.netDiff,computing:s.candidateComputing};});
  expect(state).toEqual({commands:[],cursor:0,hash:'',netDiff:null,computing:false});
  await expect(page.locator('#ct-draft-save')).toBeDisabled();
 }finally{release?.();await p.close();}
});

test('candidate refresh preserves the original baseline and disables save after an external change',async({page})=>{
 const p=await startPanel();let release;try{
  await openItem(page,p);await comment(page,'unsaved-field-comment');
  const original=await page.evaluate(()=>window.__ct.getPageState('schema').schemaRevision);
  const requests=[];let reached;const arrived=new Promise(resolve=>reached=resolve);
  const held=new Promise(resolve=>release=resolve);
  await page.route('**/api/schema-workspace/candidate',async route=>{
   const body=route.request().postDataJSON();requests.push(body);
   if(requests.length===1){reached();await held;}
   await route.continue();
  });
  await page.locator('#ct-draft-undo').click();await arrived;
  await expect(page.locator('#ct-draft-save')).toBeDisabled();
  const yaml=join(p.root,'config/schemas/Item.yaml');await appendFile(yaml,'\n# external change\n');
  release();
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').notice)).toContain('基线');
  await page.locator('#ct-draft-redo').click();
  await expect.poll(()=>requests.length).toBe(2);
  expect(requests.every(request=>request.schemaRevision===original)).toBe(true);
  await expect(page.locator('#ct-draft-save')).toBeDisabled();
  const state=await page.evaluate(()=>{const s=window.__ct.getPageState('schema');return {revision:s.schemaRevision,cursor:s.cursor,commands:s.commands};});
  expect(state.revision).toBe(original);expect(state.cursor).toBe(1);expect(state.commands).toHaveLength(1);
  expect(await readFile(yaml,'utf8')).not.toContain('unsaved-field-comment');
 }finally{release?.();await p.close();}
});

test('a failed status refresh after a successful save does not request another save',async({page})=>{
 const p=await startPanel();try{
  await openItem(page,p);await comment(page,'saved-despite-status-failure');
  let saves=0;
  await page.route('**/api/schema-workspace/save',async route=>{saves++;await route.continue();});
  await page.route('**/api/workspace',route=>route.fulfill({status:500,contentType:'application/json',body:'{"ok":false,"error":"status boom"}'}));
  await page.locator('#ct-draft-save').click();
  await expect.poll(()=>readFile(join(p.root,'config/schemas/Item.yaml'),'utf8')).toContain('saved-despite-status-failure');
  await expect.poll(()=>page.evaluate(()=>window.__ct.getPageState('schema').statusError)).toContain('暂不可用');
  const state=await page.evaluate(()=>{const s=window.__ct.getPageState('schema');return {commands:s.commands,cursor:s.cursor,error:s.saveError?.message||''};});
  expect(state).toEqual({commands:[],cursor:0,error:''});
  expect(saves).toBe(1);
  await page.waitForTimeout(100);
  expect(saves).toBe(1);
 }finally{await p.close();}
});
