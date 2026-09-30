import {createHash} from 'node:crypto';
import {readFile, readdir, access} from 'node:fs/promises';
import {resolve, join} from 'node:path';

// A new or changed legacy script must receive an explicit audit, never silently join CI.
const root = resolve(import.meta.dirname, '..');
const inventory = JSON.parse(await readFile(join(root, 'test-proj/python-retirement.json'), 'utf8'));
if (inventory.schema !== 'ct-test-proj-retirement/1' || inventory.files.length !== 19) {
  throw new Error('test-proj retirement inventory must contain all 19 audited scripts');
}
async function pythonPaths(relative) {
  const entries = await readdir(join(root, relative), {withFileTypes: true});
  const paths = [];
  for (const entry of entries) {
    if (['bin', 'obj', '.venv', '__pycache__', 'node_modules'].includes(entry.name)) continue;
    const path = `${relative}/${entry.name}`;
    if (entry.isDirectory()) paths.push(...await pythonPaths(path));
    else if (entry.name.endsWith('.py')) paths.push(path);
  }
  return paths.sort();
}
const actual = await pythonPaths('test-proj');
const declared = inventory.files.filter(entry => entry.status === 'historical').map(entry => entry.path).sort();
if (JSON.stringify(actual) !== JSON.stringify(declared) || new Set(declared).size !== 17) {
  throw new Error('test-proj Python script set differs from explicit retirement inventory');
}
for (const entry of inventory.files) {
  if (!['replaced', 'historical'].includes(entry.status) || !entry.reason?.trim()) {
    throw new Error(`unaudited legacy entry: ${entry.path}`);
  }
  if (!/^test-proj\/[\w./-]+\.py$/.test(entry.path) || entry.path.split('/').includes('..') ||
      !/^[\w./-]+$/.test(entry.successor) || entry.successor.split('/').includes('..') || entry.successor.endsWith('.py')) {
    throw new Error(`unsafe or executable Python successor: ${entry.path}`);
  }
  // Removed formal sources remain available as immutable, non-executable oracles.
  const source = entry.status === 'historical' ? entry.path :
    `native/fixtures/accessor_verify/source/${entry.path.split('/').pop()}.txt`;
  if (entry.status === 'replaced') {
    let present = false;
    try { await access(join(root, entry.path)); present = true; } catch {}
    if (present) throw new Error(`retired formal source remains: ${entry.path}`);
  }
  const sha = createHash('sha256').update(await readFile(join(root, source))).digest('hex');
  if (sha !== entry.sha256) throw new Error(`legacy source changed since audit: ${entry.path}`);
  await access(join(root, entry.successor));
}
const replaced = inventory.files.filter(entry => entry.status === 'replaced').map(entry => entry.path).sort();
if (JSON.stringify(replaced) !== JSON.stringify([
  'test-proj/ExportAccessorVerify/gen_scalars_bench.py',
  'test-proj/ExportAccessorVerify/prepare.py',
])) throw new Error('formal preparation replacements changed without updating acceptance scope');
for (const path of inventory.activeEntries) {
  if (!path.startsWith('test-proj/') || !path.endsWith('.mjs') || path.split('/').includes('..')) throw new Error('invalid active entry');
  await access(join(root, path));
}
console.log('test-proj: 19/19 scripts audited; 2 retired preparation entries verified in static oracles, 17 historical experiments');
