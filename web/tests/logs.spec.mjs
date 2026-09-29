import { test, expect } from '@playwright/test';
import { startPanel } from './panel-helper.mjs';

test('native logs filter by module, level and search; polling preserves reading position', async ({ page }) => {
  const panel = await startPanel();
  try {
    expect((await panel.request('/api/schema-workspace/gen-template', { table: 'Item' })).status).toBe(200);
    expect((await panel.request('/api/schema-workspace/gen-template', { table: 'Unknown' })).status).toBe(404);
    expect((await panel.request('/api/i18n/sync', { table: 'Item', lang: 'en' })).status).toBe(200);
    await page.goto(panel.url);
    await page.locator('.ct-sitem[data-module="logs"]').click();
    await expect(page.locator('#log-modules [data-module]')).toHaveCount(6);
    expect(await page.locator('#log-modules [data-module]').evaluateAll(rows => rows.map(row => row.dataset.module)))
      .toEqual(['all', '导出', '校验', 'i18n', '模板', '系统']);
    await expect(page.locator('#log-levels [data-level]')).toHaveCount(4);
    await page.locator('#log-modules [data-module="模板"]').click();
    await expect(page.locator('#log-content tbody tr')).toHaveCount(2);
    await page.locator('#log-levels [data-level="ERROR"]').click();
    await expect(page.locator('#log-content tbody tr')).toHaveCount(1);
    await expect(page.locator('#log-content')).toContainText('Unknown');
    await page.locator('#log-search').fill('no-match');
    await expect(page.locator('#log-content .ct-empty-title')).toHaveText('没有匹配的日志');
    await page.locator('#logs-clear-filters').click();
    await expect(page.locator('#log-content tbody tr')).toHaveCount(4); // service, template x2, i18n

    for (let i = 0; i < 45; i++) {
      expect((await panel.request('/api/schema-workspace/gen-template', { table: `Missing${i}` })).status).toBe(404);
    }
    await expect(page.locator('#log-content tbody tr')).toHaveCount(49, { timeout: 10000 });
    const viewport = page.locator('.ct-log-table-wrap');
    await viewport.evaluate(element => { element.scrollTop = 0; });
    await expect(page.locator('#logs-jump-bottom')).toBeVisible();
    await viewport.evaluate(element => { element.dataset.identity = 'stable'; });
    await page.waitForTimeout(1500); // one unchanged poll must leave the viewport in place
    await expect(viewport).toHaveAttribute('data-identity', 'stable');
    expect(await viewport.evaluate(element => element.scrollTop)).toBe(0);
    expect((await panel.request('/api/schema-workspace/gen-template', { table: 'LastMissing' })).status).toBe(404);
    expect((await panel.request('/api/logs')).data).toHaveLength(50);
    await expect(page.locator('#log-content tbody tr')).toHaveCount(50, { timeout: 10000 });
    expect(await viewport.evaluate(element => element.scrollTop)).toBe(0);
    await page.locator('#logs-jump-bottom').click();
    await expect(page.locator('#logs-jump-bottom')).toBeHidden();
    const all = await panel.request('/api/logs');
    expect(all.data).toHaveLength(50);
    expect(all.data.filter(row => row.message.includes('LastMissing'))).toHaveLength(1);
  } finally {
    await panel.close();
  }
});
