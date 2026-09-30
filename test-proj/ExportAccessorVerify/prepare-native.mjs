import {spawnSync} from 'node:child_process';
import {cp,mkdir,readdir,readFile,rm,writeFile} from 'node:fs/promises';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {basename,join,resolve} from 'node:path';

const repo=resolve(import.meta.dirname,'../..');
const source=join(repo,'test-proj/ExportAccessorVerify');
const binary=process.env.CT_NATIVE_BIN||join(repo,'native/target/release',process.platform==='win32'?'ct.exe':'ct');
const dotnet=process.env.DOTNET_BIN||'dotnet';
const xtask=process.env.CT_XTASK_BIN||join(repo,'native/target/debug',process.platform==='win32'?'xtask.exe':'xtask');
const scratch=await mkdtemp(join(tmpdir(),'ct-accessor-verify-'));
const project=join(scratch,'ExportAccessorVerify');
const generated=join(project,'generated');
const fixtures=join(project,'fixtures');
const reader=join(scratch,'ConfigAccessorBench');
const workspace=join(scratch,'workspace');
function run(command,args){
 const result=spawnSync(command,args,{cwd:scratch,encoding:'utf8',timeout:120000,env:{...process.env,DOTNET_NOLOGO:'1'}});
 if(result.error)throw result.error;
 if(result.status!==0)throw new Error(`${command} ${args.join(' ')} failed (${result.status})\n${result.stdout}\n${result.stderr}`);
 return result.stdout;
}
try{
 await Promise.all([mkdir(generated,{recursive:true}),mkdir(fixtures,{recursive:true}),mkdir(reader,{recursive:true})]);
 await cp(join(repo,'native/fixtures/accessor_verify/workspace'),workspace,{recursive:true});
 for(const name of ['Program.cs','ExportAccessorVerify.csproj'])await cp(join(source,name),join(project,name));
 for(const name of ['WireReader.cs','Runtime.cs','ConfigReader.cs'])await cp(join(repo,'test-proj/ConfigAccessorBench',name),join(reader,name));
 const scalarOutput=join(scratch,'native-scalars');
 console.log(run(xtask,['accessor-fixtures','--root',repo,'--out',scalarOutput]).trim());
 await cp(join(scalarOutput,'ScalarsAccessor.cs'),join(generated,'ScalarsAccessor.cs'));
 for(const name of ['scalars.bin','scalars.json'])await cp(join(scalarOutput,name),join(fixtures,name));
 await cp(join(source,'fixtures/fnv_vectors.tsv'),join(fixtures,'fnv_vectors.tsv'));

 const exportOutput=run(binary,['export','--all','--root',workspace]);
 const output=join(workspace,'output');
 const accessors=(await readdir(join(output,'generated/csharp'))).filter(name=>name.endsWith('.cs'));
 for(const name of accessors)await cp(join(output,'generated/csharp',name),join(generated,name));
 for(const name of ['data_zh.bin','data_en.bin','data_ja.bin'])await cp(join(output,'binary',name),join(fixtures,name));
 const jsons=(await readdir(join(output,'json'))).filter(name=>name.endsWith('.json'));
 if(accessors.length!==5||jsons.length!==12)throw new Error(`incomplete export: ${accessors.length} accessors, ${jsons.length} JSON files`);
 for(const name of jsons)await cp(join(output,'json',name),join(fixtures,name));
 const manifests={};
 const tables=(await readdir(join(workspace,'config/schemas'))).filter(name=>name.endsWith('.yaml')).map(name=>basename(name,'.yaml'));
 for(const name of (await readdir(join(workspace,'excel/layout_manifests'))).filter(name=>name.endsWith('.json'))){
  const key=tables.find(table=>table.toLowerCase()===basename(name,'.json').toLowerCase());
  if(!key)throw new Error(`manifest has no schema: ${name}`);
  manifests[key]=JSON.parse(await readFile(join(workspace,'excel/layout_manifests',name),'utf8'));
 }
 await writeFile(join(fixtures,'manifests.json'),JSON.stringify(manifests,null,2)+'\n');
 run(dotnet,['build',join(project,'ExportAccessorVerify.csproj'),'--configuration','Release']);
 const runtimeFixtures=join(project,'bin/Release/net10.0/fixtures');
 await mkdir(runtimeFixtures,{recursive:true});
 for(const name of await readdir(fixtures))await cp(join(fixtures,name),join(runtimeFixtures,name));
 const result=run(dotnet,['run','--project',join(project,'ExportAccessorVerify.csproj'),'--configuration','Release','--no-build']);
 console.log(`native export: ${exportOutput.trim().split('\n').at(-1)}`);
 console.log(`generated accessors: ${accessors.length}; JSON files: ${jsons.length}`);
 console.log(result.trim());
}finally{
 if(process.argv.includes('--keep'))console.log(`temporary project: ${scratch}`);
 else await rm(scratch,{recursive:true,force:true});
}
