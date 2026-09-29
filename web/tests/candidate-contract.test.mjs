import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdir, readFile, stat, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

const edit=(value)=>({type:'set_property',payload:{owner:'table:Item',name:'Name',property:'comment',value}});
const call=(panel,path,revision,commands,cursor,draftGeneration)=>panel.request(path,{schemaRevision:revision,commands,cursor,draftGeneration});

test('candidate and validation use only the requested command prefix and echo its generation',async()=>{
 const p=await startPanel();try{
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const history=[edit('前缀'),edit('重做分支')];
  const prefix=await call(p,'/api/schema-workspace/candidate',revision,history,1,17);
  const direct=await call(p,'/api/schema-workspace/candidate',revision,[history[0]],1,18);
  assert.equal(prefix.status,200,JSON.stringify(prefix));assert.equal(direct.status,200,JSON.stringify(direct));
  assert.equal(prefix.data.draftGeneration,17);
  assert.equal(prefix.data.schemaRevision.revision,revision);
  assert.deepEqual(prefix.data.resources,direct.data.resources);
  assert.deepEqual(prefix.data.netDiff,direct.data.netDiff);
  assert.equal(prefix.data.candidateHash,direct.data.candidateHash);
  assert.equal(prefix.data.netDiff.changedResources,1);
  assert.equal(prefix.data.resources.find(r=>r.resourceId==='table:Item').fields.find(f=>f.name==='Name').comment,'前缀');
  const validated=await call(p,'/api/schema-workspace/validate',revision,history,1,19);
  assert.equal(validated.status,200,JSON.stringify(validated));
  assert.equal(validated.data.valid,true);assert.deepEqual(validated.data.issues,[]);
  assert.equal(validated.data.draftGeneration,19);
  assert.equal(validated.data.candidateHash,prefix.data.candidateHash);
  assert.deepEqual(validated.data.netDiff,prefix.data.netDiff);
  assert.deepEqual(validated.data.resources,prefix.data.resources);
  const baseline=await call(p,'/api/schema-workspace/candidate',revision,history,0,20);
  const empty=await call(p,'/api/schema-workspace/candidate',revision,[],0,21);
  assert.equal(baseline.status,200);assert.equal(empty.status,200);
  assert.equal(baseline.data.netDiff.isNoOp,true);
  assert.equal(baseline.data.candidateHash,empty.data.candidateHash);
 }finally{await p.close();}
});

test('malformed active command pinpoints its position; inactive redo is not applied',async()=>{
 const p=await startPanel();try{
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const malformed=[edit('有效'),{type:'frobnicate',payload:{}}];
  for(const endpoint of ['candidate','validate']){
   const path='/api/schema-workspace/'+endpoint;
   const good=await call(p,path,revision,malformed,1,4);
   assert.equal(good.status,200,JSON.stringify(good));
   const bad=await call(p,path,revision,malformed,2,5);
   assert.equal(bad.status,endpoint==='candidate'?400:200,JSON.stringify(bad));
   assert.equal((endpoint==='candidate'?bad.issues:bad.data.issues)[0].location,'commands[1]');
   if(endpoint==='validate'){assert.equal(bad.data.valid,false);assert.equal(bad.data.netDiff,null);}
  }
  const malformedResource=[{type:'add_resource',payload:{kind:'record',resource:{kind:'record',name:'Bad',fields:[{name:'N',type:'no_such_type'}]}}}];
  const resource=await call(p,'/api/schema-workspace/candidate',revision,malformedResource,1,6);
  assert.equal(resource.status,400,JSON.stringify(resource));
  assert.match(resource.issues[0].location,/^commands\[0\]\.payload\.resource/);
  for(const [commands,location] of [['bad','commands'],[[null],'commands[0]'],[[{}],'commands[0]']]){
   const response=await call(p,'/api/schema-workspace/candidate',revision,commands,undefined,7);
   assert.equal(response.status,400,JSON.stringify(response));assert.equal(response.issues[0].location,location);
  }
  const cursor=await call(p,'/api/schema-workspace/candidate',revision,[edit('有效')],2,8);
  assert.equal(cursor.status,400);assert.equal(cursor.issues[0].location,'cursor');
 }finally{await p.close();}
});

test('stale baseline rejects the draft and candidate or validation never reads Excel or writes files',async()=>{
 const p=await startPanel();try{
  const yaml=join(p.root,'config/schemas/Item.yaml');
  const excel=join(p.root,'excel/Item.xlsx');
  await mkdir(join(p.root,'excel'),{recursive:true});await writeFile(excel,'invalid workbook');
  const before=await readFile(yaml);const mtime=(await stat(yaml,{bigint:true})).mtimeNs;
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  for(const endpoint of ['candidate','validate']){
   const result=await call(p,'/api/schema-workspace/'+endpoint,revision,[edit('只看结构')],1,22);
   assert.equal(result.status,200,JSON.stringify(result));
   assert.equal(result.data.draftGeneration,22);
  }
  assert.deepEqual(await readFile(yaml),before);assert.equal((await stat(yaml,{bigint:true})).mtimeNs,mtime);
  assert.equal(await readFile(excel,'utf8'),'invalid workbook');
  await writeFile(yaml,Buffer.concat([before,Buffer.from('\n# external edit\n')]));
  for(const endpoint of ['candidate','validate']){
   const stale=await call(p,'/api/schema-workspace/'+endpoint,revision,[edit('不可重基')],1,23);
   assert.equal(stale.status,409,JSON.stringify(stale));
   assert.equal(stale.conflict.kind,'schema-revision');
   assert.notEqual(stale.conflict.schemaRevision.revision,revision);
  }
  assert.equal(await readFile(excel,'utf8'),'invalid workbook');
 }finally{await p.close();}
});
