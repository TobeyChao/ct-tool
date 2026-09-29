import {spawn} from 'node:child_process';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {once} from 'node:events';
export async function startPanel({invalid=false,rootDir=null,cleanupRoot=true,port=0}={}) {
 const root=rootDir||await mkdtemp(join(tmpdir(),'ct-web-中文 '));
 if(!invalid&&!rootDir){await mkdir(join(root,'config/schemas'),{recursive:true});await mkdir(join(root,'config/types'),{recursive:true});
 await writeFile(join(root,'config/global.yaml'),'primary_lang: zh\nsecondary_langs: [en]\n');
 await writeFile(join(root,'config/schemas/Item.yaml'),'table: Item\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: Name\n    type: string\n    i18n: true\n');}
 const binary=process.env.CT_WEB_BIN||resolve(import.meta.dirname,'../../native/target/debug/'+(process.platform==='win32'?'ct.exe':'ct'));
 const child=spawn(binary,['panel','--root',root,'--port',String(port),'--no-browser','--shutdown-on-stdin-eof'],{stdio:['pipe','pipe','pipe']});
 let output='';child.stderr.on('data',b=>output+=b);
 const url=await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>{child.kill();reject(new Error('panel startup timed out: '+output));},15000);child.once('error',e=>{clearTimeout(timeout);reject(e)});child.once('exit',code=>{clearTimeout(timeout);reject(new Error('panel exited '+code+': '+output));});child.stdout.on('data',chunk=>{output+=chunk;const m=output.match(/http:\/\/[^\s（]+/);if(m){clearTimeout(timeout);resolve(m[0]);}})});
 return {root,child,url,request:async(path,data)=>{const r=await fetch(url+path,data===undefined?{}:{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(data)});return {status:r.status,...await r.json()};},close:async()=>{if(child.exitCode===null&&child.signalCode===null){const exit=once(child,'exit');child.stdin.end();const timer=setTimeout(()=>child.kill('SIGKILL'),15000);try{await exit;}finally{clearTimeout(timer);}}if(cleanupRoot)await rm(root,{recursive:true,force:true});}};
}
