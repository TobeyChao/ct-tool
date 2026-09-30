import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile, readdir, stat} from 'node:fs/promises';
import {resolve, join, dirname, sep} from 'node:path';
import {fileURLToPath} from 'node:url';

const repo = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const staticRoot = join(repo, 'web/static');

async function filesUnder(root, prefix = '') {
  const files = [];
  for (const entry of await readdir(join(root, prefix), {withFileTypes: true})) {
    const name = join(prefix, entry.name);
    if (entry.isDirectory()) files.push(...await filesUnder(root, name));
    else files.push(name.split(sep).join('/'));
  }
  return files.sort();
}

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

export async function checkStaticAssets() {
  const manifest = JSON.parse(await readFile(join(repo, 'web/static-manifest.json'), 'utf8'));
  assert.equal(manifest.format, 'web-static-manifest/1');
  assert.equal(manifest.sourceCommit, '8dc7b81');
  const expected = manifest.files.map(item => item.path);
  assert.deepEqual(expected, [...expected].sort(), 'manifest paths must be ordered');
  assert.deepEqual(await filesUnder(staticRoot), expected, 'migrated static tree must be complete');

  for (const item of manifest.files) {
    const target = join(staticRoot, item.path);
    const bytes = await readFile(target);
    assert.ok(bytes.length > 0, `${item.path} is empty`);
    if (item.migration === 'identical') {
      assert.equal(sha256(bytes), item.legacySha256, `${item.path} changed from the frozen Web baseline`);
    } else {
      assert.equal(item.migration, 'adapted', item.path);
      assert.ok(item.reason, `${item.path} needs a migration reason`);
    }
    if (item.path.endsWith('.js')) {
      const source = bytes.toString('utf8');
      for (const match of source.matchAll(/(?:from\s*|import\s*\(\s*)['"]([^'"]+)['"]/g)) {
        const specifier = match[1];
        if (!specifier.startsWith('.') && !specifier.startsWith('/static/')) continue;
        const imported = specifier.startsWith('/static/')
          ? join(staticRoot, specifier.slice('/static/'.length))
          : resolve(dirname(target), specifier);
        assert.ok(imported.startsWith(staticRoot + sep), `${item.path}: import escapes static tree`);
        assert.ok((await stat(imported)).isFile(), `${item.path}: missing ${specifier}`);
      }
      if (item.path.startsWith('js/core/')) {
        assert.ok(!source.split('\n').some(line => line.startsWith('import ') && line.includes('modules/')),
          `${item.path}: core must not import a business module`);
      }
    }
  }
  const index = await readFile(join(staticRoot, 'index.html'), 'utf8');
  for (const css of ['tokens', 'base', 'layout', 'components']) {
    assert.ok(index.includes(`/static/styles/${css}.css`));
  }
  assert.ok(index.includes('src="/static/js/module-registry.js"'));

  return {files: expected.length, adapted: manifest.files.filter(item => item.migration === 'adapted').length};
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes('--live-old')) throw new Error('Old Web tree retired; compare against the frozen manifest');
  const result = await checkStaticAssets();
  console.log(`Static assets verified: ${result.files} files, ${result.adapted} Web adapter changes.`);
}
