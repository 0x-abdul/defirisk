import { test, expect } from '@playwright/test';

/**
 * Visual baseline #5 — Feature A global factor page.
 *
 * Reference: eng-review-2026-04-23.md §3F baseline 5; spec-addendum
 * §A "Page composition `/factors/<factor-id>/`".
 *
 * Pre-M3a status: this is the ONLY one of the 5 §3F reference pages
 * that has a built dist target without M3a data — every factor page
 * generates from listFactors() (184 paths) and renders the methodology
 * + empty per-protocol scoring + 0 linked hacks. The empty-state
 * baseline is captured first; it will be refreshed via
 * `npm run test:visual:update` once M3a fills factor scores + hack
 * linkage.
 */
test.describe('Feature A global factor page — /factors/RD-F-022/', () => {
  test('full-page snapshot', async ({ page }) => {
    await page.goto('/factors/RD-F-022/');
    // Wait for fonts + critical chrome (masthead, sections, envelope footer)
    await page.waitForSelector('.envelope', { state: 'visible' });
    await expect(page).toHaveScreenshot('factor-page-global.png', {
      fullPage: true,
    });
  });

  test('above-the-fold snapshot', async ({ page }) => {
    await page.goto('/factors/RD-F-022/');
    await page.waitForSelector('.envelope', { state: 'visible' });
    await expect(page).toHaveScreenshot('factor-page-global-fold.png', {
      fullPage: false,
    });
  });
});
