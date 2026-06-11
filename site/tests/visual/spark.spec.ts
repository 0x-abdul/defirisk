import { test, expect } from '@playwright/test';

/**
 * Visual baseline #1 — Spark protocol detail (clean A+CLEAN).
 *
 * Reference: eng-review-2026-04-23.md §3F baseline 1.
 *
 * Pre-M3a status: SKIPPED. /protocols/spark/ does not exist until M3a
 * fills the protocols table; getStaticPaths returns 0 paths today.
 * Activate by removing the `test.skip()` once `npm run build` produces
 * dist/protocols/spark/index.html, then run
 * `npm run test:visual:update` to capture the initial baseline.
 */
test.describe('Spark protocol detail — /protocols/spark/', () => {
  test('full-page snapshot', async ({ page }) => {
    await page.goto('/protocols/spark/');
    await page.waitForSelector('.envelope', { state: 'visible' });
    await expect(page).toHaveScreenshot('spark.png', { fullPage: true });
  });

  test('above-the-fold snapshot', async ({ page }) => {
    await page.goto('/protocols/spark/');
    await page.waitForSelector('.envelope', { state: 'visible' });
    await expect(page).toHaveScreenshot('spark-fold.png', { fullPage: false });
  });
});
