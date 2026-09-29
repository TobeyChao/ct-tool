import { test, expect } from '@playwright/test';
import { rm } from 'node:fs/promises';
import { startPanel } from './panel-helper.mjs';

test('a restarted service cannot make a lost write response look like a known task', async ({ page }) => {
  const first = await startPanel({ cleanupRoot: false });
  let second;
  let posts = 0;
  try {
    expect((await first.request('/api/schema-workspace/gen-template', { table: 'Item' })).status).toBe(200);
    await page.goto(first.url);
    const oldInstance = (await first.request('/api/service')).data.instanceId;
    await page.route('**/api/service', route => route.abort('failed'));
    await page.route('**/api/export', async route => {
      posts++;
      await route.fetch();
      await route.abort('failed');
    });
    await page.locator('#export-start').click();
    await expect(page.locator('#export-message')).toHaveText('导出请求结果待核实');
    await expect(page.locator('#export-start')).toBeDisabled();
    await first.close(); // stdin EOF waits for the accepted export
    const port = Number(new URL(first.url).port);
    second = await startPanel({ rootDir: first.root, port });
    expect((await second.request('/api/service')).data.instanceId).not.toBe(oldInstance);
    await page.unroute('**/api/service');
    await page.reload();
    await expect(page.locator('#export-message')).toHaveText('导出请求结果待核实');
    await expect(page.locator('#export-start')).toBeDisabled();
    expect(posts).toBe(1);
    expect((await second.request('/api/history')).data).toHaveLength(1);
    await page.locator('#export-ack').click();
    await expect(page.locator('#export-start')).toBeEnabled();
    expect(posts).toBe(1);
  } finally {
    await second?.close();
    await first.close();
    if (!second) await rm(first.root, { recursive: true, force: true });
  }
});
