import {test,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

async function seedI18n(panel){
 await mkdir(join(panel.root,'i18n/source'),{recursive:true});
 await mkdir(join(panel.root,'i18n/en'),{recursive:true});
 const source={'1.Name':'很长的原文'.repeat(35),'2.Name':'木盾','3.Name':'铁甲'};
 await writeFile(join(panel.root,'i18n/source/Item.json'),JSON.stringify(source));
 await writeFile(join(panel.root,'i18n/en/Item.json'),JSON.stringify({
  '1.Name':{source:source['1.Name'],text:'Sword',confirmed:true,status:'translated'},
  '2.Name':{source:source['2.Name'],text:'Shield',confirmed:true,status:'translated'},
  '3.Name':{source:source['3.Name'],text:'',confirmed:false,status:'missing'},
 }));
}
async function openI18n(page,panel){
 await page.goto(panel.url);
 if((await page.evaluate(()=>innerWidth))<740)await page.locator('#ct-hamb').click();
 await page.locator('.ct-sitem[data-module="i18n"]').click();
 await expect(page.locator('.ct-i18n-table tbody tr')).toHaveCount(3);
}

test('fresh native workspace renders an empty export history',async({page})=>{
 const panel=await startPanel();try{
  await page.goto(panel.url);
  await page.locator('.ct-sitem[data-module="history"]').click();
  await expect(page.locator('#page-history .ct-empty-sub')).toHaveText('暂无导出历史');
 }finally{await panel.close();}
});

test('native history displays both stored and imported legacy successes with success badges',async({page})=>{
 const panel=await startPanel();try{
  await mkdir(join(panel.root,'cache'),{recursive:true});
  await writeFile(join(panel.root,'cache/history.json'),JSON.stringify({format:'desktop-history/1',entries:[
   {time:'2026-09-29T01:00:00Z',scope:'全部表 × 全量语言',result:'success',tables:4,elapsed:0.2,forced:false,error:''},
  ]}));
  await writeFile(join(panel.root,'cache/panel_history.json'),JSON.stringify([
   {time:'2026-09-29T00:00:00Z',scope:'全部表 × 全量语言',result:'成功',tables:3,elapsed:0.1,forced:false,error:''},
  ]));
  await page.goto(panel.url);
  await page.locator('.ct-sitem[data-module="history"]').click();
  await expect(page.locator('#page-history .ct-badge-ok')).toHaveText(['成功','成功']);
  await expect(page.locator('#page-history .ct-badge-err')).toHaveCount(0);
  expect((await panel.request('/api/history')).data).toHaveLength(2);
 }finally{await panel.close();}
});

test('compact log rows retain time, module, level and message labels at 390px',async({page})=>{
 const panel=await startPanel();try{
  expect((await panel.request('/api/schema-workspace/gen-template',{table:'MissingCompact'})).status).toBe(404);
  await page.setViewportSize({width:390,height:844});
  await page.goto(panel.url);
  await page.locator('#ct-hamb').click();
  await page.locator('.ct-sitem[data-module="logs"]').click();
  const row=page.locator('#page-logs tr',{hasText:'MissingCompact'});
  await expect(row).toBeVisible();
  for(const label of ['时间','模块','级别','信息'])await expect(row.locator(`[data-label="${label}"]`)).toHaveCount(1);
 }finally{await panel.close();}
});

test('translation table picker selects another i18n Table by click without keyboard highlight',async({page})=>{
 const panel=await startPanel();try{
  await writeFile(join(panel.root,'config/schemas/Quest.yaml'),
   'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: Name\n    type: string\n    i18n: true\n');
  await page.goto(panel.url);
  await page.locator('.ct-sitem[data-module="i18n"]').click();
  await page.locator('#i18n-pick').click();
  await expect(page.locator('.ct-dialog-mask.open .ct-picker-row.highlight')).toHaveCount(0);
  await page.locator('.ct-dialog-mask.open .ct-picker-row',{hasText:'Quest'}).click();
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
  await expect(page.locator('.ct-current-table')).toHaveText('Quest');
 }finally{await panel.close();}
});

test('translation source and target columns align with action buttons',async({page})=>{
 const panel=await startPanel();try{
  await seedI18n(panel);await openI18n(page,panel);
  const m=await page.evaluate(()=>{
   const th=[...document.querySelectorAll('#page-i18n .ct-data thead th')];
   const opsTh=th.at(-1).getBoundingClientRect();
   const opsTd=document.querySelector('#page-i18n .ct-row-ops').getBoundingClientRect();
   const src=th[2].getBoundingClientRect();const trans=th[3].getBoundingClientRect();
   const button=document.querySelector('#page-i18n .ct-row-ops button').getBoundingClientRect();
   return {offset:Math.abs(Math.round(opsTh.left)-Math.round(opsTd.left)),textWidthDelta:Math.abs(Math.round(src.width)-Math.round(trans.width)),buttonWidth:button.width};
  });
  expect(m.offset).toBeLessThanOrEqual(1);
  expect(m.textWidthDelta).toBeLessThanOrEqual(2);
  expect(m.buttonWidth).toBeGreaterThanOrEqual(90);
 }finally{await panel.close();}
});

test('390px translation table scrolls horizontally while preserving full text column widths',async({page})=>{
 const panel=await startPanel();try{
  await seedI18n(panel);await page.setViewportSize({width:390,height:844});await openI18n(page,panel);
  const m=await page.evaluate(()=>{
   const wrap=document.querySelector('#page-i18n .ct-i18n-table');
   const table=wrap.querySelector('table');const th=table.querySelectorAll('thead th');
   return {tableWidth:table.getBoundingClientRect().width,sourceWidth:th[2].getBoundingClientRect().width,translationWidth:th[3].getBoundingClientRect().width,horizontalOverflow:wrap.scrollWidth>wrap.clientWidth,pageOverflow:document.documentElement.scrollWidth>innerWidth+1};
  });
  expect(m.tableWidth).toBeGreaterThanOrEqual(916);
  expect(m.sourceWidth).toBeGreaterThanOrEqual(240);
  expect(m.translationWidth).toBeGreaterThanOrEqual(240);
  expect(m.horizontalOverflow).toBe(true);
  expect(m.pageOverflow).toBe(false);
 }finally{await panel.close();}
});

test('520px translation header keeps title and wrapped actions vertically centered',async({page})=>{
 const panel=await startPanel();try{
  await page.setViewportSize({width:520,height:460});
  await page.goto(panel.url+'#/i18n');
  await expect(page.locator('#page-i18n .ct-module-head')).toBeVisible();
  const m=await page.evaluate(()=>{
   const head=document.querySelector('#page-i18n .ct-module-head');
   const group=head.querySelector('.ct-module-actions');group.style.width='180px';
   const title=head.querySelector('.ct-panel-title').getBoundingClientRect();
   const actions=group.getBoundingClientRect();
   const buttons=[...group.querySelectorAll(':scope > .ct-btn')];
   return {centerDelta:Math.abs(Math.round(title.top+title.height/2)-Math.round(actions.top+actions.height/2)),actionRows:new Set(buttons.map(button=>Math.round(button.getBoundingClientRect().top))).size};
  });
  expect(m.centerDelta).toBeLessThanOrEqual(2);
  expect(m.actionRows).toBeGreaterThanOrEqual(2);
 }finally{await panel.close();}
});

test('translation column visibility persists across rerender and menu closes on outside click or Escape',async({page})=>{
 const panel=await startPanel();try{
  await seedI18n(panel);await openI18n(page,panel);
  await page.locator('#i18n-colvis-btn').click();
  await expect(page.locator('.ct-col-menu')).toBeVisible();
  await page.locator('.ct-col-menu input[data-col="trans"]').click();
  await expect(page.locator('table.ct-col-rules thead th').nth(3)).toBeHidden();
  await page.locator('[data-filter="missing"]').click();
  await expect(page.locator('table.ct-col-rules thead th').nth(3)).toBeHidden();
  await page.locator('[data-filter="all"]').click();
  await page.locator('#i18n-colvis-btn').click();
  await page.locator('.ct-current-table').click();
  await expect(page.locator('.ct-col-menu')).toBeHidden();
  await page.locator('#i18n-colvis-btn').click();
  await expect(page.locator('.ct-col-menu')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.ct-col-menu')).toBeHidden();
 }finally{await panel.close();}
});

test('long translation source can expand and collapse its tail',async({page})=>{
 const panel=await startPanel();try{
  await seedI18n(panel);await openI18n(page,panel);
  const tail=page.locator('.ct-src-more').first();
  await expect(tail).toContainText('展开');
  await tail.click();await expect(tail).toContainText('收起');
  await tail.click();await expect(tail).toContainText('展开');
 }finally{await panel.close();}
});

test('translation blur saves changed inline drafts but leaves untouched entries unconfirmed',async({page})=>{
 const panel=await startPanel();try{
  await seedI18n(panel);
  let saves=0;
  page.on('request',request=>{if(request.url().endsWith('/api/i18n/entry')&&request.method()==='POST')saves++;});
  await openI18n(page,panel);
  await page.locator('.trans-preview').first().click();
  await page.locator('[data-filter="all"]').click();
  expect(saves).toBe(0);
  await page.locator('.trans-preview').first().click();
  await page.locator('textarea.is-area').fill('失焦保存译文');
  await page.locator('[data-filter="all"]').click();
  await expect.poll(()=>saves).toBe(1);
  await expect(page.locator('#page-i18n')).toContainText('失焦保存译文');
 }finally{await panel.close();}
});

test('reactivating translation after a viewport change recomputes sticky ID width',async({page})=>{
 const panel=await startPanel();try{
  await seedI18n(panel);await openI18n(page,panel);
  const table=page.locator('table.ct-col-rules');
  await page.locator('.ct-sitem[data-module="logs"]').click();
  await table.evaluate(el=>el.style.removeProperty('--ct-i18n-id-w'));
  await page.setViewportSize({width:1200,height:760});
  await page.locator('.ct-sitem[data-module="i18n"]').click();
  await expect.poll(()=>table.evaluate(el=>parseFloat(el.style.getPropertyValue('--ct-i18n-id-w')))).toBeGreaterThan(0);
 }finally{await panel.close();}
});
