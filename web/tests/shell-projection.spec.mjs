import {test,expect} from '@playwright/test';
import {readFile,stat} from 'node:fs/promises';
import {resolve} from 'node:path';
import {startPanel} from './panel-helper.mjs';

async function openSchema(page,panel){
 await page.goto(panel.url);
 if((await page.evaluate(()=>innerWidth))<740)await page.locator('#ct-hamb').click();
 await page.locator('.ct-sitem[data-module="schema"]').click();
 await expect(page.locator('.ct-resource-row[data-name="Item"]')).toHaveCount(1);
}
async function width(locator){return locator.evaluate(el=>el.getBoundingClientRect().width);}
async function noPageOverflow(page){return page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);}

test('projection switches at 900px and 740px without page-level overflow',async({page})=>{
 const panel=await startPanel();try{
  await page.setViewportSize({width:1600,height:900});await page.goto(panel.url);
  await expect(page.locator('#app')).toHaveAttribute('data-projection','docked');
  await page.setViewportSize({width:800,height:460});
  await expect(page.locator('#app')).toHaveAttribute('data-projection','pane-drawer');
  expect(await noPageOverflow(page)).toBe(true);
  await page.setViewportSize({width:400,height:844});
  await expect(page.locator('#app')).toHaveAttribute('data-projection','shell-drawer');
  await expect(page.locator('.ct-topbar .ct-ws-name')).toBeVisible();
  await expect(page.locator('.ct-activity-bar')).toHaveCount(0);
 }finally{await panel.close();}
});

test('Schema selection survives module switches and a narrow-to-wide projection round trip',async({page})=>{
 const panel=await startPanel();try{
  await page.setViewportSize({width:1600,height:900});await openSchema(page,panel);
  await page.locator('#resource-toggle').click();
  await page.locator('.ct-resource-row[data-name="Item"]').click();
  await expect(page.locator('#editor-title')).toHaveText('Item');
  await page.locator('.ct-sitem[data-module="logs"]').click();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect(page.locator('.ct-resource-row[data-name="Item"]')).toHaveClass(/active/);
  await page.setViewportSize({width:800,height:460});
  await expect(page.locator('#app')).toHaveAttribute('data-projection','pane-drawer');
  await page.setViewportSize({width:1600,height:900});
  await expect(page.locator('#app')).toHaveAttribute('data-projection','docked');
  await expect(page.locator('.ct-resource-row[data-name="Item"]')).toHaveClass(/active/);
  await expect(page.locator('.ct-workspace-layout')).toHaveAttribute('data-resource-open','false');
 }finally{await panel.close();}
});

test('docked resource and inspector panes start collapsed and toggle between two states',async({page})=>{
 const panel=await startPanel();try{
  await page.setViewportSize({width:1600,height:900});await openSchema(page,panel);
  const side=page.locator('.ct-side');const tab=page.locator('.ct-side-tab');
  await expect(tab).toHaveAttribute('aria-pressed','false');
  await expect(page.locator('#side-inspector')).toHaveAttribute('inert','');
  expect(await width(side)).toBeLessThanOrEqual(1);
  await tab.click();
  await expect(tab).toHaveAttribute('aria-pressed','true');
  await expect.poll(()=>width(side)).toBeGreaterThanOrEqual(280);
  await expect(page.locator('#side-inspector')).not.toHaveAttribute('inert','');
  await tab.click();
  await expect(tab).toHaveAttribute('aria-pressed','false');
  await expect.poll(()=>width(side)).toBeLessThanOrEqual(1);
  const pane=page.locator('.ct-resource-pane');const toggle=page.locator('#resource-toggle');
  expect(await width(pane)).toBeLessThanOrEqual(1);
  await toggle.click();await expect(toggle).toHaveAttribute('aria-expanded','true');
  await expect.poll(()=>width(pane)).toBeGreaterThanOrEqual(200);
  await toggle.click();await expect(toggle).toHaveAttribute('aria-expanded','false');
  await expect.poll(()=>width(pane)).toBeLessThanOrEqual(1);
 }finally{await panel.close();}
});

test('at 800px resource pane acts as an inert offscreen drawer and selection or Escape closes it',async({page})=>{
 const panel=await startPanel();try{
  await page.setViewportSize({width:800,height:700});await openSchema(page,panel);
  const pane=page.locator('.ct-resource-pane');
  const closed=()=>pane.evaluate(el=>{const r=el.getBoundingClientRect();return r.x+r.width<=1;});
  await expect.poll(closed).toBe(true);
  await expect(pane).toHaveAttribute('inert','');
  await page.locator('#resource-toggle').click();
  await expect.poll(()=>pane.evaluate(el=>el.getBoundingClientRect().x)).toBeGreaterThanOrEqual(0);
  await page.locator('.ct-resource-row[data-name="Item"]').click();
  await expect.poll(closed).toBe(true);
  await page.locator('#resource-toggle').click();
  await page.keyboard.press('Escape');
  await expect.poll(closed).toBe(true);
 }finally{await panel.close();}
});

test('widening an open drawer closes it and removes editor inert state',async({page})=>{
 const panel=await startPanel();try{
  await page.setViewportSize({width:800,height:700});await openSchema(page,panel);
  await page.locator('#resource-toggle').click();
  await expect(page.locator('.ct-editor')).toHaveAttribute('inert','');
  await page.setViewportSize({width:1000,height:700});
  await expect(page.locator('#resource-toggle')).toHaveAttribute('aria-expanded','false');
  await expect(page.locator('.ct-editor')).not.toHaveAttribute('inert','');
  await expect.poll(()=>width(page.locator('.ct-resource-pane'))).toBeLessThanOrEqual(1);
 }finally{await panel.close();}
});

test('hidden module pages remain inert',async({page})=>{
 const panel=await startPanel();try{
  await openSchema(page,panel);
  await page.locator('.ct-sitem[data-module="export"]').click();
  await expect(page.locator('#page-schema')).toHaveAttribute('inert','');
 }finally{await panel.close();}
});

test('about and help dialogs show product and shortcut details and close on Escape',async({page})=>{
 const panel=await startPanel();try{
  await page.goto(panel.url);
  await page.locator('#ct-about').click();
  await expect(page.locator('.ct-dialog-mask.open')).toContainText('配表工具');
  await page.keyboard.press('Escape');
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
  await page.locator('#ct-help').click();
  await expect(page.locator('.ct-dialog-mask.open .ct-keys')).toBeVisible();
  await expect(page.locator('.ct-dialog-mask.open')).toContainText('⌘P');
  await expect(page.locator('.ct-dialog-mask.open')).toContainText('⌘Z');
  await page.keyboard.press('Escape');
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
 }finally{await panel.close();}
});

test('reduced motion eliminates workspace pane transitions',async({page})=>{
 const panel=await startPanel();try{
  await page.emulateMedia({reducedMotion:'reduce'});await openSchema(page,panel);
  await expect(page.locator('.ct-workspace-layout')).toHaveCSS('transition-duration','0s');
 }finally{await panel.close();}
});

test('nested dialogs close top-first, retain app inert and restore each opener focus',async({page})=>{
 const panel=await startPanel();try{
  await page.goto(panel.url);
  await page.locator('#ct-help').focus();
  await page.evaluate(async()=>{
   const {openDialog}=await import('/static/js/core/dialog.js');
   const parent=openDialog({title:'Parent',body:'<button id="nested-open">Open child</button>'});
   parent.el.querySelector('#nested-open').addEventListener('click',()=>openDialog({title:'Child',body:'<button>Child action</button>'}));
  });
  await page.locator('#nested-open').click();
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(2);
  const labels=await page.locator('.ct-dialog-mask.open .ct-dialog').evaluateAll(dialogs=>dialogs.map(dialog=>dialog.getAttribute('aria-labelledby')));
  expect(new Set(labels).size).toBe(2);
  await expect(page.locator('#app')).toHaveAttribute('inert','');
  await page.keyboard.press('Escape');
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(1);
  await expect(page.locator('#nested-open')).toBeFocused();
  await expect(page.locator('#app')).toHaveAttribute('inert','');
  await page.keyboard.press('Escape');
  await expect(page.locator('.ct-dialog-mask.open')).toHaveCount(0);
  await expect(page.locator('#app')).not.toHaveAttribute('inert','');
  await expect(page.locator('#ct-help')).toBeFocused();
 }finally{await panel.close();}
});

test('physical viewport and browser zoom matrix preserves projection and has no horizontal overflow',async({browser})=>{
 test.setTimeout(90000);
 const panel=await startPanel();
 const matrix=JSON.parse(await readFile(resolve(import.meta.dirname,'fixtures/schema_workbench_matrix.json'),'utf8'));
 try{
  for(const viewport of matrix.viewports){
   for(const percent of matrix.zoom_percentages){
    const zoom=percent/100;
    const css={width:Math.round(viewport.width/zoom),height:Math.round(viewport.height/zoom)};
    const expected=css.width>=900?'docked':css.width>=740?'pane-drawer':'shell-drawer';
    const context=await browser.newContext({viewport:css,deviceScaleFactor:zoom,locale:'zh-CN',reducedMotion:'reduce'});
    try{
     const page=await context.newPage();
     const consoleErrors=[];
     page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});
     await page.goto(panel.url+'/#/export');
     await expect(page.locator('#app')).toHaveAttribute('data-projection',expected);
     expect(await page.locator('.ct-brand-mark',{hasText:'ct'}).count()).toBeGreaterThanOrEqual(1);
     await expect(page.locator('.ct-sitem')).toHaveCount(5);
     if(css.width<740){
      await expect(page.locator('.ct-topbar .ct-ws-name')).toBeVisible();
     }else{
      await expect(page.locator('.ct-topbar')).toBeHidden();
     }
     await expect(page.getByText('新增表',{exact:true})).toHaveCount(0);
     expect(await noPageOverflow(page),`${viewport.width}x${viewport.height} z${percent}`).toBe(true);
     const suffix=`${viewport.width}x${viewport.height}-z${percent}-${expected}.png`;
     const exportScreenshot=resolve(import.meta.dirname,`../test-results/export-${suffix}`);
     await page.screenshot({path:exportScreenshot,animations:'disabled'});
     expect((await stat(exportScreenshot)).size).toBeGreaterThan(1000);
     if(css.width<740)await page.locator('#ct-hamb').click();
     await page.locator('.ct-sitem[data-module="schema"]').click();
     await page.locator('#resource-toggle').click();
     await page.locator('.ct-resource-row[data-name="Item"]').click();
     if(expected==='docked'){
      const sidebar=await width(page.locator('.ct-sidebar'));
      expect(sidebar).toBeGreaterThanOrEqual(200);expect(sidebar).toBeLessThanOrEqual(300);
      await expect(page.locator('.ct-right-activity')).toBeVisible();
     }
     expect(await noPageOverflow(page),`Schema ${viewport.width}x${viewport.height} z${percent}`).toBe(true);
     const screenshot=resolve(import.meta.dirname,`../test-results/schema-${suffix}`);
     await page.screenshot({path:screenshot,animations:'disabled'});
     expect((await stat(screenshot)).size).toBeGreaterThan(1000);
     expect(consoleErrors,`${viewport.width}x${viewport.height} z${percent}`).toEqual([]);
    }finally{await context.close();}
   }
  }
 }finally{await panel.close();}
});
