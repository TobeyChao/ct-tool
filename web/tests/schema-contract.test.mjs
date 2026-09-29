import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdir,stat,readdir,appendFile} from 'node:fs/promises';
import {join,dirname} from 'node:path';
import {startPanel} from './panel-helper.mjs';

const command=(value='新的注释')=>[{type:'set_property',payload:{owner:'table:Item',name:'Name',property:'comment',value}}];
async function candidate(p,commands,revision){
 const body={schemaRevision:revision,commands};const result=await p.request('/api/schema-workspace/candidate',body);
 assert.equal(result.status,200,JSON.stringify(result));return {...body,candidateHash:result.data.candidateHash};
}
async function bytes(path){return readFile(path).catch(error=>error.code==='ENOENT'?null:Promise.reject(error));}

test('schema save publishes only changed YAML and a new baseline',async()=>{
 const p=await startPanel();try{
  const item=join(p.root,'config/schemas/Item.yaml');const quest=join(p.root,'config/schemas/Quest.yaml');
  await writeFile(quest,'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n');
  const before={quest:await bytes(quest),config:await bytes(join(p.root,'config/global.yaml'))};
  const original=(await p.request('/api/schema-workspace')).data;
  const body=await candidate(p,command(),original.schemaRevision);
  const result=await p.request('/api/schema-workspace/save',body);
  assert.equal(result.status,200,JSON.stringify(result));
  assert.equal(result.data.isNoOp,false);assert.equal(result.data.written.length,1);
  assert.equal(result.data.written[0].split(/[\\/]/).at(-1),'Item.yaml');
  assert.deepEqual(result.data.deleted,[]);assert.notEqual(result.data.schemaRevision,original.schemaRevision);
  assert.equal(result.data.netDiff.isNoOp,true);
  assert.ok(result.data.resources.some(r=>r.resourceId==='table:Item'));
  assert.match(await readFile(item,'utf8'),/新的注释/);
  assert.deepEqual(await bytes(quest),before.quest);assert.deepEqual(await bytes(join(p.root,'config/global.yaml')),before.config);
  for(const area of ['excel','i18n','output'])assert.equal((await readdir(join(p.root,area)).catch(e=>e.code==='ENOENT'?[]:Promise.reject(e))).length,0);
 }finally{await p.close();}
});

test('no-op save preserves bytes and nanosecond mtime without a journal',async()=>{
 const p=await startPanel();try{
  const path=join(p.root,'config/schemas/Item.yaml');const before=await bytes(path);const mtime=(await stat(path,{bigint:true})).mtimeNs;
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const result=await p.request('/api/schema-workspace/save',await candidate(p,[],revision));
  assert.equal(result.status,200,JSON.stringify(result));assert.equal(result.data.isNoOp,true);
  assert.deepEqual(result.data.written,[]);assert.deepEqual(result.data.deleted,[]);
  assert.deepEqual(await bytes(path),before);assert.equal((await stat(path,{bigint:true})).mtimeNs,mtime);
  assert.equal(await bytes(join(p.root,'.ct/export-publication.json')),null);
 }finally{await p.close();}
});

test('save rejects stale revision, preserves external YAML and succeeds after fresh review',async()=>{
 const p=await startPanel();try{
  const quest=join(p.root,'config/schemas/Quest.yaml');await writeFile(quest,'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n');
  const item=join(p.root,'config/schemas/Item.yaml');const untouched=await bytes(item);
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const body=await candidate(p,command(),revision);
  await writeFile(quest,(await readFile(quest,'utf8'))+'\n# external edit\n');
  const conflict=await p.request('/api/schema-workspace/save',body);
  assert.equal(conflict.status,409);assert.equal(conflict.conflict.kind,'schema-revision');
  assert.ok(conflict.conflict.schemaRevision.members);assert.deepEqual(await bytes(item),untouched);
  const fresh=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const saved=await p.request('/api/schema-workspace/save',{...body,schemaRevision:fresh});
  assert.equal(saved.status,200,JSON.stringify(saved));assert.equal(saved.data.isNoOp,false);
  assert.match(await readFile(quest,'utf8'),/# external edit/);
 }finally{await p.close();}
});

test('save requires both guards and locates malformed command histories',async()=>{
 const p=await startPanel();try{
  const item=join(p.root,'config/schemas/Item.yaml');const before=await bytes(item);
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const body=await candidate(p,command(),revision);
  for(const guards of [{},{schemaRevision:revision},{candidateHash:body.candidateHash}]){
   const r=await p.request('/api/schema-workspace/save',{commands:body.commands,...guards});assert.equal(r.status,400,JSON.stringify(r));
  }
  for(const [commands,location] of [['invalid','commands'],[[42],'commands[0]'],[[{}],'commands[0]']]){
   const r=await p.request('/api/schema-workspace/save',{schemaRevision:revision,candidateHash:body.candidateHash,commands});
   assert.equal(r.status,400,JSON.stringify(r));assert.equal(r.issues[0].location,location);
  }
  assert.deepEqual(await bytes(item),before);
 }finally{await p.close();}
});

test('schema save never needs to read a malformed workbook',async()=>{
 const p=await startPanel();try{
  const excel=join(p.root,'excel/Item.xlsx');await mkdir(join(p.root,'excel'),{recursive:true});await writeFile(excel,'definitely not a workbook');
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const result=await p.request('/api/schema-workspace/save',await candidate(p,command('无 Excel 也能保存'),revision));
  assert.equal(result.status,200,JSON.stringify(result));assert.match(await readFile(join(p.root,'config/schemas/Item.yaml'),'utf8'),/无 Excel 也能保存/);
  assert.equal(await readFile(excel,'utf8'),'definitely not a workbook');
 }finally{await p.close();}
});

test('structurally invalid draft has issues and cannot write YAML',async()=>{
 const p=await startPanel();try{
  const path=join(p.root,'config/schemas/Item.yaml'),before=await bytes(path);
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const commands=[{type:'set_type',payload:{owner:'table:Item',name:'Id',type_text:'Missing'}}];
  const c=await candidate(p,commands,revision);assert.ok(c.candidateHash);
  const validate=await p.request('/api/schema-workspace/validate',{schemaRevision:revision,commands});
  assert.equal(validate.status,200);assert.equal(validate.data.valid,false);assert.ok(validate.data.issues.length);
  const save=await p.request('/api/schema-workspace/save',c);assert.equal(save.status,400,JSON.stringify(save));assert.ok(save.issues.length);
  assert.deepEqual(await bytes(path),before);
 }finally{await p.close();}
});

test('workspace status separates missing, changed and drifted in custom directories',async()=>{
 const p=await startPanel();try{
  await writeFile(join(p.root,'config/global.yaml'),'primary_lang: zh\nsecondary_langs: [en]\nschemas_dir: data/custom-schemas\nexcel_dir: data/books\ncache_dir: data/cache\n');
  await mkdir(join(p.root,'data/custom-schemas'),{recursive:true});
  for(const table of ['Item','Quest','Player'])await writeFile(join(p.root,'data/custom-schemas',table+'.yaml'),`table: ${table}\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n`);
  const empty=await p.request('/api/workspace');assert.equal(empty.status,200,JSON.stringify(empty));
  assert.deepEqual(empty.data.status.missing,['Item','Player','Quest']);assert.deepEqual(empty.data.config.deploy.targets,[]);
  for(const table of ['Quest','Player'])assert.equal((await p.request('/api/schema-workspace/gen-template',{table})).status,200);
  const generated=await p.request('/api/workspace');assert.deepEqual(generated.data.status.changed,[]);
  const ledger=await bytes(join(p.root,'data/cache/state.json'));assert.ok(ledger);
  // ZIP readers accept trailing bytes: this changes the workbook hash while
  // preserving its decoded columns, so only the data-change flag moves.
  await appendFile(join(p.root,'data/books/Player.xlsx'),Buffer.from([0]));
  await writeFile(join(p.root,'data/custom-schemas/Quest.yaml'),(await readFile(join(p.root,'data/custom-schemas/Quest.yaml'),'utf8')+'  - name: Title\n    type: string\n'));
  const state=await p.request('/api/workspace');assert.equal(state.status,200,JSON.stringify(state));
  assert.deepEqual(state.data.status.missing,['Item']);
  assert.deepEqual(state.data.status.changed,['Player']);
  assert.deepEqual(state.data.status.drifted,['Quest']);
  assert.deepEqual(state.data.config.deploy.targets,[]);
  assert.deepEqual(await bytes(join(p.root,'data/cache/state.json')),ledger);
 }finally{await p.close();}
});

test('save recovers a prepared publication before loading business resources',async()=>{
 const p=await startPanel();try{
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const body=await candidate(p,[],revision);
  const journal=join(p.root,'.ct/export-publication.json');await mkdir(dirname(journal),{recursive:true});
  await writeFile(journal,JSON.stringify({format:'export-publication/1',operation_id:'prepared-fixture',root:p.root,phase:'prepared',allowed_dirs:[p.root],entries:[]}));
  const saved=await p.request('/api/schema-workspace/save',body);
  assert.equal(saved.status,200,JSON.stringify(saved));assert.ok(saved.data.recovery);
  assert.equal(await bytes(journal),null);
 }finally{await p.close();}
});

test('validation accepts a field draft and rejects i18n on a Record',async()=>{
 const p=await startPanel();try{
  const revision=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const valid=await p.request('/api/schema-workspace/validate',{schemaRevision:revision,commands:[{type:'add_field',payload:{owner:'table:Item',field:{name:'Price',type:'int32'}}}]});
  assert.equal(valid.status,200,JSON.stringify(valid));assert.equal(valid.data.valid,true);
  await writeFile(join(p.root,'config/types/R.yaml'),'kind: record\nname: R\nfields:\n  - name: N\n    type: string\n');
  const fresh=(await p.request('/api/schema-workspace')).data.schemaRevision;
  const invalid=await p.request('/api/schema-workspace/validate',{schemaRevision:fresh,commands:[{type:'set_property',payload:{owner:'record:R',name:'N',property:'i18n',value:true}}]});
  assert.equal(invalid.status,200,JSON.stringify(invalid));assert.equal(invalid.data.valid,false);
  assert.ok(invalid.data.issues.some(issue=>issue.message.includes('i18n')));
 }finally{await p.close();}
});
