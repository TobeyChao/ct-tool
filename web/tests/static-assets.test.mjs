import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {checkStaticAssets} from '../tools/check-static-assets.mjs';
import {startPanel} from './panel-helper.mjs';

test('the complete old Web asset tree and module imports are preserved', async () => {
  assert.deepEqual(await checkStaticAssets(), {files: 23, adapted: 8});
});

test('the native panel serves every migrated asset with its expected media type', async () => {
  const manifest = JSON.parse(await readFile(new URL('../static-manifest.json', import.meta.url), 'utf8'));
  const panel = await startPanel();
  try {
    for (const item of manifest.files) {
      const response = await fetch(`${panel.url}/static/${item.path}`);
      assert.equal(response.status, 200, item.path);
      const type = item.path.endsWith('.js') ? 'text/javascript'
        : item.path.endsWith('.css') ? 'text/css' : 'text/html';
      assert.ok(response.headers.get('content-type')?.startsWith(type), item.path);
      assert.ok((await response.arrayBuffer()).byteLength > 0, item.path);
    }
  } finally {
    await panel.close();
  }
});
