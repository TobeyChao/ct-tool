import {test,expect} from '@playwright/test';
import {mkdtemp,mkdir,stat,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

async function openSchema(page,panel){
 await page.goto(panel.url);
 await page.locator('.ct-sitem[data-module="schema"]').click();
 await page.locator('.ct-workspace-layout').waitFor();
 if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
}
async function absent(path){
 return (await stat(path).catch(error=>error.code==='ENOENT'?null:Promise.reject(error)))===null;
}
async function createResource(page,kind,name,{field='',type='',item=''}={}){
 await page.locator('#head-create-resource').click();
 await page.locator(`[data-cr-kind="${kind}"]`).click();
 await page.locator('[data-cr-name]').fill(name);
 if(kind==='record'){
  await page.locator('[data-cr-field-name]').fill(field);
  if(type){
   await page.locator('[data-cr-field-type]').click();
   await page.locator(`[data-type-list] [data-type="${type}"]`).click();
  }
 }
 if(kind==='enum')await page.locator('[data-cr-item-name]').fill(item);
 await page.locator('.ct-dialog-mask.open [data-submit]').click();
 await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
 await expect(page.locator('#editor-title')).toHaveText(name);
}

test('header and group creation entries choose the correct form; a Table starts with Id only',async({page})=>{
 const panel=await startPanel();try{
  await openSchema(page,panel);
  await page.locator('#head-create-resource').click();
  await expect(page.locator('[data-cr-kind="table"]')).toHaveClass(/active/);
  await page.keyboard.press('Escape');
  await page.locator('[data-create-kind="enum"]').click();
  await expect(page.locator('[data-cr-kind="enum"]')).toHaveClass(/active/);
  await expect(page.locator('[data-cr-item]')).toBeVisible();
  await expect(page.locator('[data-cr-field]')).toBeHidden();
  await page.keyboard.press('Escape');
  await page.locator('#head-create-resource').click();
  await page.locator('[data-cr-name]').fill('Quest');
  await page.locator('[data-submit]').click();
  await expect(page.locator('#editor-title')).toHaveText('Quest');
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await expect(page.locator('.ct-field-grid')).toContainText('Id');
  await expect(page.locator('.ct-field-grid')).toContainText('int32');
  expect(await absent(join(panel.root,'config/schemas/Quest.yaml'))).toBe(true);
 }finally{await panel.close();}
});

test('an empty workspace can start a Record draft from its empty-state entry',async({page})=>{
 const root=await mkdtemp(join(tmpdir(),'ct-empty-schema-'));
 await mkdir(join(root,'config/schemas'),{recursive:true});
 await mkdir(join(root,'config/types'),{recursive:true});
 await writeFile(join(root,'config/global.yaml'),'primary_lang: zh\nsecondary_langs: [en]\n');
 const panel=await startPanel({rootDir:root});try{
  await openSchema(page,panel);
  await page.locator('#empty-create-resource').click();
  await page.locator('[data-cr-kind="record"]').click();
  await page.locator('[data-cr-name]').fill('DropReward');
  await page.locator('[data-cr-field-name]').fill('Min');
  await page.locator('[data-submit]').click();
  await expect(page.locator('#editor-title')).toHaveText('DropReward');
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  expect(await absent(join(root,'config/types/DropReward.yaml'))).toBe(true);
 }finally{await panel.close();}
});

test('invalid or cross-kind duplicate names keep the form open without adding commands',async({page})=>{
 const panel=await startPanel();try{
  await openSchema(page,panel);
  await page.locator('#head-create-resource').click();
  await page.locator('[data-cr-name]').fill('bad_name');
  await page.locator('[data-submit]').click();
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(1);
  await expect(page.locator('[data-cr-name]')).toHaveValue('bad_name');
  await page.locator('[data-cr-kind="enum"]').click();
  await page.locator('[data-cr-name]').fill('Item');
  await page.locator('[data-cr-item-name]').fill('Common');
  await page.locator('[data-submit]').click();
  await expect(page.locator('[data-cr-err]')).toContainText('已被占用');
  expect(await page.evaluate(()=>window.__ct.getPageState('schema').commands)).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(page.locator('#ct-draftbar')).toBeHidden();
 }finally{await panel.close();}
});

test('two immediate submit clicks add one Table command and one resource row',async({page})=>{
 const panel=await startPanel();try{
  await openSchema(page,panel);
  await page.locator('#head-create-resource').click();
  await page.locator('[data-cr-name]').fill('Quest');
  await page.locator('[data-submit]').evaluate(button=>{
   button.dispatchEvent(new MouseEvent('click',{bubbles:true}));
   button.dispatchEvent(new MouseEvent('click',{bubbles:true}));
  });
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  expect(await page.evaluate(()=>window.__ct.getPageState('schema').commands.length)).toBe(1);
  await expect(page.locator('.ct-resource-row[data-name="Quest"]')).toHaveCount(1);
 }finally{await panel.close();}
});

test('saving new Record and Enum resources never offers a Table template entry',async({page})=>{
 const panel=await startPanel();try{
  await openSchema(page,panel);
  await page.locator('#head-create-resource').click();
  await page.locator('[data-cr-kind="enum"]').click();
  await page.locator('[data-cr-name]').fill('ItemRarity');
  await page.locator('[data-cr-item-name]').fill('Common');
  await page.locator('[data-submit]').click();
  await expect(page.locator('#ct-draft-save')).toBeEnabled();
  await page.locator('#ct-draft-save').click();
  await expect(page.locator('#ct-draftbar')).toBeHidden();
  await expect(page.locator('#template-unsaved')).toHaveCount(0);
  await expect(page.locator('.banner-gen-template[data-table="ItemRarity"]')).toHaveCount(0);
  await expect(page.locator('.ct-resource-row[data-name="ItemRarity"]')).toHaveCount(1);
  expect(await absent(join(panel.root,'excel/ItemRarity.xlsx'))).toBe(true);
  await page.locator('#head-create-resource').click();
  await page.locator('[data-cr-kind="record"]').click();
  await page.locator('[data-cr-name]').fill('DropReward');
  await page.locator('[data-cr-field-name]').fill('Min');
  await page.locator('[data-submit]').click();
  await page.locator('#ct-draft-save').click();
  await expect(page.locator('#ct-draftbar')).toBeHidden();
  await expect(page.locator('#template-unsaved')).toHaveCount(0);
  await expect(page.locator('.banner-gen-template[data-table="DropReward"]')).toHaveCount(0);
  await expect(page.locator('.ct-resource-row[data-name="DropReward"]')).toHaveCount(1);
  expect(await absent(join(panel.root,'excel/DropReward.xlsx'))).toBe(true);
 }finally{await panel.close();}
});

test('at 390px the creation entry supports keyboard focus, Escape and explicit submit',async({page})=>{
 const panel=await startPanel();try{
  await page.setViewportSize({width:390,height:844});
  await page.goto(panel.url);
  await page.locator('#ct-hamb').click();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await page.locator('.ct-workspace-layout').waitFor();
  await page.locator('#head-create-resource').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('[data-cr-name]')).toBeFocused();
  await expect(page.locator('[data-cr-kind="table"]')).toHaveClass(/active/);
  await page.keyboard.press('Escape');
  await expect(page.locator('#ct-draftbar')).toBeHidden();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.locator('#head-create-resource').focus();
  await page.keyboard.press('Enter');
  await page.keyboard.type('Quest');
  await page.keyboard.press('Enter');
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(1);
  await page.locator('.ct-dialog-mask.open [data-submit]').click();
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 }finally{await panel.close();}
});

test('unsaved Enum, Record and Table are immediately usable as field types, ref targets and Quick Open resources',async({page})=>{
 const panel=await startPanel();try{
  await openSchema(page,panel);
  await createResource(page,'enum','ItemRarity',{item:'Common'});
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await createResource(page,'record','DropReward',{field:'Rarity',type:'ItemRarity'});
  await expect(page.locator('#ct-draft-txt')).toContainText('2 个资源');
  await createResource(page,'table','Quest');
  await expect(page.locator('#ct-draft-txt')).toContainText('3 个资源');
  if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
  await page.locator('.ct-resource-row[data-name="Item"]').click();
  await expect(page.locator('#editor-title')).toHaveText('Item');
  await page.locator('#add-field').click();
  await page.locator('[data-af-name]').fill('Reward');
  await page.locator('[data-af-type]').click();
  await page.locator('[data-type-list] [data-type="DropReward"]').click();
  await page.locator('[data-af-add]').click();
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
  await page.locator('#add-field').click();
  await page.locator('[data-af-name]').fill('QuestId');
  await page.locator('.ct-dialog .ct-chip',{hasText:'引用'}).click();
  await expect(page.locator('[data-ref-list] [data-ref="Quest.Id"]')).toHaveCount(1);
  await expect(page.locator('[data-ref-list] [data-ref="Item.Id"]')).toHaveCount(1);
  await expect(page.locator('[data-ref-list] [data-ref="Item.Name"]')).toHaveCount(0);
  await page.locator('[data-ref-list] [data-ref="Quest.Id"]').click();
  await page.locator('[data-af-add]').click();
  await expect(page.locator('.ct-field-grid')).toContainText('Reward');
  await expect(page.locator('.ct-field-grid')).toContainText('QuestId');
  await page.locator('#add-field').click();
  await page.locator('[data-af-type]').click();
  await expect(page.locator('[data-type-list] [data-type="DropReward"]')).toHaveCount(1);
  await expect(page.locator('[data-type-list] [data-type="Quest"]')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+p');
  await page.locator('[data-qo-input]').fill('ItemRarity');
  await expect(page.locator('[data-qo-list] [data-qo="ItemRarity"]')).toHaveCount(1);
  await expect(page.locator('#resource-summary')).toContainText('4 总计');
  expect(await absent(join(panel.root,'config/types/ItemRarity.yaml'))).toBe(true);
  expect(await absent(join(panel.root,'config/types/DropReward.yaml'))).toBe(true);
  expect(await absent(join(panel.root,'config/schemas/Quest.yaml'))).toBe(true);
 }finally{await panel.close();}
});

test('Record creation and field editing omit ref while Table primary cannot be renamed',async({page})=>{
 const panel=await startPanel();try{
  await openSchema(page,panel);
  await page.locator('#head-create-resource').click();
  await page.locator('[data-cr-kind="record"]').click();
  await expect(page.locator('[data-cr-ref]')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await createResource(page,'record','DropReward',{field:'Min'});
  await page.locator('#add-field').click();
  await expect(page.locator('[data-af-ref]')).toBeDisabled();
  await page.keyboard.press('Escape');
  if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
  await page.locator('.ct-resource-row[data-name="Item"]').click();
  const primary=page.locator('tr[data-field="Id"] [data-act="rename"]');
  await expect(primary).toBeDisabled();
  await expect(primary).toHaveAttribute('title','主键字段不可改名');
  await expect(page.locator('tr[data-field="Name"] [data-act="rename"]')).toBeEnabled();
 }finally{await panel.close();}
});
