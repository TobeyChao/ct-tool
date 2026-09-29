import { test, expect } from '@playwright/test';
import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { startPanel } from './panel-helper.mjs';

test('translation editor filters non-i18n tables, saves long text, and clears a translation', async ({ page }) => {
  const panel = await startPanel();
  try {
    await writeFile(join(panel.root, 'config/schemas/Quest.yaml'),
      'table: Quest\nprimary: Id\nfields:\n  - name: Id\n    type: int32\n');
    await mkdir(join(panel.root, 'i18n/source'), { recursive: true });
    await mkdir(join(panel.root, 'i18n/en'), { recursive: true });
    const source = { '1.Name': '铁剑', '2.Name': '木盾', '3.Name': '长篇原文' };
    await writeFile(join(panel.root, 'i18n/source/Item.json'), JSON.stringify(source));
    const langPath = join(panel.root, 'i18n/en/Item.json');
    await writeFile(langPath, JSON.stringify({
      '1.Name': { source: source['1.Name'], text: 'Sword', confirmed: true, status: 'translated' },
      '2.Name': { source: '旧原文', text: 'Shield', confirmed: true, status: 'translated' },
      '3.Name': { source: source['3.Name'], text: '', confirmed: false, status: 'missing' },
      '4.Name': { source: '已删除', text: 'Orphan', confirmed: true, status: 'orphan' },
    }));
    await page.goto(panel.url);
    await page.locator('.ct-sitem[data-module="i18n"]').click();
    await expect(page.locator('.ct-current-table')).toHaveText('Item');
    await page.locator('#i18n-pick').click();
    await expect(page.locator('.ct-dialog-mask.open [data-pick-table="Item"]')).toBeVisible();
    await expect(page.locator('.ct-dialog-mask.open [data-pick-table="Quest"]')).toHaveCount(0);
    await page.locator('.ct-dialog-mask.open [data-pick-search]').fill('not-a-table');
    await expect(page.locator('.ct-dialog-mask.open .ct-empty-title')).toHaveText('没有匹配的表');
    await page.locator('.ct-dialog-mask.open [data-pick-search]').fill('item');
    await expect(page.locator('.ct-dialog-mask.open [data-pick-table="Item"]')).toBeVisible();
    await page.locator('.ct-dialog-mask.open [data-pick-close]').click();
    await expect(page.locator('.ct-i18n-table tbody tr')).toHaveCount(4);
    await expect(page.locator('.ct-row-ops [data-key="2.Name"]')).toHaveText('确认并保存');
    await expect(page.locator('.ct-i18n-table tbody tr').last().locator('.ct-badge')).toHaveText('无主');
    const longText = 'Long translation 🙂\n'.repeat(700);
    await page.locator('.ct-trans-expand[data-key="3.Name"]').click();
    await page.locator('.ct-dialog-mask.open [data-full-trans]').fill('cancelled draft');
    await page.locator('.ct-dialog-mask.open [data-full-cancel]').click();
    expect(JSON.parse(await readFile(langPath))['3.Name'].text).toBe('');
    await page.locator('.ct-trans-expand[data-key="3.Name"]').click();
    await page.locator('.ct-dialog-mask.open [data-full-trans]').fill(longText);
    await page.locator('.ct-dialog-mask.open [data-full-save]').click();
    await expect.poll(async () => JSON.parse(await readFile(langPath))['3.Name'].text).toBe(longText);
    await expect(page.locator('.ct-row-ops [data-key="3.Name"]')).toHaveText('保存');
    await page.locator('.trans-preview[data-expand-key="1.Name"]').click();
    await page.locator('textarea.is-area[data-key="1.Name"]').fill('');
    await page.locator('.ct-row-ops [data-key="1.Name"]').click();
    await expect.poll(async () => JSON.parse(await readFile(langPath))['1.Name'].text).toBe('');
    await expect(page.locator('.ct-row-ops [data-key="1.Name"]')).toHaveText('保存');
    expect((await panel.request('/api/i18n/entries?table=Item&lang=en')).data.find(entry => entry.key === '1.Name').status).toBe('missing');
  } finally {
    await panel.close();
  }
});

test('sync refreshes visible entries and compact requires preview confirmation', async ({ page }) => {
  const panel = await startPanel({ invalid: true });
  try {
    await cp(resolve(import.meta.dirname, '../../native/fixtures/export_pipeline/workspace'),
      panel.root, { recursive: true, force: true });
    await rm(join(panel.root, 'i18n/en/Item.json'));
    await page.goto(panel.url);
    await page.locator('.ct-sitem[data-module="i18n"]').click();
    await expect(page.locator('#page-i18n .ct-empty-title')).toHaveText('暂无翻译条目');
    await page.locator('#i18n-sync').click();
    await expect(page.locator('.ct-i18n-table tbody tr')).toHaveCount(2);
    await page.locator('#i18n-progress').click();
    await expect(page.locator('.ct-dialog-mask.open')).toContainText('en');
    await page.locator('.ct-dialog-mask.open [data-progress-close]').click();
    const langPath = join(panel.root, 'i18n/en/Item.json');
    const entries = JSON.parse(await readFile(langPath));
    entries['9999.Name'] = { source: '已删除', text: 'Orphan', confirmed: true, status: 'orphan' };
    await writeFile(langPath, JSON.stringify(entries));
    await page.reload();
    await page.locator('.ct-sitem[data-module="i18n"]').click();
    await expect(page.locator('#i18n-compact')).toBeEnabled();
    await page.locator('#i18n-compact').click();
    await expect(page.locator('.ct-dialog-mask.open')).toContainText('9999.Name');
    expect(JSON.parse(await readFile(langPath))['9999.Name']).toBeDefined();
    await page.locator('.ct-dialog-mask.open [data-cancel-compact]').click();
    expect(JSON.parse(await readFile(langPath))['9999.Name']).toBeDefined();
    await page.locator('#i18n-compact').click();
    await page.locator('.ct-dialog-mask.open [data-confirm-compact]').click();
    await expect(page.locator('#i18n-compact')).toBeDisabled();
    expect(JSON.parse(await readFile(langPath))['9999.Name']).toBeUndefined();
    await expect(page.locator('.ct-i18n-table tbody tr')).toHaveCount(2);
  } finally {
    await panel.close();
  }
});
