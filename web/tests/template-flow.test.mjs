import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { startPanel } from './panel-helper.mjs';

test('template generation uses saved Schema and stays independent from YAML save and export', async () => {
  const panel = await startPanel();
  try {
    const before = (await panel.request('/api/schema-workspace')).data;
    const commands = [{ type: 'add_field', payload: {
      owner: 'table:Item', field: { name: 'Weight', type: 'float' },
    } }];
    const candidate = await panel.request('/api/schema-workspace/candidate', {
      schemaRevision: before.schemaRevision, commands,
    });
    assert.equal(candidate.status, 200, JSON.stringify(candidate));
    const saved = await panel.request('/api/schema-workspace/save', {
      schemaRevision: before.schemaRevision, commands,
      candidateHash: candidate.data.candidateHash,
    });
    assert.equal(saved.status, 200, JSON.stringify(saved));
    const workbook = join(panel.root, 'excel/Item.xlsx');
    await assert.rejects(stat(workbook), { code: 'ENOENT' });
    assert.deepEqual((await panel.request('/api/workspace')).data.status.missing, ['Item']);
    const generated = await panel.request('/api/schema-workspace/gen-template', { table: 'Item' });
    assert.equal(generated.status, 200, JSON.stringify(generated));
    const manifest = JSON.parse(await readFile(join(panel.root, 'excel/layout_manifests/Item.json')));
    assert.deepEqual(manifest.columns.map(column => column.leaf), ['Id', 'Name', 'Weight']);
    assert.ok((await stat(workbook)).size > 0);
    assert.deepEqual((await panel.request('/api/workspace')).data.status.missing, []);
    await assert.rejects(stat(join(panel.root, 'output')), { code: 'ENOENT' });
    assert.equal((await panel.request('/api/schema-workspace/gen-template', { table: 'Unknown' })).status, 404);
  } finally {
    await panel.close();
  }
});

test('missing manifest and malformed workbook reject regeneration without changing the original files', async () => {
  const panel = await startPanel();
  try {
    assert.equal((await panel.request('/api/schema-workspace/gen-template', { table: 'Item' })).status, 200);
    const workbook = join(panel.root, 'excel/Item.xlsx');
    const manifest = join(panel.root, 'excel/layout_manifests/Item.json');
    const ledger = join(panel.root, 'cache/state.json');
    const original = await readFile(workbook);
    const oldLedger = await readFile(ledger);
    const oldManifest = await readFile(manifest);
    await rm(manifest);
    const withoutManifest = await panel.request('/api/schema-workspace/gen-template', { table: 'Item' });
    assert.notEqual(withoutManifest.status, 200);
    assert.match(withoutManifest.error, /缺少布局 manifest/);
    assert.deepEqual(await readFile(workbook), original);
    assert.deepEqual(await readFile(ledger), oldLedger);
    await writeFile(manifest, oldManifest);
    await writeFile(workbook, 'invalid xlsx');
    const failed = await panel.request('/api/schema-workspace/gen-template', { table: 'Item' });
    assert.notEqual(failed.status, 200);
    assert.deepEqual(await readFile(workbook), Buffer.from('invalid xlsx'));
    assert.deepEqual(await readFile(manifest), oldManifest);
    assert.deepEqual(await readFile(ledger), oldLedger);
  } finally {
    await panel.close();
  }
});
