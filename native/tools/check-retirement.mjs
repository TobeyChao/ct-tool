import {createHash} from 'node:crypto';
import {readFile, access, readdir} from 'node:fs/promises';
import {resolve, join} from 'node:path';

const root=resolve(import.meta.dirname,'../..');
const path='native/docs/baseline/python-retirement-inventory.json';
const bytes=await readFile(join(root,path));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
if(sha(bytes)!==(await readFile(join(root,path+'.sha256'),'utf8')).trim()) throw new Error('retirement inventory checksum mismatch');
const inventory=JSON.parse(bytes), after=process.argv.includes('--after-deletion');
if(inventory.format!=='python-retirement-inventory/2'||inventory.items.length!==313) throw new Error('incomplete retirement scope');
const entries=new Map();
for(const item of inventory.items){
  if(entries.has(item.path)||item.status!=='classified'||!item.reason?.trim()||!item.replacement.length) throw new Error('unclassified/duplicate retirement item');
  for(const p of [item.path,...item.replacement,...item.archive]) if(p.startsWith('/')||p.split('/').includes('..')) throw new Error('unsafe inventory path');
  entries.set(item.path,item);
  for(const p of [...item.replacement,...item.archive]) await access(join(root,p));
  if(item.disposition==='remove'){
    let present=true;try{await access(join(root,item.path))}catch{present=false}
    if(after&&present) throw new Error(`retired file remains: ${item.path}`);
    if(!after&&(!present||sha(await readFile(join(root,item.path)))!==item.sourceSha256)) throw new Error(`retirement source changed/missing before removal: ${item.path}`);
  }
}
if([...entries.keys()].filter(p=>p.startsWith('ct/')).length!==249) throw new Error('legacy tracked tree scope shrank');
const reference=JSON.parse(await readFile(join(root,'native/docs/baseline/reference-tests.json'),'utf8'));
for(const [p,file] of Object.entries(reference.files)) if(entries.get(p)?.sourceSha256!==file.sha256) throw new Error(`legacy test source omitted/changed: ${p}`);
async function scan(relative){
  let children;try{children=await readdir(join(root,relative),{withFileTypes:true})}catch(e){if(e.code==='ENOENT')return;throw e}
  for(const child of children){
    if(['target','dist','node_modules','bin','obj','build','.venv','__pycache__','.dart_tool','ephemeral','_ws'].includes(child.name))continue;
    const p=`${relative}/${child.name}`;
    if(child.isDirectory()) await scan(p);
    else if(child.name.endsWith('.py')){
      const item=entries.get(p);
      if(!item || (after&&item.disposition!=='retain-historical')) throw new Error(`unclassified/active Python file: ${p}`);
    }
  }
}
// 版本化范围全扫，避免出现清单外的“活跃 Python 文件”；跳过目录见 scan 的噪声列表。
for(const scope of ['ct','native','test-proj','openspec','docs','web','launcher','.github'])await scan(scope);
const dispositions=inventory.items.reduce((acc,item)=>(acc[item.disposition]=(acc[item.disposition]??0)+1,acc),{});
const legacyCt=[...entries.keys()].filter(p=>p.startsWith('ct/')).length;
console.log(`retirement: ${inventory.items.length} entries classified; ${legacyCt} legacy ct files, ${dispositions.remove} removals, ${dispositions['retain-historical']} retained historical paths; ${after?'deletion verified':'removal source checksums verified'}`);
