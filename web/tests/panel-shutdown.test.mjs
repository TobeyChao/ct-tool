import { test } from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { readFile, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { startPanel } from './panel-helper.mjs';

for (const shutdown of [
  { name: 'SIGINT', skip: process.platform === 'win32', trigger: child => assert.equal(child.kill('SIGINT'), true) },
  { name: 'stdin EOF', skip: false, trigger: child => child.stdin.end() },
]) test(`${shutdown.name} waits for an accepted export to publish a complete file set and restart gets a new instance`,
  { skip: shutdown.skip, timeout: 60000 }, async () => {
    const panel = await startPanel({ cleanupRoot: false });
    let restarted;
    try {
      for (let i = 0; i < 80; i++) {
        const table = `T${String(i).padStart(3, '0')}`;
        await writeFile(join(panel.root, 'config/schemas', `${table}.yaml`),
          `table: ${table}\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: Name\n    type: string\n`);
        assert.equal((await panel.request('/api/schema-workspace/gen-template', { table })).status, 200);
      }
      assert.equal((await panel.request('/api/schema-workspace/gen-template', { table: 'Item' })).status, 200);
      const firstInstance = (await panel.request('/api/service')).data.instanceId;
      const started = await panel.request('/api/export', { forced: true });
      assert.equal(started.status, 200);
      assert.equal(started.data.status, 'running');
      const exited = once(panel.child, 'exit');
      shutdown.trigger(panel.child);
      const [code, signal] = await exited;
      assert.equal(code, 0, `panel must exit cleanly after publishing, signal=${signal}`);
      assert.equal(signal, null);
      for (const table of ['Item', ...Array.from({ length: 80 }, (_, i) => `T${String(i).padStart(3, '0')}`)]) {
        const basename = table.toLowerCase();
        for (const lang of ['zh', 'en']) {
          assert.ok((await stat(join(panel.root, 'output/json', `${basename}_${lang}.json`))).size > 0);
        }
        assert.ok((await stat(join(panel.root, 'output/fbs', `${basename}.fbs`))).size > 0);
        assert.ok((await stat(join(panel.root, 'output/generated/csharp', `${basename}accessor.cs`))).size > 0);
        assert.ok((await stat(join(panel.root, 'output/generated/lua', `${basename}accessor.lua`))).size > 0);
      }
      for (const lang of ['zh', 'en']) {
        assert.ok((await stat(join(panel.root, 'output/binary', `data_${lang}.bin`))).size > 0);
      }
      const ledger = JSON.parse(await readFile(join(panel.root, 'cache/state.json')));
      assert.equal(Object.keys(ledger.excel_hashes).length, 81);
      assert.deepEqual(Object.keys(ledger.bundles).sort(), ['en', 'zh']);
      assert.equal(await stat(join(panel.root, '.ct/export-publication.json')).catch(() => null), null);
      const history = JSON.parse(await readFile(join(panel.root, 'cache/history.json')));
      assert.equal(history.entries.length, 1);
      restarted = await startPanel({ rootDir: panel.root });
      const nextInstance = (await restarted.request('/api/service')).data.instanceId;
      assert.notEqual(nextInstance, firstInstance);
      assert.equal((await restarted.request('/api/history')).data.length, 1);
    } finally {
      await restarted?.close();
      await panel.close();
      if (!restarted) await rm(panel.root, { recursive: true, force: true });
    }
  });
