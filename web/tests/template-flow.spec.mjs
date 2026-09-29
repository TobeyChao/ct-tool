import { test, expect } from '@playwright/test';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { startPanel } from './panel-helper.mjs';

test('export page generates multiple missing templates one at a time and refreshes status', async ({ page }) => {
  const panel = await startPanel();
  try {
    await writeFile(join(panel.root, 'config/schemas/Quest.yaml'),
      'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n');
    await page.goto(panel.url);
    await expect(page.locator('#export-context-drifted')).toContainText('2');
    await page.locator('#export-regenerate-template').click();
    await expect(page.locator('.ct-dialog-mask.open')).toContainText('Item');
    await expect(page.locator('.ct-dialog-mask.open')).toContainText('Quest');
    await page.locator('.ct-dialog-mask.open [data-confirm]').click();
    await expect(page.locator('#export-regenerate-template')).toHaveCount(0);
    for (const table of ['Item', 'Quest']) {
      expect((await stat(join(panel.root, `excel/${table}.xlsx`))).size).toBeGreaterThan(0);
    }
    expect((await panel.request('/api/workspace')).data.status.missing).toEqual([]);
    await expect(page.locator('#export-context-drifted')).toHaveText('无');
  } finally {
    await panel.close();
  }
});

test('drift refresh explains data migration and only runs after explicit confirmation', async ({ page }) => {
  const panel = await startPanel();
  try {
    expect((await panel.request('/api/schema-workspace/gen-template', { table: 'Item' })).status).toBe(200);
    const workbook = join(panel.root, 'excel/Item.xlsx');
    const before = await readFile(workbook);
    const schema = join(panel.root, 'config/schemas/Item.yaml');
    await writeFile(schema, `${await readFile(schema, 'utf8')}  - name: Weight\n    type: float\n`);
    await page.goto(panel.url);
    await expect(page.locator('#export-context-drifted')).toContainText('1');
    await page.locator('#export-regenerate-template').click();
    await expect(page.locator('.ct-dialog-mask.open')).toContainText('附加工作表等非数据区内容不保留');
    expect(await readFile(workbook)).toEqual(before);
    await page.locator('.ct-dialog-mask.open [data-confirm]').click();
    await expect(page.locator('#export-context-drifted')).toHaveText('无');
    const manifest = JSON.parse(await readFile(join(panel.root, 'excel/layout_manifests/Item.json')));
    expect(manifest.columns.map(column => column.leaf)).toEqual(['Id', 'Name', 'Weight']);
    expect(await readFile(workbook)).not.toEqual(before);
    await expect(page.locator('#export-regenerate-template')).toHaveCount(0);
  } finally {
    await panel.close();
  }
});

test('new table offers template generation only after YAML save and across refresh', async ({ page }) => {
  const panel = await startPanel();
  try {
    await page.goto(panel.url);
    await page.locator('.ct-sitem[data-module="schema"]').click();
    await page.locator('.ct-workspace-layout').waitFor();
    await page.locator('#head-create-resource').click();
    await page.locator('[data-cr-name]').fill('Quest');
    await page.locator('[data-submit]').click();
    await expect(page.locator('#template-unsaved')).toContainText('保存后才能生成模板');
    await expect(page.locator('.banner-gen-template[data-table="Quest"]')).toHaveCount(0);
    await page.locator('#ct-draft-save').click();
    await expect(page.locator('.banner-gen-template[data-table="Quest"]')).toBeVisible();
    await expect.poll(() => readFile(join(panel.root, 'config/schemas/Quest.yaml'), 'utf8')).toContain('Quest');
    await expect.poll(() => stat(join(panel.root, 'excel/Quest.xlsx')).catch(() => null)).toBeNull();
    await page.reload();
    await page.locator('.ct-sitem[data-module="schema"]').click();
    await expect(page.locator('.banner-gen-template[data-table="Quest"]')).toBeVisible();
    await page.locator('.banner-gen-template[data-table="Quest"]').click();
    await expect(page.locator('.banner-gen-template[data-table="Quest"]')).toHaveCount(0);
    expect((await stat(join(panel.root, 'excel/Quest.xlsx'))).size).toBeGreaterThan(0);
    await expect.poll(() => stat(join(panel.root, 'output')).catch(() => null)).toBeNull();
  } finally {
    await panel.close();
  }
});
