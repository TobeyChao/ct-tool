import {readFileSync,existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
const root=resolve(import.meta.dirname,'../..');
const matrix=JSON.parse(readFileSync(resolve(root,'native/docs/baseline/web-parity.json')));
assert.equal(matrix.format,'web-parity/1');
assert.equal(matrix.files.length,15,'Frozen Web baseline must not shrink');
assert.equal(matrix.scenarios.length,146,'Frozen scenario inventory must not shrink');
const sources=new Set();
for(const scenario of matrix.scenarios){
 assert(!sources.has(scenario.source),'Duplicate scenario '+scenario.source);sources.add(scenario.source);
 assert(scenario.target && scenario.scenario,'Missing acceptance target');
 assert(['pending','verified','allowed-difference','historical'].includes(scenario.status));
 if(scenario.status==='verified'){
  assert(scenario.evidence,'Verified scenarios need recorded evidence');
  assert(existsSync(resolve(root,scenario.target)),'Missing verified target '+scenario.target);
  assert(readFileSync(resolve(root,scenario.target),'utf8').includes(scenario.scenario),'Missing test anchor '+scenario.scenario);
  assert(existsSync(resolve(root,scenario.evidence)),'Missing execution evidence');
 }
}
for(const {file,sha256} of matrix.files){
 const scenarios=matrix.scenarios.filter(s=>s.source.startsWith(file+'::'));assert(scenarios.length>0,file);
 const path=resolve(root,file);
 if(existsSync(path)){
  const text=readFileSync(path,'utf8');assert.equal(createHash('sha256').update(text).digest('hex'),sha256,'Frozen source changed: '+file);
  const names=[...text.matchAll(/^def (test_\w+)\(/gm)].map(m=>m[1]);
  assert.deepEqual(scenarios.map(s=>s.source.split('::')[1]).sort(),names.sort());
 }
}
const pending=matrix.scenarios.filter(s=>s.status==='pending').length;
console.log(`${matrix.scenarios.length} scenarios, ${matrix.files.length} source files; ${pending} pending. G1 ${pending?'NOT PASSED':'requires execution evidence'}.`);
if(process.argv.includes('--require-complete'))assert.equal(pending,0,'G1 incomplete; Python retirement is blocked');
