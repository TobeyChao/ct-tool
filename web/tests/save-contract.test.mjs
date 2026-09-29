import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdir, readFile, stat, writeFile} from 'node:fs/promises';
import {join, basename, dirname} from 'node:path';
import {startPanel} from './panel-helper.mjs';

async function savedState(path){
 try{return {bytes:await readFile(path),mtime:(await stat(path,{bigint:true})).mtimeNs};}
 catch(error){if(error.code==='ENOENT')return null;throw error;}
}
async function draft(panel,commands,cursor=commands.length){
 const original=(await panel.request('/api/schema-workspace')).data;
 const body={schemaRevision:original.schemaRevision,commands,cursor};
 const candidate=await panel.request('/api/schema-workspace/candidate',body);
 assert.equal(candidate.status,200,JSON.stringify(candidate));
 return {original,body:{...body,candidateHash:candidate.data.candidateHash},candidate:candidate.data};
}

test('rename save updates references and reports an exact YAML-only receipt and fresh snapshot',async()=>{
 const p=await startPanel();try{
  const root=p.root;
  const item=join(root,'config/schemas/Item.yaml'),quest=join(root,'config/schemas/Quest.yaml');
  const rarity=join(root,'config/types/Rarity.yaml'),oldExcel=join(root,'excel/Item.xlsx');
  const translation=join(root,'i18n/en/Item.json'),ledger=join(root,'cache/state.json');
  await writeFile(quest,'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: ItemId\n    type: int32\n    ref: Item.Id\n');
  await mkdir(join(root,'config/types'),{recursive:true});
  await writeFile(rarity,'kind: enum\nname: Rarity\nvalues:\n  - name: Common\n');
  for(const path of [oldExcel,translation,ledger]){
   await mkdir(dirname(path),{recursive:true});await writeFile(path,`leave ${basename(path)} untouched`);
  }
  const protectedFiles=[rarity,oldExcel,translation,ledger];
  const before=await Promise.all(protectedFiles.map(savedState));
  const {original,body,candidate}=await draft(p,[{type:'rename_resource',payload:{old:'Item',new:'Goods'}}]);
  assert.equal(candidate.issues.length,0,JSON.stringify(candidate.issues));
  assert.equal(candidate.netDiff.changedResources,2);
  assert.equal(candidate.resources.find(r=>r.resourceId==='table:Quest').fields.find(f=>f.name==='ItemId').ref,'Goods.Id');
  const saved=await p.request('/api/schema-workspace/save',body);
  assert.equal(saved.status,200,JSON.stringify(saved));
  const result=saved.data;
  assert.equal(result.isNoOp,false);assert.equal(result.changedResources,2);
  assert.deepEqual(result.written.map(path=>basename(path)).sort(),['Goods.yaml','Quest.yaml']);
  assert.deepEqual(result.deleted.map(path=>basename(path)),['Item.yaml']);
  assert.deepEqual(result.unchanged.map(path=>basename(path)),['Rarity.yaml']);
  assert.deepEqual(result.notes,[]);assert.equal(result.netDiff.isNoOp,true);
  assert.equal(result.schemaRevision,result.revision);
  assert.notEqual(result.schemaRevision,original.schemaRevision);
  assert.equal(await savedState(item),null);
  assert.match(await readFile(join(root,'config/schemas/Goods.yaml'),'utf8'),/table: Goods/);
  assert.match(await readFile(quest,'utf8'),/ref: Goods\.Id/);
  const fresh=(await p.request('/api/schema-workspace')).data;
  assert.equal(fresh.schemaRevision,result.schemaRevision);
  assert.deepEqual(result.resources,fresh.resources);
  assert.deepEqual(result.reverseRefs,fresh.reverseRefs);
  for(let i=0;i<protectedFiles.length;i++)assert.deepEqual(await savedState(protectedFiles[i]),before[i],protectedFiles[i]);
  assert.equal(await savedState(join(root,'output/json/Goods_zh.json')),null);
 }finally{await p.close();}
});

test('new Table save warns about its existing workbook without reading or changing it',async()=>{
 const p=await startPanel();try{
  const workbook=join(p.root,'excel/Quest.xlsx');await mkdir(join(p.root,'excel'),{recursive:true});
  await writeFile(workbook,'not a valid workbook');const before=await savedState(workbook);
  const {body}=await draft(p,[{type:'add_resource',payload:{kind:'table',resource:{table:'Quest',primary:'Id',fields:[{name:'Id',type:'int32'}]}}}]);
  const response=await p.request('/api/schema-workspace/save',body);
  assert.equal(response.status,200,JSON.stringify(response));
  assert.deepEqual(response.data.written.map(path=>basename(path)),['Quest.yaml']);
  assert.ok(response.data.notes.some(note=>note.includes('Quest')&&note.includes('Quest.xlsx')));
  assert.deepEqual(await savedState(workbook),before);
  assert.equal(await savedState(join(p.root,'excel/layout_manifests/quest.json')),null);
 }finally{await p.close();}
});

test('net-zero command history does not touch YAML or create a publication journal',async()=>{
 const p=await startPanel();try{
  const item=join(p.root,'config/schemas/Item.yaml'),before=await savedState(item);
  const commands=[
   {type:'add_resource',payload:{kind:'record',resource:{kind:'record',name:'Temporary',fields:[{name:'N',type:'int32'}]}}},
   {type:'delete_resource',payload:{name:'record:Temporary'}},
  ];
  const {body,candidate}=await draft(p,commands);
  assert.equal(candidate.netDiff.isNoOp,true);
  const saved=await p.request('/api/schema-workspace/save',body);
  assert.equal(saved.status,200,JSON.stringify(saved));
  assert.equal(saved.data.isNoOp,true);
  assert.deepEqual(saved.data.written,[]);assert.deepEqual(saved.data.deleted,[]);
  assert.deepEqual(await savedState(item),before);
  assert.equal(await savedState(join(p.root,'config/types/Temporary.yaml')),null);
  assert.equal(await savedState(join(p.root,'.ct/export-publication.json')),null);
 }finally{await p.close();}
});

test('target path conflict rejects the entire save and preserves the draft baseline',async()=>{
 const p=await startPanel();try{
  const item=join(p.root,'config/schemas/Item.yaml');
  const blocker=join(p.root,'config/types/Bonus.yaml');
  await mkdir(blocker,{recursive:true});
  const before=await savedState(item);
  const commands=[
   {type:'set_property',payload:{owner:'table:Item',name:'Name',property:'comment',value:'pending'}},
   {type:'add_resource',payload:{kind:'record',resource:{kind:'record',name:'Bonus',fields:[{name:'N',type:'int32'}]}}},
  ];
  const {original,body}=await draft(p,commands);
  const rejected=await p.request('/api/schema-workspace/save',body);
  assert.equal(rejected.status,409,JSON.stringify(rejected));
  assert.equal(rejected.conflict.kind,'target');
  assert.deepEqual(await savedState(item),before);
  assert.equal((await stat(blocker)).isDirectory(),true);
  assert.equal((await p.request('/api/schema-workspace')).data.schemaRevision,original.schemaRevision);
  assert.equal(await savedState(join(p.root,'.ct/export-publication.json')),null);
 }finally{await p.close();}
});
