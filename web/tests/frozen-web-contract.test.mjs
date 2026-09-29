import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir,access} from 'node:fs/promises';
import {realpathSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {join,dirname,resolve} from 'node:path';
import {startPanel} from './panel-helper.mjs';

const baseline=JSON.parse(await readFile(new URL('../../native/docs/baseline/web-http-python.json',import.meta.url)));
function hash(bytes){return createHash('sha256').update(bytes).digest('hex');}

test('frozen Python Web inputs and success/error contracts run against the native panel',async()=>{
 assert.equal(baseline.format,'python-web-http-fixtures/1');
 assert.equal(Object.keys(baseline.data.captures).length,12);
 for(const [source,digest] of Object.entries(baseline.sourceSha256)){
  const path=resolve(import.meta.dirname,'../..',source);
  try{await access(path)}catch{continue;} // ct/ is optional after retirement.
  assert.equal(hash(await readFile(path)),digest,source+' changed after baseline freeze');
 }
 const p=await startPanel();try{
  for(const [relative,file] of Object.entries(baseline.data.filesBefore)){
   const target=join(p.root,relative);await mkdir(dirname(target),{recursive:true});await writeFile(target,file.text);
   assert.equal(hash(await readFile(target)),file.sha256);
  }
  const canonicalRoot=realpathSync(p.root);
  const normalized=value=>JSON.parse(JSON.stringify(value).replaceAll(canonicalRoot,'${ROOT}').replaceAll(p.root,'${ROOT}'));
  for(const [name,contract] of Object.entries(baseline.data.captures)){
   const request=contract.request;
   const actual=await p.request(request.path,request.method==='POST'?request.body:undefined);
   assert.equal(actual.status,contract.status,name+': '+JSON.stringify(actual));
   const projected=normalized(actual);
   const expected={status:contract.status,...contract.response};
   switch(name){
    case 'candidate_valid':
     // The native response echoes the edit generation so stale browser
     // responses can be ignored; the old response did not include it.
     delete projected.data.draftGeneration;
     break;
    case 'save_valid':
     delete projected.data.changed; // additive empty list in the native DTO.
     break;
    case 'validate_invalid':
     assert.equal(projected.data.valid,false);
     assert.equal(projected.data.issues[0].location,expected.data.issues[0].location);
     assert.match(projected.data.issues[0].message,/frobnicate/);
     continue;
    case 'save_missing_guard':
     assert.match(projected.error,/candidateHash/);continue;
    case 'save_forged_hash':
     assert.equal(projected.conflict.kind,expected.conflict.kind);continue;
    case 'logs_empty':
     assert.deepEqual(projected.data.filter(row=>row.module!=='系统'),expected.data);
     continue;
   }
   assert.deepEqual(projected,expected,name);
  }
  for(const [relative,file] of Object.entries(baseline.data.filesAfterSave)){
   const bytes=await readFile(join(p.root,relative));
   assert.equal(hash(bytes),file.sha256,relative);
   assert.equal(bytes.length,file.bytes,relative);
  }
 }finally{await p.close();}
});

test('frozen legacy history entry imports and normalizes its result code',async()=>{
 const p=await startPanel();try{
  const history=baseline.data.legacyHistory;
  const source=join(p.root,history.sourceFile);await mkdir(dirname(source),{recursive:true});
  await writeFile(source,history.sourceText);
  const result=await p.request('/api/history');assert.equal(result.status,200,JSON.stringify(result));
  assert.equal(result.data.length,1);assert.equal(result.data[0].result,history.readResponse[0].result);
  assert.equal(result.data[0].tables,history.readResponse[0].tables);
  assert.equal(await readFile(source,'utf8'),history.sourceText);
 }finally{await p.close();}
});
