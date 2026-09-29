import { test, expect } from '@playwright/test';
import { cp, readFile, stat, unlink, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { startPanel } from './panel-helper.mjs';

async function terminal(panel) {
  for (let attempt = 0; attempt < 300; attempt++) {
    const response = await panel.request('/api/export/progress');
    if (response.data.status !== 'running') return response.data;
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  throw new Error('export did not reach a terminal state');
}

async function manyTables(panel, count) {
  const item = await panel.request('/api/schema-workspace/gen-template', { table: 'Item' });
  expect(item.status).toBe(200);
  for (let i = 1; i <= count; i++) {
    const name = `T${String(i).padStart(3, '0')}`;
    await writeFile(join(panel.root, 'config/schemas', `${name}.yaml`),
      `table: ${name}\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n  - name: Name\n    type: string\n`);
    const response = await panel.request('/api/schema-workspace/gen-template', { table: name });
    expect(response.status, name).toBe(200);
  }
}

test('export is service-owned across two tabs and refresh; explicit cancel keeps output untouched', async ({ page, context }) => {
  test.setTimeout(60000);
  const panel = await startPanel();
  let second;
  try {
    await manyTables(panel, 100);
    const ledgerBefore = await readFile(join(panel.root, 'cache/state.json')).catch(() => null);
    await page.goto(panel.url);
    await page.locator('#export-force').click();
    await expect(page.locator('#export-badge')).toHaveText('导出中');
    const first = await panel.request('/api/export/progress');
    expect(first.data.status).toBe('running');
    expect(first.data.forced).toBe(true);
    const startedAt = first.data.started_at;

    second = await context.newPage();
    await second.goto(panel.url);
    await expect(second.locator('#export-badge')).toHaveText('导出中');
    await expect(second.locator('.ct-taskbar .ct-task')).toContainText('导出');
    expect((await panel.request('/api/export', { forced: false })).status).toBe(409);
    expect((await panel.request('/api/export/progress')).data.started_at).toBe(startedAt);

    await page.reload();
    await expect(page.locator('#export-badge')).toHaveText('导出中');
    expect((await panel.request('/api/export/progress')).data.started_at).toBe(startedAt);
    await second.locator('#export-cancel').click();
    const result = await terminal(panel);
    expect(result.status).toBe('cancelled');
    expect(result.cancelled).toBe(true);
    expect(await stat(join(panel.root, 'output')).catch(() => null)).toBeNull();
    expect(await readFile(join(panel.root, 'cache/state.json')).catch(() => null)).toEqual(ledgerBefore);
    await expect(page.locator('#export-badge')).toHaveText('已取消');
  } finally {
    await second?.close();
    await panel.close();
  }
});

test('lost export response reattaches to the one real task without replaying POST', async ({ page }) => {
  const panel = await startPanel();
  let posts = 0;
  try {
    expect((await panel.request('/api/schema-workspace/gen-template', { table: 'Item' })).status).toBe(200);
    await page.goto(panel.url);
    await page.route('**/api/export', async route => {
      posts++;
      await route.fetch(); // The native service accepted the write.
      await route.abort('failed'); // Only the browser loses its response.
    });
    await page.locator('#export-start').click();
    await expect(page.locator('#export-badge')).toContainText('成功');
    expect(posts).toBe(1);
    expect((await panel.request('/api/history')).data).toHaveLength(1);
    await page.reload();
    await expect(page.locator('#export-badge')).toContainText('成功');
    expect(posts).toBe(1);
  } finally {
    await panel.close();
  }
});

test('HTTP timeout after native acceptance never retries the write', async ({ page }) => {
  const panel = await startPanel();
  let posts = 0;
  try {
    expect((await panel.request('/api/schema-workspace/gen-template', { table: 'Item' })).status).toBe(200);
    await page.goto(panel.url);
    await page.route('**/api/export', async route => {
      posts++;
      const response = await route.fetch();
      await new Promise(resolve => setTimeout(resolve, 120));
      await route.fulfill({ response }).catch(() => {});
    });
    const result = await page.evaluate(async () => {
      const { api } = await import('/static/js/core/api.js');
      try {
        await api('/api/export', { method: 'POST', body: '{}', timeoutMs: 20 });
        return { unexpectedSuccess: true };
      } catch (error) {
        return { outcomeUnknown: error.outcomeUnknown, message: error.message };
      }
    });
    expect(result.outcomeUnknown).toBe(true);
    expect(result.message).toContain('超时');
    expect((await terminal(panel)).status).toBe('done');
    expect(posts).toBe(1);
    expect((await panel.request('/api/history')).data).toHaveLength(1);
  } finally {
    await panel.close();
  }
});

test('unverifiable write stays marked unknown across refresh until the service is reachable', async ({ page }) => {
  const panel = await startPanel();
  let posts = 0;
  try {
    expect((await panel.request('/api/schema-workspace/gen-template', { table: 'Item' })).status).toBe(200);
    await page.goto(panel.url);
    await page.route('**/api/service', route => route.abort('failed'));
    await page.route('**/api/export', async route => {
      posts++;
      await route.fetch();
      await route.abort('failed');
    });
    await page.locator('#export-start').click();
    await expect(page.locator('#export-message')).toHaveText('导出请求结果待核实');
    await expect(page.locator('#export-start')).toBeDisabled();
    await page.reload();
    await expect(page.locator('#export-message')).toHaveText('导出请求结果待核实');
    await expect(page.locator('#export-start')).toBeDisabled();
    expect(posts).toBe(1);
    await page.unroute('**/api/service');
    await page.locator('#export-verify').click();
    await expect(page.locator('#export-badge')).toContainText('成功');
    expect(posts).toBe(1);
    expect((await panel.request('/api/history')).data).toHaveLength(1);
  } finally {
    await panel.close();
  }
});

test('forced build and validation issues stay queryable in the export page', async ({ page }) => {
  const panel = await startPanel({ invalid: true });
  try {
    const source = resolve(import.meta.dirname, '../../native/fixtures/export_pipeline/workspace');
    await cp(source, panel.root, { recursive: true, force: true });
    await page.goto(panel.url);
    await page.locator('#export-start').click();
    await expect(page.locator('#export-badge')).toContainText('成功');
    const cold = await stat(join(panel.root, 'output/binary/data_en.bin'), { bigint: true });
    await page.locator('#export-start').click();
    await expect(page.locator('#export-badge')).toContainText('成功');
    const warm = await stat(join(panel.root, 'output/binary/data_en.bin'), { bigint: true });
    expect(warm.mtimeNs).toBe(cold.mtimeNs);
    await page.locator('#export-force').click();
    await expect(page.locator('#export-badge')).toContainText('成功');
    expect((await panel.request('/api/export/progress')).data.forced).toBe(true);
    await expect(page.locator('.ct-prog-cell')).toHaveCount(5);
    await expect(page.locator('.ct-prog-cell.done')).toHaveCount(5);
    await expect(page.locator('#export-context-result')).toContainText('成功');
    await page.reload();
    await expect(page.locator('#export-context-result')).toContainText('成功');

    await writeFile(join(panel.root, 'config/types/rarity.yaml'),
      'kind: enum\nname: Rarity\nvalues:\n  - name: Epic\n');
    const output = await readFile(join(panel.root, 'output/binary/data_en.bin'));
    await page.locator('#export-start').click();
    await expect(page.locator('#export-badge')).toHaveText('导出中止');
    const failed = (await panel.request('/api/export/progress')).data;
    expect(failed.status).toBe('error');
    expect(failed.step_name).toBe('解析校验');
    expect(failed.errors).toHaveLength(2);
    await expect(page.locator('.ct-export-errors .ct-error-inline')).toHaveCount(2);
    expect(await readFile(join(panel.root, 'output/binary/data_en.bin'))).toEqual(output);
    await page.reload();
    await expect(page.locator('.ct-export-errors .ct-error-inline')).toHaveCount(2);
    await expect(page.locator('.ct-task-close')).toBeVisible();
    await page.locator('.ct-task-close').click();
    await expect(page.locator('.ct-taskbar .ct-task')).toHaveCount(0);
    await page.reload();
    await expect(page.locator('.ct-taskbar .ct-task')).toHaveCount(0);
    await expect(page.locator('.ct-export-errors .ct-error-inline')).toHaveCount(2);
  } finally {
    await panel.close();
  }
});

test('failed export messages with a long workspace path stay inside the context card',async({page})=>{
  const panel=await startPanel();
  try{
    await page.setViewportSize({width:1280,height:720});
    await page.goto(panel.url);
    await expect(page.locator('#export-start')).toBeEnabled();
    await unlink(join(panel.root,'config/global.yaml'));
    await page.locator('#export-start').click();
    await expect(page.locator('#export-badge')).toHaveText('导出中止');
    await expect(page.locator('#export-context-result')).toContainText('不存在');
    const fits=await page.evaluate(()=>{
      const measured=selector=>{const range=document.createRange();range.selectNodeContents(document.querySelector(selector));return range.getBoundingClientRect();};
      const card=document.querySelector('#page-export .ct-export-context').getBoundingClientRect();
      const section=document.querySelector('#page-export .ct-workbench-section').getBoundingClientRect();
      return {result:measured('#export-context-result').right<=card.right+1,message:measured('#export-message').right<=section.right+1};
    });
    expect(fits).toEqual({result:true,message:true});
  }finally{await panel.close();}
});

test('failed task dismiss shows a toast and task card returns after polling',async({page})=>{
  const panel=await startPanel();
  try{
    await page.setViewportSize({width:1280,height:720});
    await page.route('**/api/tasks/*/dismiss',route=>route.abort());
    await page.goto(panel.url);
    await expect(page.locator('#export-start')).toBeEnabled();
    await unlink(join(panel.root,'config/global.yaml'));
    await page.locator('#export-start').click();
    await expect(page.locator('#export-badge')).toHaveText('导出中止');
    const close=page.locator('#ct-taskbar .ct-task-close');
    await expect(close).toBeVisible();
    await close.click();
    await expect(page.locator('#ct-toast')).toContainText('关闭失败');
    await expect(close).toBeVisible({timeout:10000});
  }finally{await panel.close();}
});
