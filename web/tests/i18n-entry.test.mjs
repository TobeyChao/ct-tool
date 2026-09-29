import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { startPanel } from './panel-helper.mjs';

test('translation listing exposes every entry beyond a page, four states, and exact single-entry writes', async () => {
  const panel = await startPanel();
  try {
    await mkdir(join(panel.root, 'i18n/source'), { recursive: true });
    await mkdir(join(panel.root, 'i18n/en'), { recursive: true });
    const source = Object.fromEntries(Array.from({ length: 2501 }, (_, i) => [`${i + 1}.Name`, `原文 ${i + 1}`]));
    await writeFile(join(panel.root, 'i18n/source/Item.json'), JSON.stringify(source));
    const enFile = join(panel.root, 'i18n/en/Item.json');
    await writeFile(enFile, JSON.stringify({
      '1.Name': { source: source['1.Name'], text: 'Sword', confirmed: true, status: 'translated' },
      '2.Name': { source: '旧原文', text: 'Shield', confirmed: true, status: 'translated' },
      '2501.Name': { source: source['2501.Name'], text: '', confirmed: false, status: 'missing' },
      '9999.Name': { source: '已删除', text: 'Orphan', confirmed: true, status: 'translated' },
    }));
    const other = join(panel.root, 'i18n/fr/Item.json');
    await mkdir(join(panel.root, 'i18n/fr'), { recursive: true });
    await writeFile(other, '{"do-not-touch":true}');
    const otherBefore = await readFile(other);
    const tables = await panel.request('/api/i18n/tables');
    assert.equal(tables.status, 200);
    assert.equal(tables.data.find(table => table.table === 'Item').has_i18n, true);
    const listing = await panel.request('/api/i18n/entries?table=Item&lang=en');
    assert.equal(listing.status, 200);
    assert.equal(listing.data.length, 2502);
    assert.equal(listing.data.find(entry => entry.key === '1.Name').status, 'translated');
    assert.equal(listing.data.find(entry => entry.key === '2.Name').status, 'stale');
    assert.equal(listing.data.find(entry => entry.key === '3.Name').status, 'missing');
    assert.equal(listing.data.find(entry => entry.key === '9999.Name').status, 'orphan');
    const total = await panel.request('/api/i18n/status');
    assert.equal(total.data.en.total, 2502);
    assert.equal(total.data.en.tables.Item.orphan, 1);
    const longText = '译文🙂'.repeat(2000);
    const saved = await panel.request('/api/i18n/entry', {
      table: 'Item', lang: 'en', key: '2501.Name', text: longText, confirmed: true,
    });
    assert.equal(saved.status, 200, JSON.stringify(saved));
    assert.equal(saved.data.status, 'translated');
    const cleared = await panel.request('/api/i18n/entry', {
      table: 'Item', lang: 'en', key: '1.Name', text: '', confirmed: true,
    });
    assert.equal(cleared.data.status, 'missing');
    const disk = JSON.parse(await readFile(enFile));
    assert.equal(disk['2501.Name'].text, longText);
    assert.equal(disk['1.Name'].text, '');
    assert.equal(disk['2.Name'].text, 'Shield');
    assert.deepEqual(await readFile(other), otherBefore);
    assert.equal((await panel.request('/api/i18n/entry', {
      table: 'Item', lang: 'en', key: '10000.Name', text: 'x', confirmed: true,
    })).status, 400);
  } finally {
    await panel.close();
  }
});

test('sync and compact stay within table/language scope, preview without writes, and emit logs', async () => {
  const panel = await startPanel({ invalid: true });
  try {
    await cp(resolve(import.meta.dirname, '../../native/fixtures/export_pipeline/workspace'),
      panel.root, { recursive: true, force: true });
    const unrelated = join(panel.root, 'i18n/en/Unrelated.json');
    await writeFile(unrelated, '{"keep":true}');
    const unrelatedBefore = await readFile(unrelated);
    const sync = await panel.request('/api/i18n/sync', { table: 'Item', lang: 'en' });
    assert.equal(sync.status, 200, JSON.stringify(sync));
    assert.match(sync.data.synced.at(-1), /1 张表 × 1 语言/);
    const source = JSON.parse(await readFile(join(panel.root, 'i18n/source/Item.json')));
    assert.equal(source['1001.Name'], '铁剑');
    const enPath = join(panel.root, 'i18n/en/Item.json');
    const en = JSON.parse(await readFile(enPath));
    assert.equal(en['1001.Name'].text, 'Iron Sword');
    assert.equal(en['1002.Name'].status, 'missing');
    assert.equal((await panel.request('/api/i18n/status')).data.en.tables.Item.total, 2);
    await assert.rejects(stat(join(panel.root, 'i18n/ja/Item.json')), { code: 'ENOENT' });
    assert.deepEqual(await readFile(unrelated), unrelatedBefore);
    const saved = await panel.request('/api/i18n/entry', {
      table: 'Item', lang: 'en', key: '1001.Name', text: 'Iron Sword', confirmed: true,
    });
    assert.equal(saved.status, 200, JSON.stringify(saved));
    en['9999.Name'] = { source: '已删除', text: 'Orphan', confirmed: true, status: 'orphan' };
    await writeFile(enPath, JSON.stringify(en));
    const before = await readFile(enPath);
    const dry = await panel.request('/api/i18n/compact', { table: 'Item', lang: 'en', dry_run: true });
    assert.equal(dry.status, 200, JSON.stringify(dry));
    assert.equal(dry.data.total_removed, 1);
    assert.deepEqual(dry.data.files[0].removed_keys, ['9999.Name']);
    assert.deepEqual(await readFile(enPath), before);
    const compact = await panel.request('/api/i18n/compact', { table: 'Item', lang: 'en', dry_run: false });
    assert.equal(compact.status, 200, JSON.stringify(compact));
    assert.equal(compact.data.total_removed, 1);
    assert.equal(JSON.parse(await readFile(enPath))['9999.Name'], undefined);
    assert.deepEqual(await readFile(unrelated), unrelatedBefore);
    const logs = await panel.request('/api/logs?module=i18n');
    assert.equal(logs.status, 200);
    assert.ok(logs.data.some(row => row.message.includes('sync')));
    assert.ok(logs.data.some(row => row.message.includes('entry')));
    assert.ok(logs.data.some(row => row.message.includes('compact')));
    assert.equal((await panel.request('/api/i18n/sync', { table: 'Unknown', lang: 'en' })).status, 400);
    assert.equal((await panel.request('/api/i18n/sync', { table: 'Item', lang: 'xx' })).status, 400);
    assert.deepEqual((await panel.request('/api/logs?module=i18n')).data, logs.data,
      'failed translation operations must not be logged as successful writes');
  } finally {
    await panel.close();
  }
});
