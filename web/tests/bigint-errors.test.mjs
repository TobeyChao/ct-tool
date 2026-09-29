import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

test('HTTP serializes unsafe integers as exact decimal tags at every depth',async()=>{
 const p=await startPanel();try{
  await mkdir(join(p.root,'cache'),{recursive:true});
  await writeFile(join(p.root,'cache/history.json'),'{"format":"desktop-history/1","entries":[{"time":"2026-09-28T00:00:00Z","scope":"all","result":"success","tables":1,"elapsed":0,"forced":false,"error":"","boundary":{"safe":9007199254740991,"unsafe":9007199254740992,"negative":-9007199254740992,"nested":[18446744073709551615,-9223372036854775808]}}]}');
  const response=await p.request('/api/history');
  assert.equal(response.status,200,JSON.stringify(response));
  const value=response.data[0].boundary;
  assert.equal(value.safe,Number.MAX_SAFE_INTEGER);
  assert.deepEqual(value.unsafe,{'$int':'9007199254740992'});
  assert.deepEqual(value.negative,{'$int':'-9007199254740992'});
  assert.deepEqual(value.nested,[{'$int':'18446744073709551615'},{'$int':'-9223372036854775808'}]);
  assert.equal(JSON.stringify(value).includes('18446744073709551615'),true);
 }finally{await p.close();}
});

test('400, 404, 409 and publication 500 remain structured without changing YAML',async()=>{
 const p=await startPanel();try{
  const item=join(p.root,'config/schemas/Item.yaml'),before=await readFile(item);
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const bad=await p.request('/api/schema-workspace/candidate',{schemaRevision:revision,commands:[{type:'unknown',payload:{}}]});
  assert.equal(bad.status,400,JSON.stringify(bad));
  assert.equal(bad.ok,false);assert.equal(bad.issues[0].location,'commands[0]');
  const missing=await p.request('/api/schema-workspace/gen-template',{table:'Missing'});
  assert.equal(missing.status,404,JSON.stringify(missing));
  assert.equal(missing.ok,false);assert.equal(typeof missing.error,'string');
  const command={type:'set_property',payload:{owner:'table:Item',name:'Name',property:'comment',value:'must-roll-back'}};
  const body={schemaRevision:revision,commands:[command],cursor:1};
  const candidate=await p.request('/api/schema-workspace/candidate',body);
  assert.equal(candidate.status,200,JSON.stringify(candidate));
  const conflict=await p.request('/api/schema-workspace/save',{...body,candidateHash:'0'.repeat(64)});
  assert.equal(conflict.status,409,JSON.stringify(conflict));
  assert.equal(conflict.conflict.kind,'candidate-hash');
  await mkdir(join(p.root,'.ct'),{recursive:true});
  await writeFile(join(p.root,'.ct/staged'),'block publication staging');
  const failed=await p.request('/api/schema-workspace/save',{...body,candidateHash:candidate.data.candidateHash});
  assert.equal(failed.status,500,JSON.stringify(failed));
  assert.equal(failed.ok,false);assert.equal(typeof failed.error,'string');
  assert.match(failed.error,/发布失败/);
  assert.deepEqual(await readFile(item),before);
  assert.equal((await p.request('/api/schema-workspace')).data.schemaRevision,revision);
 }finally{await p.close();}
});
