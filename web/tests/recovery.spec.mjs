import {test,expect} from '@playwright/test';
import {startPanel} from './panel-helper.mjs';
import {readFile,writeFile,mkdir,stat} from 'node:fs/promises';
import {join,dirname,resolve} from 'node:path';

test('recovery banner explicitly restores a Python crash before reloading the workspace',async({page})=>{
 const p=await startPanel();try{
  const fixture=JSON.parse(await readFile(resolve(import.meta.dirname,'../../native/fixtures/journals/python-publication.json'),'utf8'));
  const crash=fixture.cases.find(c=>c.name==='publishing-4');
  for(const [relative,{text}] of Object.entries(crash.before)){
   const target=join(p.root,relative);await mkdir(dirname(target),{recursive:true});await writeFile(target,text);
  }
  const expand=value=>typeof value==='string'?value.replaceAll('${ROOT}',p.root):Array.isArray(value)?value.map(expand):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([key,v])=>[key,expand(v)])):value;
  const journal=join(p.root,'.ct/export-publication.json');await writeFile(journal,JSON.stringify(expand(crash.journal)));
  let recoveries=0;page.on('request',r=>{if(r.url().endsWith('/api/workspace/recover'))recoveries++;});
  await page.goto(p.url);await expect(page.locator('#ct-recovery-notice')).toContainText('未完成');
  await page.screenshot({path:resolve(import.meta.dirname,'../test-results/native-recovery.png'),fullPage:true});
  expect(recoveries).toBe(0);expect(await readFile(join(p.root,'config/global.yaml'),'utf8')).toContain('[invalid');
  await page.getByRole('button',{name:'恢复未完成发布'}).click();
  await expect(page.locator('#ct-recovery-notice')).toContainText('恢复完成');expect(recoveries).toBe(1);
  expect(await readFile(join(p.root,'config/global.yaml'),'utf8')).toBe(crash.after['config/global.yaml'].text);
  await expect(stat(journal)).rejects.toMatchObject({code:'ENOENT'});
  await page.reload();await expect(page.locator('#ct-recovery-notice')).toHaveCount(0);
  await page.locator('.ct-sitem[data-module="schema"]').click();await expect(page.locator('.ct-resource-row[data-name="Item"]')).toHaveCount(1);
  expect(recoveries).toBe(1);
 }finally{await p.close();}
});

test('unknown Apply recovery stays blocked with original materials visible',async({page})=>{
 const p=await startPanel();try{
  await mkdir(join(p.root,'cache'),{recursive:true});const journal=join(p.root,'cache/apply.journal.json');await writeFile(journal,'{"format":"old-unknown"}');
  await page.goto(p.url);await expect(page.locator('#ct-recovery-notice')).toContainText('旧 Apply');
  await page.getByRole('button',{name:'恢复未完成发布'}).click();await expect(page.locator('[data-recovery-result]')).toContainText('保留');
  expect(await readFile(journal,'utf8')).toBe('{"format":"old-unknown"}');
  await page.reload();await expect(page.locator('#ct-recovery-notice')).toContainText('旧 Apply');
 }finally{await p.close();}
});
