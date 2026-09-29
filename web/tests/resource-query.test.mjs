import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdir, realpath, stat, appendFile} from 'node:fs/promises';
import {join, dirname} from 'node:path';
import {startPanel} from './panel-helper.mjs';

const frozen = JSON.parse(await readFile(new URL('../../native/docs/baseline/web-resource-query-python.json', import.meta.url), 'utf8'));

async function install(panel) {
  for (const [name, text] of Object.entries(frozen.fixture.files)) {
    const target = join(panel.root, name);
    await mkdir(dirname(target), {recursive: true});
    await writeFile(target, text);
  }
}

test('custom-directory status, all resources and reverse references match frozen Web responses', async () => {
  const panel = await startPanel();
  try {
    await install(panel);
    const root = await realpath(panel.root);
    const normalize = value => typeof value === 'string'
      ? value.replaceAll(root, '${ROOT}').replaceAll(panel.root, '${ROOT}')
      : Array.isArray(value) ? value.map(normalize)
        : value && typeof value === 'object'
          ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalize(item)]))
          : value;
    const matches = async (path, expected) => {
      const {status, ...body} = normalize(await panel.request(path));
      assert.equal(status, expected.status, path);
      assert.deepEqual(body, expected.body, path);
    };
    const schemaFile = join(panel.root, 'data/schemas/Item.yaml');
    const before = await readFile(schemaFile);
    const beforeMtime = (await stat(schemaFile, {bigint: true})).mtimeNs;
    const ledger = join(panel.root, 'data/cache/state.json');
    await matches('/api/workspace', frozen.captures.before.workspace);
    await matches('/api/schema-workspace', frozen.captures.before.schema);
    assert.deepEqual(await readFile(schemaFile), before);
    assert.equal((await stat(schemaFile, {bigint: true})).mtimeNs, beforeMtime);
    await assert.rejects(stat(ledger), {code: 'ENOENT'});

    for (const table of ['Item', 'Monster']) {
      assert.equal((await panel.request('/api/schema-workspace/gen-template', {table})).status,
        frozen.captures.templateStatus[table]);
    }
    await matches('/api/workspace', frozen.captures.afterTemplates.workspace);
    const state = JSON.parse(await readFile(ledger, 'utf8'));
    assert.equal(state.format, 'canonical-cache/1');
    assert.deepEqual(Object.keys(state.excel_hashes).sort(), ['Item', 'Monster']);
    const ledgerBeforeRead = await readFile(ledger);
    await writeFile(schemaFile, (await readFile(schemaFile, 'utf8')).replace('indexes:\n',
      '  - name: Added\n    type: int32\nindexes:\n'));
    await matches('/api/workspace', frozen.captures.afterDrift.workspace);
    await appendFile(join(panel.root, 'data/books/Monster.xlsx'), Buffer.from([0]));
    await matches('/api/workspace', frozen.captures.afterChangedAndDrift.workspace);
    assert.deepEqual(await readFile(ledger), ledgerBeforeRead, 'read-only status must not advance the ledger');
    await assert.rejects(stat(join(panel.root, 'cache/state.json')), {code: 'ENOENT'});
  } finally {
    await panel.close();
  }
});

test('template and success ledger roll back together when custom cache target cannot publish', async () => {
  const panel = await startPanel();
  try {
    await install(panel);
    const state = join(panel.root, 'data/cache/state.json');
    await mkdir(state, {recursive: true});
    const result = await panel.request('/api/schema-workspace/gen-template', {table: 'Item'});
    assert.notEqual(result.status, 200, JSON.stringify(result));
    await assert.rejects(stat(join(panel.root, 'data/books/Item.xlsx')), {code: 'ENOENT'});
    await assert.rejects(stat(join(panel.root, 'data/books/layout_manifests/Item.json')), {code: 'ENOENT'});
    assert.equal((await stat(state)).isDirectory(), true);
    assert.deepEqual((await panel.request('/api/workspace')).data.status.missing, ['Item', 'Monster']);
  } finally {
    await panel.close();
  }
});
