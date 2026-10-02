import {test,expect} from '@playwright/test';
import {mkdir,readFile,rm,stat,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

async function fixture({record=false,code=false,index=false,ref=false,tableRef=false}={}){
 const panel=await startPanel();
 if(code||index||ref||tableRef)await writeFile(join(panel.root,'config/schemas/Item.yaml'),
  'table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: Name\n    type: string\n    i18n: true\n'+
  (code||index?'  - name: CodeName\n    type: string\n':'')+
  (ref?'  - name: Rewards\n    type: vector<DropReward>\n    excel_columns: 1\n':'')+
  (tableRef?'  - name: ItemTypeId\n    type: int32\n    ref: ItemType.Id\n':'')+
  (index?'indexes:\n  - kind: codename\n':''));
 await writeFile(join(panel.root,'config/schemas/Quest.yaml'),'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n');
 if(tableRef)await writeFile(join(panel.root,'config/schemas/ItemType.yaml'),'table: ItemType\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n');
 await writeFile(join(panel.root,'config/types/ItemRarity.yaml'),'kind: enum\nname: ItemRarity\nvalues:\n  - name: Common\n  - name: Rare\n');
 if(record)await writeFile(join(panel.root,'config/types/DropReward.yaml'),'kind: record\nname: DropReward\nfields:\n  - name: ItemId\n    type: int32\n');
 return panel;
}
async function openSchema(page,panel){
 await page.goto(panel.url);
 if((await page.evaluate(()=>window.innerWidth))<740)await page.locator('#ct-hamb').click();
 await page.locator('.ct-sitem[data-module="schema"]').click();
 if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
 await expect(page.locator('.ct-resource-row[data-name="Item"]')).toBeVisible();
}
async function select(page,name){
 await page.locator(`.ct-resource-row[data-name="${name}"]`).click();
 await expect(page.locator('#editor-title')).toHaveText(name);
}
async function command(page){
 return page.evaluate(()=>window.__ct.getPageState('schema').commands.at(-1));
}

test('resource groups filter across kinds and highlight fuzzy matched characters',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);
  await expect(page.locator('#resource-list .ct-resource-row')).toHaveCount(3);
  await page.locator('#resource-filter').fill('Item');
  await expect(page.locator('#resource-list .ct-resource-row')).toHaveCount(2);
  await expect(page.locator('.ct-resource-row[data-name="Quest"]')).toHaveCount(0);
  await page.locator('#resource-filter').fill('IR');
  await expect(page.locator('.ct-resource-row[data-name="ItemRarity"] mark')).toHaveText(['I','R']);
 }finally{await panel.close();}
});

test('search temporarily expands a collapsed group and preserves its preference on reload',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);
  const tables=page.locator('[data-group="table"]');
  await tables.click();
  await expect(tables).toHaveAttribute('aria-expanded','false');
  await expect(page.locator('.ct-resource-group:has([data-group="table"])')).toHaveAttribute('data-open','false');
  await page.locator('#resource-filter').fill('Item');
  await expect(tables).toHaveAttribute('aria-expanded','true');
  await expect(page.locator('.ct-resource-row[data-name="Item"]')).toBeVisible();
  await page.locator('#resource-filter').fill('');
  await expect(tables).toHaveAttribute('aria-expanded','false');
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect(page.locator('[data-group="table"]')).toHaveAttribute('aria-expanded','false');
 }finally{await panel.close();}
});

test('resource count, keyboard selection and filter preference survive reload',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);
  await expect(page.locator('#resource-summary')).toContainText('3 总计');
  await page.locator('#resource-filter').fill('Item');
  await expect(page.locator('#resource-summary')).toContainText('2 匹配');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(page.locator('#editor-title')).toHaveText('ItemRarity');
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect(page.locator('#resource-filter')).toHaveValue('Item');
  await expect(page.locator('#resource-summary')).toContainText('2 匹配');
 }finally{await panel.close();}
});

test('add-field dialog rejects an invalid name and adds one complete draft field',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);await select(page,'Item');
  await page.locator('#add-field').click();
  await expect(page.locator('[data-af-name]')).toBeFocused();
  await page.locator('[data-af-name]').fill('lowercase');
  await page.locator('[data-af-add]').click();
  await expect(page.locator('[data-af-name]')).toHaveClass(/invalid/);
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(1);
  await page.locator('[data-af-name]').fill('Price');
  await page.locator('[data-af-add]').click();
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await expect(page.locator('.ct-field-grid')).toContainText('Price');
  expect(await command(page)).toMatchObject({type:'add_field',payload:{owner:'table:Item',field:{name:'Price',type:'int32'}}});
 }finally{await panel.close();}
});

test('I18N add-field role restricts the type picker to string',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);await select(page,'Item');
  await page.locator('#add-field').click();
  await page.locator('.ct-dialog .ct-chip', {hasText:'I18N'}).click();
  await page.locator('[data-af-type]').click();
  await expect(page.locator('[data-type-list] .ct-dlg-row')).toHaveText(['string']);
  await page.locator('[data-type="string"]').click();
  await page.locator('[data-af-name]').fill('Note');
  await page.locator('[data-af-add]').click();
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await expect(page.locator('.ct-field-grid')).toContainText('Note');
  expect(await command(page)).toMatchObject({type:'add_field',payload:{owner:'table:Item',field:{name:'Note',type:'string',i18n:true}}});
 }finally{await panel.close();}
});

test('CodeName constraint fixes name and type and disables incompatible controls',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);await select(page,'Quest');
  await page.locator('#add-field').click();
  await page.locator('.ct-dialog .ct-chip', {hasText:'代号'}).click();
  await expect(page.locator('[data-af-name]')).toHaveValue('CodeName');
  await expect(page.locator('[data-af-name]')).toBeDisabled();
  await expect(page.locator('[data-af-type-txt]')).toHaveText('string');
  await expect(page.locator('[data-af-type]')).toBeDisabled();
  await expect(page.locator('input[name="af-role"][value="i18n"]')).toBeDisabled();
  await expect(page.locator('input[name="af-role"][value="server"]')).toHaveCount(0);
  await expect(page.locator('[data-af-vec]')).toBeDisabled();
  await page.locator('[data-af-add]').click();
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  expect(await command(page)).toMatchObject({type:'add_field',payload:{owner:'table:Quest',field:{name:'CodeName',type:'string'}}});
 }finally{await panel.close();}
});

test('primary field locks reordering, type change and deletion but permits comment editing',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);await select(page,'Item');
  const primary=page.locator('tr[data-field="Id"]');
  const ops=primary.locator('.ct-row-ops button');
  await expect(ops).toHaveCount(4);
  await expect(ops.nth(0)).toBeDisabled();
  await expect(ops.nth(1)).toBeDisabled();
  await expect(ops.nth(2)).toBeEnabled();
  await expect(ops.nth(3)).toBeDisabled();
  await expect(ops.nth(0)).toHaveAttribute('title',/主键字段不可调整顺序/);
  await expect(ops.nth(3)).toHaveAttribute('title',/主键字段不可删除/);
  await expect(primary.locator('[data-act="type"]')).toHaveCount(0);
  await expect(page.locator('tr[data-field="Name"] [data-act="type"]')).toHaveCount(1);
  expect(await page.evaluate(()=>window.__ct.getPageState('schema').commands)).toEqual([]);
 }finally{await panel.close();}
});

test('inspector shows selected field properties as a read-only summary',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);await select(page,'Item');
  await page.locator('#side-tab').click();
  await page.locator('tr[data-field="Name"]').click();
  await expect(page.locator('#side-inspector')).toContainText('只读');
  await expect(page.locator('#side-inspector [data-prop]')).toHaveCount(0);
  await expect(page.locator('#field-save')).toHaveCount(0);
  expect(await page.evaluate(()=>window.__ct.getPageState('schema').commands)).toEqual([]);
 }finally{await panel.close();}
});

test('field type picker offers a named Enum and emits a set-type draft command',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);await select(page,'Item');
  await page.locator('tr[data-field="Name"] [data-act="type"]').click();
  await page.locator('[data-fe-type]').click();
  await page.locator('[data-type-search]').fill('ItemRarity');
  await expect(page.locator('[data-type="ItemRarity"]')).toHaveCount(1);
  await page.locator('[data-type="ItemRarity"]').click();
  await page.locator('[data-fe-apply]').click();
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await expect(page.locator('tr[data-field="Name"]')).toContainText('ItemRarity');
  const commands=await page.evaluate(()=>window.__ct.getPageState('schema').commands);
  expect(commands).toContainEqual(expect.objectContaining({type:'set_type',payload:{owner:'table:Item',name:'Name',type_text:'ItemRarity'}}));
  expect(commands).toContainEqual(expect.objectContaining({type:'set_property',payload:{owner:'table:Item',name:'Name',property:'excel_columns',value:null}}));
 }finally{await panel.close();}
});

test('Record editor hides table-only role options but keeps vector available',async({page})=>{
 const panel=await fixture({record:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await expect(page.locator('table.ct-field-grid thead')).toContainText('角色与约束');
  if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
  await select(page,'DropReward');
  await expect(page.locator('table.ct-field-grid thead th')).toHaveText(['字段','类型表达式','Excel','']);
  await page.locator('#add-field').click();
  await expect(page.locator('[data-af-role-row]')).toBeHidden();
  await expect(page.locator('input[name="af-role"][value="i18n"]')).toBeDisabled();
  await expect(page.locator('input[name="af-role"][value="server"]')).toHaveCount(0);
  await expect(page.locator('[data-af-code]')).toBeDisabled();
  await expect(page.locator('[data-af-vec]')).toBeEnabled();
 }finally{await panel.close();}
});

test('390px field cards hide table headers and retain accessible actions without page overflow',async({page})=>{
 const panel=await fixture();try{
  await page.setViewportSize({width:390,height:844});
  await openSchema(page,panel);await select(page,'Item');
  await expect(page.locator('table.ct-field-grid thead')).toBeHidden();
  await expect(page.locator('tr[data-field="Name"] [data-act="type"]')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
 }finally{await panel.close();}
});

test('renaming, moving, changing type and deleting a field records net deletion from the original schema',async({page})=>{
 const panel=await fixture({code:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await page.locator('tr[data-field="Name"] [data-act="rename"]').click();
  await page.locator('[data-form-input]').fill('DisplayName');
  await page.locator('.ct-dialog-mask.open [data-submit]').click();
  await expect(page.locator('tr[data-field="DisplayName"]')).toHaveCount(1);
  await page.locator('tr[data-field="DisplayName"] [data-act="up"]').click();
  await page.locator('tr[data-field="DisplayName"] [data-act="type"]').click();
  await page.locator('[data-fe-type]').click();
  await page.locator('[data-type="int64"]').click();
  await page.locator('[data-fe-apply]').click();
  await expect(page.locator('tr[data-field="DisplayName"]')).toContainText('int64');
  await page.locator('tr[data-field="DisplayName"] [data-act="delete"]').click();
  await page.locator('.ct-dialog-mask.open [data-confirm]').click();
  await expect(page.locator('tr[data-field="DisplayName"]')).toHaveCount(0);
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await page.locator('#ct-draft-txt').click();
  const summary=page.locator('.ct-dialog-mask.open .ct-dialog');
  await expect(summary).toContainText('删除');
  await expect(summary).toContainText('Name');
  await expect(summary).not.toContainText('DisplayName');
 }finally{await panel.close();}
});

test('CodeName index card emits one index command and YAML-only draft summary',async({page})=>{
 const panel=await fixture({code:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await page.getByRole('button',{name:'查询索引'}).click();
  await expect(page.locator('.ct-index-card')).toHaveCount(1);
  await page.locator('[data-index-codename]').check();
  await expect(page.locator('.ct-index-preview')).toContainText('ByCodeName');
  await expect(page.locator('.ct-index-preview')).not.toContainText('ByGroupKey');
  await expect(page.locator('[data-index-kind]')).toHaveCount(0);
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  expect(await command(page)).toMatchObject({type:'set_indexes',payload:{table:'table:Item',indexes:[{kind:'codename'}]}});
  await page.locator('#ct-draft-txt').click();
  await expect(page.locator('.ct-dialog-mask.open .ct-dialog')).toContainText('1 个资源');
  await expect(page.locator('.ct-dialog-mask.open .ct-dialog')).not.toContainText('Accessor');
 }finally{await panel.close();}
});

test('persisted CodeName index can be disabled in draft and remains disabled after reload',async({page})=>{
 const panel=await fixture({index:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await page.getByRole('button',{name:'查询索引'}).click();
  await expect(page.locator('[data-index-codename]')).toBeChecked();
  await page.locator('[data-index-codename]').uncheck();
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
  await select(page,'Item');
  await page.getByRole('button',{name:'查询索引'}).click();
  await expect(page.locator('[data-index-codename]')).not.toBeChecked();
 }finally{await panel.close();}
});

test('CodeName badge appears only when the index is declared',async({page})=>{
 const panel=await fixture({code:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await expect(page.locator('tr[data-field="CodeName"] .ct-badge',{hasText:'CODENAME'})).toHaveCount(0);
  await writeFile(join(panel.root,'config/schemas/Item.yaml'),
   'table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: Name\n    type: string\n    i18n: true\n  - name: CodeName\n    type: string\nindexes:\n  - kind: codename\n');
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
  await select(page,'Item');
  await expect(page.locator('tr[data-field="CodeName"] .ct-badge',{hasText:'CODENAME'})).toHaveCount(1);
  await expect(page.locator('tr[data-field="CodeName"] .ct-field-role')).toContainText('🏷');
  await expect(page.locator('tr[data-field="Id"] .ct-badge',{hasText:'CODENAME'})).toHaveCount(0);
  await expect(page.locator('tr[data-field="Name"] .ct-badge',{hasText:'CODENAME'})).toHaveCount(0);
 }finally{await panel.close();}
});

test('deleting indexed CodeName explicitly removes its index in the same draft',async({page})=>{
 const panel=await fixture({index:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await page.locator('tr[data-field="CodeName"] [data-act="delete"]').click();
  await expect(page.locator('.ct-dialog-mask.open')).toContainText('codename 索引');
  await expect(page.locator('.ct-dialog-mask.open')).toContainText('一并移除');
  await page.locator('.ct-dialog-mask.open [data-confirm]').click();
  await expect(page.locator('tr[data-field="CodeName"]')).toHaveCount(0);
  await page.getByRole('button',{name:'查询索引'}).click();
  await expect(page.locator('[data-index-codename]')).not.toBeChecked();
  expect(await page.evaluate(()=>window.__ct.getPageState('schema').commands.map(c=>c.type))).toEqual(['set_indexes','delete_field']);
 }finally{await panel.close();}
});

test('renaming indexed CodeName explicitly removes its index in the same draft',async({page})=>{
 const panel=await fixture({index:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await page.locator('tr[data-field="CodeName"] [data-act="rename"]').click();
  await expect(page.locator('.ct-dialog-mask.open')).toContainText('codename 索引');
  await page.locator('.ct-dialog-mask.open [data-form-input]').fill('TypeCode');
  await page.locator('.ct-dialog-mask.open [data-submit]').click();
  await expect(page.locator('tr[data-field="TypeCode"]')).toHaveCount(1);
  await expect(page.locator('tr[data-field="CodeName"]')).toHaveCount(0);
  await page.getByRole('button',{name:'查询索引'}).click();
  await expect(page.locator('[data-index-codename]')).not.toBeChecked();
  expect(await page.evaluate(()=>window.__ct.getPageState('schema').commands.map(c=>c.type))).toEqual(['set_indexes','rename_field']);
 }finally{await panel.close();}
});

test('Enum editor adds, renames and removes values in one draft',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);await select(page,'ItemRarity');
  await page.locator('#enum-add-value').click();
  await page.locator('[data-aev-name]').fill('Legendary');
  await page.locator('.ct-dialog-mask.open [data-submit]').click();
  await expect(page.locator('tr[data-enum-value="Legendary"]')).toHaveCount(1);
  await page.locator('tr[data-enum-value="Legendary"] [data-act="rename"]').click();
  await page.locator('[data-form-input]').fill('Mythic');
  await page.locator('.ct-dialog-mask.open [data-submit]').click();
  await expect(page.locator('tr[data-enum-value="Mythic"]')).toHaveCount(1);
  await page.locator('tr[data-enum-value="Common"] [data-act="delete"]').click();
  await expect(page.locator('tr[data-enum-value="Common"]')).toHaveCount(0);
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
 }finally{await panel.close();}
});

test('referenced Record deletion is blocked with its referring field disclosed',async({page})=>{
 const panel=await fixture({record:true,ref:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await page.locator('[data-navigate-type="DropReward"]').click();
  await expect(page.locator('#editor-title')).toHaveText('DropReward');
  await page.locator('#head-delete-resource').click();
  const dialog=page.locator('.ct-dialog-mask.open .ct-dialog');
  await expect(dialog).toContainText('无法删除');
  await expect(dialog).toContainText('Rewards');
  await expect(dialog).toContainText('YAML');
  await expect(dialog).toContainText('Excel');
  await expect(dialog).toContainText('产物');
  await expect(dialog.locator('[data-confirm]')).toBeDisabled();
  await expect(page.locator('#dl-seeplan')).toHaveCount(0);
 }finally{await panel.close();}
});

test('ref field link navigates to its referenced Table',async({page})=>{
 const panel=await fixture({tableRef:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await expect(page.locator('[data-navigate-type="ItemType"]')).toHaveCount(1);
  await page.locator('[data-navigate-type="ItemType"]').click();
  await expect(page.locator('#editor-title')).toHaveText('ItemType');
  await expect(page.locator('tr[data-field="Id"]')).toHaveCount(1);
 }finally{await panel.close();}
});

test('turning an index on and off leaves zero net difference but preserves undo history',async({page})=>{
 const panel=await fixture({code:true});try{
  await openSchema(page,panel);await select(page,'Item');
  await page.getByRole('button',{name:'查询索引'}).click();
  const checkbox=page.locator('[data-index-codename]');
  await checkbox.check();
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await checkbox.uncheck();
  await expect(page.locator('#ct-draft-txt')).toContainText('无未保存修改');
  await expect(page.locator('#ct-draft-save')).toBeDisabled();
  await expect(page.locator('#ct-draft-undo')).toBeEnabled();
  expect(await page.evaluate(()=>window.__ct.getPageState('schema').commands.length)).toBe(2);
 }finally{await panel.close();}
});

test('module navigation remains keyboard reachable and Quick Open restores Schema from another module',async({page})=>{
 const panel=await fixture();try{
  await page.goto(panel.url);
  const first=page.locator('.ct-sitem').first();
  await first.focus();
  await expect(first).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(first).toHaveClass(/active/);
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect(page.locator('.ct-resource-row[data-name="Item"]')).toHaveCount(1);
  await page.locator('.ct-sitem[data-module="export"]').click();
  await expect(page.locator('#page-schema')).toHaveAttribute('inert','');
  await page.keyboard.press('Control+p');
  await expect(page.locator('.ct-dlg-palette [data-qo-input]')).toBeFocused();
  await expect(page.locator('#page-schema')).not.toHaveAttribute('inert','');
  await page.keyboard.press('Escape');
  await expect(page.locator('.ct-dlg-palette')).toHaveCount(0);
 }finally{await panel.close();}
});

test('inspector resize widens the pane and saves its preferred width',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);
  await page.locator('.ct-side-tab').click();
  const handle=page.locator('.ct-resize-handle.right');
  const width=()=>page.locator('.ct-side').evaluate(el=>el.getBoundingClientRect().width);
  await expect.poll(width).toBeGreaterThan(290);
  // 工作区列宽带 200ms 的 grid 过渡。不等它落定，before 会取在动画中途，手柄也会在
  // mousedown 前继续滑动：拖动落空后仅靠剩余动画就能满足宽度断言，而 localStorage
  // 从未被写入（CI 上表现为 Number(null) === 0）。
  await expect.poll(async()=>{const first=await width();await page.waitForTimeout(60);return Math.abs(await width()-first)<0.5;}).toBe(true);
  const before=await width();
  const box=await handle.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
  await page.mouse.down();
  await page.mouse.move(box.x-80,box.y+box.height/2,{steps:5});
  await page.mouse.up();
  // 必须真被拖宽 80px 量级；过渡余量不足以满足这个门槛。
  await expect.poll(width).toBeGreaterThan(before+40);
  await expect.poll(async()=>Number(await page.evaluate(()=>localStorage.getItem('ct-side-w-wide')))).toBeGreaterThan(before);
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await page.locator('.ct-side-tab').click();
  await expect.poll(width).toBeGreaterThan(before+40);
 }finally{await panel.close();}
});

test('deleting a Table saves YAML only and retains its Excel and exported JSON',async({page})=>{
 const panel=await fixture();try{
  const book=join(panel.root,'excel/Quest.xlsx');
  const output=join(panel.root,'output/json/Quest_zh.json');
  await mkdir(join(panel.root,'excel'),{recursive:true});
  await mkdir(join(panel.root,'output/json'),{recursive:true});
  await writeFile(book,'quest-data');await writeFile(output,'{}');
  await openSchema(page,panel);await select(page,'Quest');
  await page.locator('#head-delete-resource').click();
  await page.locator('.ct-dialog-mask.open [data-confirm]').click();
  await expect(page.locator('#ct-draft-txt')).toContainText('1 个资源');
  await page.locator('#ct-draft-save').click();
  await expect(page.locator('#ct-draftbar')).toBeHidden();
  expect(await stat(join(panel.root,'config/schemas/Quest.yaml')).catch(e=>e.code==='ENOENT'?null:Promise.reject(e))).toBeNull();
  expect(await readFile(book,'utf8')).toBe('quest-data');
  expect(await readFile(output,'utf8')).toBe('{}');
 }finally{await panel.close();}
});

test('broken Schema YAML shows its file error and recovers after the file is removed',async({page})=>{
 const panel=await fixture();try{
  const broken=join(panel.root,'config/schemas/Broken.yaml');
  await writeFile(broken,'table: [oops\n');
  await page.goto(panel.url);
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect(page.locator('#resource-load-error')).toContainText('Broken.yaml');
  await expect(page.locator('#resource-list .ct-resource-row')).toHaveCount(0);
  await expect(page.locator('#empty-create-resource')).toHaveCount(0);
  await expect(page.locator('#draft-banner')).toContainText('Schema 快照加载失败');
  await rm(broken);
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect(page.locator('.ct-resource-row[data-name="Item"]')).toHaveCount(1);
  await expect(page.locator('#resource-load-error')).toHaveCount(0);
  await expect(page.locator('#draft-banner')).not.toContainText('Schema 快照加载失败');
 }finally{await panel.close();}
});
