import {test, expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {startPanel} from './panel-helper.mjs';

test('healthy native first render matches the frozen Flask Web shell', async ({page}) => {
  const baseline = JSON.parse(await readFile(new URL('../../native/docs/baseline/web-static-render-compare.json', import.meta.url), 'utf8')).old;
  const panel = await startPanel();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  try {
    await page.setViewportSize({width: 1280, height: 900});
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.goto(`${panel.url}/#/export`);
    await expect(page.locator('#export-badge')).toHaveText('准备就绪');
    await expect(page.locator('#progress')).toContainText('模板待更新');
    const actual = await page.evaluate(() => {
      const q = selector => document.querySelector(selector);
      const style = selector => {
        const element = q(selector);
        const computed = getComputedStyle(element);
        return {
          display: computed.display,
          width: Math.round(element.getBoundingClientRect().width),
          height: Math.round(element.getBoundingClientRect().height),
        };
      };
      return {
        module: q('#app').dataset.module,
        projection: q('#app').dataset.projection,
        nav: [...document.querySelectorAll('.ct-sitem')].map(element => element.textContent.trim()),
        heading: q('#page-export h1')?.textContent.trim(),
        badge: q('#export-badge')?.textContent.trim(),
        buttons: [...document.querySelectorAll('#export-actions button:not([hidden])')].map(element => ({
          label: element.textContent.trim(), disabled: element.disabled,
        })),
        message: q('#export-message')?.textContent.trim(),
        progress: q('#progress')?.innerText.replace(/\s+/g, ' ').trim(),
        sidebar: style('.ct-sidebar'),
        main: style('.ct-main'),
        cssLinks: [...document.querySelectorAll('link[rel="stylesheet"]')].map(element => element.getAttribute('href')),
      };
    });
    expect({...actual, pageErrors}).toEqual(baseline);
  } finally {
    await panel.close();
  }
});
