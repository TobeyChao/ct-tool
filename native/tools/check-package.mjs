import {createHash} from 'node:crypto';
import {readFile, readdir, lstat, writeFile, mkdir, realpath, access} from 'node:fs/promises';
import {constants} from 'node:fs';
import {resolve, join, dirname, sep} from 'node:path';

const args = process.argv.slice(2);
function option(name) { const index=args.indexOf(name); return index<0?null:args[index+1]; }
const packagePath=option('--package'), appPath=option('--app'), out=option('--out');
if ((!packagePath && !appPath) || (packagePath && appPath)) throw new Error('use --package <directory> or --app <macOS app>');
const root=resolve(packagePath||appPath);
const runtime=appPath?join(root,'Contents/Resources/runtime'):root;
const binary=join(runtime,appPath?'ct':'bin/ct');
const realRoot=await realpath(root), realRuntime=await realpath(runtime);
if(realRuntime!==realRoot&&!realRuntime.startsWith(realRoot+sep)) throw new Error('runtime escapes delivered bundle');
if(!(await lstat(binary)).isFile()) throw new Error('runtime binary must be a bundled regular file');
await access(binary,constants.X_OK);
const files=[];
async function walk(dir, relative='') {
  for (const entry of await readdir(dir,{withFileTypes:true})) {
    const name=entry.name, path=join(dir,name), rel=relative?`${relative}/${name}`:name;
    if (/^(python(?:[\d.]|$)|py\.exe$|libpython|flask$|(?:site|dist)-packages$)/i.test(name)||/\.(py|pyc|pyo)$/i.test(name)) throw new Error(`interpreter/Flask payload forbidden: ${rel}`);
    const info=await lstat(path);
    if(info.isSymbolicLink()) continue; // Framework aliases; actual files are walked once.
    if(info.isDirectory()) await walk(path,rel);
    else files.push(rel);
  }
}
await walk(root);
const metadata=JSON.parse(await readFile(join(runtime,'VERSION.json'),'utf8'));
if(metadata.schema!=='ct-runtime-package/1'||metadata.pythonRuntimeRequired!==false||metadata.family!=='macos'||!metadata.target?.endsWith('apple-darwin')) throw new Error('not an accepted macOS native runtime manifest');
if(packagePath && JSON.stringify(files.sort())!==JSON.stringify(['README.md','RUNTIME-CHECK.txt','VERSION.json','bin/ct'].sort())) throw new Error('native package must contain exactly four versioned payload files');
const bytes=await readFile(binary), hash=createHash('sha256').update(bytes).digest('hex');
if(metadata.files.binary.sha256!==hash||metadata.files.binary.bytes!==bytes.length) throw new Error('runtime binary checksum/size differs from VERSION.json');
const check=await readFile(join(runtime,'RUNTIME-CHECK.txt'),'utf8');
if(!check.includes('[ct panel]')||!check.includes('stdin EOF')||!check.includes('hello=true open=true shutdown=true')) throw new Error('missing actual CLI/worker/panel/exit runtime evidence');
const report={schema:'ct-package-check/1',kind:appPath?'macos-launcher':'native-runtime',root,target:metadata.target,binary,sha256:hash,bytes:bytes.length,payloadFiles:files.length,pythonPayload:false,flaskPayload:false,runtimeEvidencePresent:true};
if(out){await mkdir(dirname(resolve(out)),{recursive:true});await writeFile(out,JSON.stringify(report,null,2)+'\n');}
console.log(JSON.stringify(report,null,2));
