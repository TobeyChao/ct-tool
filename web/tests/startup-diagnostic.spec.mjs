import {test, expect} from '@playwright/test';
import {startPanel} from './panel-helper.mjs';
import {mkdir, writeFile} from 'node:fs/promises';
import {join} from 'node:path';

test('invalid workspace keeps the panel reachable and export disabled until repaired', async ({page}) => {
  const panel = await startPanel({invalid: true});
  try {
    const workspace = await panel.request('/api/workspace');
    expect(workspace.status).toBe(400);
    expect(workspace.ok).toBe(false);

    await page.goto(panel.url);
    await expect(page.locator('#export-workspace-error')).toBeVisible();
    await expect(page.locator('#export-workspace-error')).not.toBeEmpty();
    await expect(page.locator('#export-badge')).toHaveText('工作区不可用');
    await expect(page.locator('#progress')).toContainText('工作区未加载');
    await expect(page.locator('#export-start')).toBeDisabled();
    await expect(page.locator('#export-force')).toBeDisabled();

    await mkdir(join(panel.root, 'config'), {recursive: true});
    await writeFile(join(panel.root, 'config/global.yaml'), 'primary_lang: [invalid\n');
    await page.reload();
    await expect(page.locator('#export-workspace-error')).toBeVisible();
    await expect(page.locator('#export-start')).toBeDisabled();
    expect((await panel.request('/api/workspace')).status).toBe(400);

    await writeFile(join(panel.root, 'config/global.yaml'), 'primary_lang: zh\nsecondary_langs: [en]\n');
    await page.locator('.ct-sitem[data-module="logs"]').click();
    await page.locator('.ct-sitem[data-module="export"]').click();
    await expect(page.locator('#export-workspace-error')).toBeHidden();
    await expect(page.locator('#export-start')).toBeEnabled();
    expect((await panel.request('/api/workspace')).status).toBe(200);
  } finally {
    await panel.close();
  }
});
