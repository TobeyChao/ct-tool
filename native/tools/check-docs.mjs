import {readFile, access} from 'node:fs/promises';
import {resolve, dirname, join} from 'node:path';

const root=resolve(import.meta.dirname,'../..');
const paths=['README.md','AGENTS.md','docs/README.md','docs/agent-project-reference.md',
  'docs/schema-save-migration.md','docs/native-migration.md','native/README.md','web/README.md','launcher/README.md'];
let links=0;
for(const path of paths){
  const text=await readFile(join(root,path),'utf8');
  if(/ct\/docs\//.test(text)) throw new Error(`active document still points into retired docs: ${path}`);
  if(/(?:pip install|python(?:3)? -m (?:venv|pytest)|ct\/\.venv\/bin\/python)/.test(text)) throw new Error(`active Python install/test command: ${path}`);
  for(const match of text.matchAll(/\]\(([^\n)]+)\)/g)){
    const href=match[1].split('#')[0];
    if(!href || /^[a-z]+:/.test(href)) continue;
    await access(resolve(root,dirname(path),decodeURIComponent(href)));links++;
  }
}
console.log(`active docs: ${paths.length} files, ${links} local file links valid; no retired install/doc entry`);
