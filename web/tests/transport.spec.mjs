import {test,expect} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

test('browser API and history view preserve a tagged integer and structured conflict',async({page})=>{
 const p=await startPanel();try{
  await mkdir(join(p.root,'cache'),{recursive:true});
  await writeFile(join(p.root,'cache/history.json'),'{"format":"desktop-history/1","entries":[{"time":"2026-09-28T00:00:00Z","scope":"all","result":"success","tables":9007199254740993,"elapsed":0,"forced":false,"error":""}]}');
  await page.goto(p.url);
  const result=await page.evaluate(async()=>{
   const {api}=await import('/static/js/core/api.js');
   const history=await api('/api/history');
   const snapshot=await api('/api/schema-workspace');
   const body=JSON.stringify({schemaRevision:snapshot.schemaRevision,candidateHash:'0'.repeat(64),commands:[]});
   let conflict;
   try{await api('/api/schema-workspace/save',{method:'POST',body});}
   catch(error){conflict={status:error.status,kind:error.payload?.conflict?.kind};}
   return {tables:history[0].tables,conflict};
  });
  expect(result.tables).toEqual({'$int':'9007199254740993'});
  expect(result.conflict).toEqual({status:409,kind:'candidate-hash'});
  await page.locator('.ct-sitem[data-module="history"]').click();
  await expect(page.locator('#page-history tbody tr td').nth(3)).toHaveText('9007199254740993');
 }finally{await p.close();}
});
