import {test} from 'node:test';
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

async function codenamePanel(){
 const panel=await startPanel();
 await writeFile(join(panel.root,'config/schemas/Item.yaml'),'table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: CodeName\n    type: string\nindexes:\n  - kind: codename\n');
 await writeFile(join(panel.root,'config/schemas/Quest.yaml'),'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n');
 const revision=(await panel.request('/api/schema-workspace')).data.schemaRevision;
 return {panel,revision};
}
const validate=(panel,revision,commands)=>panel.request('/api/schema-workspace/validate',{schemaRevision:revision,commands});

test('deleting an indexed table before reusing its name does not transfer the old index',async()=>{
 const {panel,revision}=await codenamePanel();try{
  const commands=[
   {type:'delete_resource',payload:{name:'table:Item'}},
   {type:'rename_resource',payload:{old:'Quest',new:'Item'}},
  ];
  const checked=await validate(panel,revision,commands);
  assert.equal(checked.status,200,JSON.stringify(checked));
  assert.equal(checked.data.valid,true,JSON.stringify(checked));
  const item=checked.data.resources.find(resource=>resource.resourceId==='table:Item');
  assert.ok(item,JSON.stringify(checked));
  assert.deepEqual(item.indexes,[]);
  assert.deepEqual(item.fields.map(field=>field.name),['Id']);
 }finally{await panel.close();}
});

test('deleting or renaming CodeName while the codename index remains is invalid',async()=>{
 const {panel,revision}=await codenamePanel();try{
  for(const tail of [
   {type:'delete_field',payload:{owner:'table:Item',name:'CodeName'}},
   {type:'rename_field',payload:{owner:'table:Item',old:'CodeName',new:'TypeCode'}},
  ]){
   const checked=await validate(panel,revision,[tail]);
   assert.equal(checked.status,200,JSON.stringify(checked));
   assert.equal(checked.data.valid,false,JSON.stringify(checked));
   assert.ok(checked.data.issues.some(issue=>issue.message.includes('codename 索引要求存在名为 CodeName')),JSON.stringify(checked));
  }
 }finally{await panel.close();}
});

test('explicitly removing the codename index makes either CodeName edit valid',async()=>{
 const {panel,revision}=await codenamePanel();try{
  const drop={type:'set_indexes',payload:{table:'table:Item',indexes:[]}};
  for(const tail of [
   {type:'delete_field',payload:{owner:'table:Item',name:'CodeName'}},
   {type:'rename_field',payload:{owner:'table:Item',old:'CodeName',new:'TypeCode'}},
  ]){
   const checked=await validate(panel,revision,[drop,tail]);
   assert.equal(checked.status,200,JSON.stringify(checked));
   assert.equal(checked.data.valid,true,JSON.stringify(checked));
   const item=checked.data.resources.find(resource=>resource.resourceId==='table:Item');
   assert.deepEqual(item.indexes,[],JSON.stringify(checked));
   assert.ok(!item.fields.some(field=>field.name==='CodeName'));
  }
 }finally{await panel.close();}
});
