import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,stat,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {startPanel} from './panel-helper.mjs';

test('native package serves assets and diagnostic workspace without Python',async()=>{
 const p=await startPanel({invalid:true});try{
 assert.equal((await fetch(p.url+'/')).status,200);assert.match(await (await fetch(p.url+'/static/js/app-shell.js')).text(),/AppShell/);
 assert.equal((await p.request('/api/service')).data.kernel,'native');
 assert.equal((await p.request('/api/workspace')).ok,false);
 assert.equal((await fetch(p.url+'/api/export',{method:'POST',headers:{'content-type':'application/json','origin':'http://evil.example'},body:'{}'})).status,403);
 assert.equal((await fetch(p.url+'/api/export',{method:'POST',headers:{'content-type':'application/json'},body:'{'})).status,400);
 assert.equal((await fetch(p.url+'/static/%2e%2e%2fCargo.toml')).status,404);
 }finally{await p.close();}
});
test('schema candidate, guarded YAML-only save, undo cursor and no-op',async()=>{
 const p=await startPanel();try{
 const s=await p.request('/api/schema-workspace');assert.equal(s.status,200);
 const file=join(p.root,'config/schemas/Item.yaml');const before=await readFile(file,'utf8');
 const commands=[{type:'set_property',payload:{owner:'table:Item',name:'Name',property:'comment',value:'新注释'}}];
 const body={schemaRevision:s.data.schemaRevision,commands,cursor:1,draftGeneration:7};
 const c=await p.request('/api/schema-workspace/candidate',body);assert.equal(c.status,200,JSON.stringify(c));assert.equal(c.data.draftGeneration,7);assert.equal(c.data.netDiff.changedResources,1);assert.equal(c.data.resources[0].fields[1].comment,'新注释');
 assert.equal(await readFile(file,'utf8'),before);
 const undo=await p.request('/api/schema-workspace/candidate',{...body,cursor:0});assert.equal(undo.data.netDiff.isNoOp,true);
 assert.equal((await p.request('/api/schema-workspace/save',{...body,candidateHash:'forged'})).status,409);
 const saved=await p.request('/api/schema-workspace/save',{...body,candidateHash:c.data.candidateHash});assert.equal(saved.status,200,JSON.stringify(saved));assert.equal(saved.data.netDiff.isNoOp,true);assert.notEqual(saved.data.schemaRevision,s.data.schemaRevision);
 await assert.rejects(stat(join(p.root,'excel')));await assert.rejects(stat(join(p.root,'output')));
 assert.equal((await p.request('/api/schema-workspace/candidate',body)).status,409);
 const clean={schemaRevision:saved.data.schemaRevision,commands:[],cursor:0};const hash=(await p.request('/api/schema-workspace/candidate',clean)).data.candidateHash;
 const time=(await stat(file)).mtimeMs;const noOp=await p.request('/api/schema-workspace/save',{...clean,candidateHash:hash});assert.equal(noOp.data.isNoOp,true);assert.equal((await stat(file)).mtimeMs,time);
 }finally{await p.close();}
});
test('template generation, export and task endpoints',async()=>{
 const p=await startPanel();try{
 assert.deepEqual((await p.request('/api/workspace')).data.status.missing,['Item']);
 assert.equal((await p.request('/api/schema-workspace/gen-template',{table:'Nope'})).status,404);
 const template=await p.request('/api/schema-workspace/gen-template',{table:'Item'});assert.equal(template.status,200,JSON.stringify(template));
 const run=await p.request('/api/export',{});assert.equal(run.data.status,'running');
 let progress;for(let i=0;i<100;i++){progress=await p.request('/api/export/progress');if(progress.data.status!=='running')break;await new Promise(r=>setTimeout(r,30));}
 assert.equal(progress.data.status,'done',JSON.stringify(progress));assert.equal(progress.data.tables_exported,1);
 assert.equal((await p.request('/api/history')).data.length,1);
 }finally{await p.close();}
});

test('all legacy static entry assets and core dependency boundary',async()=>{
 const p=await startPanel();try{
 const assets=['index.html','styles/tokens.css','styles/base.css','styles/layout.css','styles/components.css','js/app-shell.js','js/core/dialog.js','js/core/projection.js','js/core/draft-store.js','js/core/api.js','js/core/router.js','js/core/task.js'];
 for(const asset of assets){const response=await fetch(p.url+'/static/'+asset);assert.equal(response.status,200);assert.ok((await response.text()).length>0)}
 const index=await(await fetch(p.url+'/')).text();for(const css of ['tokens','base','layout','components'])assert.ok(index.includes('/static/styles/'+css+'.css'));assert.ok(index.includes('src="/static/js/module-registry.js"'));
 const {readdir}=await import('node:fs/promises');for(const file of await readdir(new URL('../static/js/core/',import.meta.url))){if(!file.endsWith('.js'))continue;const source=await readFile(new URL('../static/js/core/'+file,import.meta.url),'utf8');assert.ok(!source.split('\n').some(line=>line.startsWith('import ')&&line.includes('modules/')),file)}
 }finally{await p.close();}
});

test('failed task can be dismissed across clients and is reset on the next run',async()=>{
 const p=await startPanel();try{
 for(let run=0;run<2;run++){
  assert.equal((await p.request('/api/export',{})).status,200);
  let progress;for(let i=0;i<100;i++){progress=await p.request('/api/export/progress');if(progress.data.status!=='running')break;await new Promise(r=>setTimeout(r,20));}
  assert.equal(progress.data.status,'error');assert.equal((await p.request('/api/tasks')).data.length,1);
  assert.equal((await p.request('/api/tasks/canonical-export/dismiss',{})).data.dismissed,true);
  assert.deepEqual((await p.request('/api/tasks')).data,[]);
  assert.equal((await p.request('/api/export/progress')).data.status,'error');
 }
 assert.equal((await p.request('/api/tasks/unknown/dismiss',{})).status,404);
 }finally{await p.close();}
});

test('concurrent page views do not contend as workspace writers',async()=>{
 const p=await startPanel();try{
 const views=await Promise.all(['/api/workspace','/api/schema-workspace','/api/i18n/tables','/api/i18n/status','/api/history','/api/schema-workspace'].map(path=>p.request(path)));
 assert.deepEqual(views.map(v=>v.status),[200,200,200,200,200,200]);
 }finally{await p.close();}
});
