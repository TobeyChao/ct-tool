import {test,expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

async function fixture(){
 const panel=await startPanel();
 await writeFile(join(panel.root,'config/schemas/Quest.yaml'),'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n');
 await writeFile(join(panel.root,'config/types/ItemRarity.yaml'),'kind: enum\nname: ItemRarity\nvalues:\n  - name: Common\n  - name: Rare\n');
 return panel;
}
async function openSchema(page,panel){
 await page.goto(panel.url);
 await page.locator('.ct-sitem[data-module="schema"]').click();
 await expect(page.locator('.ct-resource-row[data-name="Item"]')).toHaveCount(1);
}
async function palette(page){
 await page.keyboard.press('Control+p');
 await expect(page.locator('.ct-dlg-palette [data-qo-input]')).toBeFocused();
 return page.locator('.ct-dlg-palette');
}

test('Quick Open filters resources across kinds and selects the matching Enum',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);
  const dialog=await palette(page);
  await dialog.locator('[data-qo-input]').fill('Rarity');
  await expect(dialog.locator('[data-qo="ItemRarity"]')).toHaveCount(1);
  await dialog.locator('[data-qo="ItemRarity"]').click();
  await expect(page.locator('#editor-title')).toHaveText('ItemRarity');
 }finally{await panel.close();}
});

test('an empty Quick Open query starts from the recent resource',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);
  if((await page.locator('.ct-workspace-layout').getAttribute('data-resource-open'))!=='true')await page.locator('#resource-toggle').click();
  await page.locator('.ct-resource-row[data-name="Quest"]').click();
  await expect(page.locator('#editor-title')).toHaveText('Quest');
  const dialog=await palette(page);
  await expect(dialog.locator('[data-qo-list] .ct-resource-row')).toHaveCount(1);
  await expect(dialog.locator('[data-qo-list]')).toContainText('Quest');
 }finally{await panel.close();}
});

test('stale recent-resource names from another workspace fall back to current resources',async({page})=>{
 const panel=await fixture();try{
  await page.goto(panel.url);
  await page.evaluate(()=>localStorage.setItem('ct-recent-resources',JSON.stringify(['RemovedTable'])));
  await page.reload();
  await page.locator('.ct-sitem[data-module="schema"]').click();
  await expect(page.locator('.ct-resource-row[data-name="Item"]')).toHaveCount(1);
  const dialog=await palette(page);
  await expect(dialog.locator('[data-qo-list]')).toContainText('Item');
  await expect(dialog.locator('[data-qo="RemovedTable"]')).toHaveCount(0);
 }finally{await panel.close();}
});

test('first Escape clears Quick Open search; second closes and restores opener focus',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);
  await page.locator('#quick-open-head').focus();
  const dialog=await palette(page);
  await dialog.locator('[data-qo-input]').fill('Rarity');
  await expect(dialog.locator('[data-qo="ItemRarity"]')).toHaveCount(1);
  await page.keyboard.press('Escape');
  await expect(dialog.locator('[data-qo-input]')).toHaveValue('');
  await expect(dialog.locator('[data-qo-list] .ct-resource-row')).not.toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(page.locator('.ct-dlg-palette')).toHaveCount(0);
  await expect(page.locator('#quick-open-head')).toBeFocused();
 }finally{await panel.close();}
});

test('ArrowDown and Enter select the second Quick Open result',async({page})=>{
 const panel=await fixture();try{
  await openSchema(page,panel);
  const dialog=await palette(page);
  await dialog.locator('[data-qo-input]').fill('Item');
  await expect(dialog.locator('[data-qo-list] .ct-resource-row')).toHaveCount(2);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(page.locator('#editor-title')).toHaveText('ItemRarity');
 }finally{await panel.close();}
});
