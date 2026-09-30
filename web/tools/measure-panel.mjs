import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {once} from 'node:events';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {performance} from 'node:perf_hooks';

const repo=resolve(import.meta.dirname,'../..');
if(process.argv.includes('--live-python'))throw new Error('Live Python reference retired; use the frozen performance reports');
const outIndex=process.argv.indexOf('--out');
const out=outIndex<0?null:process.argv[outIndex+1];
if(outIndex>=0&&!out)throw new Error('--out needs a file path');
const binary=process.env.CT_WEB_BIN||join(repo,'native/target/release',process.platform==='win32'?'ct.exe':'ct');

function median(samples){const sorted=[...samples].sort((a,b)=>a-b);return sorted[Math.floor(sorted.length/2)];}
function canonical(value){
 if(Array.isArray(value))return value.map(canonical);
 if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])]));
 return value;
}
async function seed(root){
 await mkdir(join(root,'config/schemas'),{recursive:true});
 await mkdir(join(root,'config/types'),{recursive:true});
 await writeFile(join(root,'config/global.yaml'),'primary_lang: zh\nsecondary_langs: [en]\n');
 await writeFile(join(root,'config/schemas/Item.yaml'),'table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: Name\n    type: string\n    i18n: true\n');
}
async function launch(kind,root){
 const args=['panel','--root',root,'--port','0','--no-browser'];
 const started=performance.now();
 const child=spawn(binary,args,{env:process.env,stdio:['pipe','pipe','pipe']});
 let diagnostic='';
 child.stderr.on('data',chunk=>{diagnostic+=chunk;});
 const url=await new Promise((done,fail)=>{
  let stdout='';
  const timer=setTimeout(()=>{child.kill('SIGKILL');fail(new Error(`${kind} startup timed out: ${diagnostic}`));},15000);
  child.once('error',error=>{clearTimeout(timer);fail(error);});
  child.once('exit',code=>{clearTimeout(timer);fail(new Error(`${kind} exited ${code}: ${diagnostic}`));});
  child.stdout.on('data',chunk=>{stdout+=chunk;const match=stdout.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);done(match[0]);}});
 });
 for(let attempt=0;attempt<100;attempt++){
  try{const response=await fetch(url+'/api/workspace');if(response.ok)return {url,child,startupMs:performance.now()-started};}catch{}
  await new Promise(done=>setTimeout(done,20));
 }
 child.kill('SIGKILL');throw new Error(`${kind} never became ready: ${diagnostic}`);
}
async function close(child){
 if(child.exitCode!==null||child.signalCode!==null)return;
 const exited=once(child,'exit');child.kill('SIGINT');
 await Promise.race([exited,new Promise(done=>setTimeout(done,5000))]);
 if(child.exitCode===null&&child.signalCode===null){child.kill('SIGKILL');await exited;}
}
async function request(url,path,body){
 const start=performance.now();
 const response=await fetch(url+path,body===undefined?{}:{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
 const bytes=await response.arrayBuffer();
 const elapsed=performance.now()-start;
 const data=JSON.parse(Buffer.from(bytes).toString('utf8'));
 if(!response.ok||!data.ok)throw new Error(`${path}: ${response.status} ${JSON.stringify(data)}`);
 return {data:data.data,elapsed,bytes:bytes.byteLength};
}
async function samples(count,measure){const values=[];for(let i=0;i<count;i++)values.push(await measure());return values;}
async function measure(kind){
 const root=await mkdtemp(join(tmpdir(),`ct-panel-measure-${kind}-`));
 let service;
 try{
  await seed(root);
  const startups=[];
  for(let run=0;run<6;run++){
   service=await launch(kind,root);
   startups.push(service.startupMs);
   if(run<5){await close(service.child);service=undefined;}
  }
  const {url}=service;
  const snapshot=(await request(url,'/api/schema-workspace')).data;
  const candidateBody={schemaRevision:snapshot.schemaRevision,commands:[{type:'set_property',payload:{owner:'table:Item',name:'Name',property:'comment',value:'benchmark'}}],cursor:1,draftGeneration:1};
  const candidate=await samples(6,async()=>{
   const response=await request(url,'/api/schema-workspace/candidate',candidateBody);
   if(response.data.netDiff?.changedResources!==1)throw new Error(`${kind} candidate is not equivalent`);
   return response.elapsed;
  });
  const template=await request(url,'/api/schema-workspace/gen-template',{table:'Item'});
  if(!template.data)throw new Error(`${kind} template result missing`);
  const exportTimes=[];
  for(let i=0;i<3;i++){
   const start=performance.now();
   await request(url,'/api/export',{forced:true});
   let result;
   for(let poll=0;poll<500;poll++){
    result=(await request(url,'/api/export/progress')).data;
    if(result.status!=='running')break;
    await new Promise(done=>setTimeout(done,10));
   }
   if(result?.status!=='done')throw new Error(`${kind} export did not finish: ${JSON.stringify(result)}`);
   exportTimes.push(performance.now()-start);
  }
  await mkdir(join(root,'i18n/source'),{recursive:true});
  await mkdir(join(root,'i18n/en'),{recursive:true});
  const source=Object.fromEntries(Array.from({length:1000},(_,index)=>[`${index}.Name`,`原文 ${index} `.repeat(8)]));
  await writeFile(join(root,'i18n/source/Item.json'),JSON.stringify(source));
  await writeFile(join(root,'i18n/en/Item.json'),JSON.stringify({}));
  const large=await samples(6,async()=>{
   const response=await request(url,'/api/i18n/entries?table=Item&lang=en');
   if(!Array.isArray(response.data)||response.data.length!==1000||!response.data.some(row=>row.key==='999.Name'))throw new Error(`${kind} large response incomplete`);
   const ordered=[...response.data].sort((a,b)=>a.key.localeCompare(b.key));
   const hash=createHash('sha256').update(JSON.stringify(canonical(ordered))).digest('hex');
   return {ms:response.elapsed,bytes:response.bytes,hash};
  });
  if(large.some(value=>value.hash!==large[0].hash))throw new Error(`${kind} large response changed during measurement`);
  return {startupMs:startups.map(Math.round),startupMedianMs:Math.round(median(startups.slice(1))),candidateMs:candidate.map(Math.round),candidateMedianMs:Math.round(median(candidate.slice(1))),exportMs:exportTimes.map(Math.round),exportMedianMs:Math.round(median(exportTimes)),largeResponseMs:large.map(value=>Math.round(value.ms)),largeMedianMs:Math.round(median(large.slice(1).map(value=>value.ms))),largeBytes:large[0].bytes,largeDataSha256:large[0].hash};
 }finally{if(service)await close(service.child);await rm(root,{recursive:true,force:true});}
}

const report={format:'panel-performance/1',at:new Date().toISOString(),platform:process.platform,arch:process.arch,node:process.version,nativeBinary:binary,fixture:'one Table, empty generated workbook; 1000 i18n source entries',native:await measure('native')};
const json=JSON.stringify(report,null,2)+'\n';
if(out)await writeFile(out,json);else process.stdout.write(json);
