import { test, expect } from '@playwright/test';

/**
 * Visual baseline #4 — Feature A protocol-contextual factor page.
 *
 * Reference: eng-review-2026-04-23.md §3F baseline 4; spec-addendum
 * §A "Page composition `/protocols/<slug>/factors/<factor-id>/`".
 * Must show the FactorDetailPage component composing MethodologyTable +
 * SourceList + HackFactorLinks (interactive variant via HackListSort).
 *
 * Pre-M3a status: SKIPPED. The (slug × non-green factor_score)
 * cross-product in getStaticPaths returns [] until M3a fills both
 * protocols AND factor_scores tables (the route only generates pages
 * for protocols that have been graded with non-green scores per
 * spec-addendum §F-A.1).
 */
test.describe('Feature A protocol-contextual factor page — /protocols/aave-v3/factors/RD-F-022/', () => {
  test('full-page snapshot', async ({ page }) => {
    await page.goto('/protocols/aave-v3/factors/RD-F-022/');
    await page.waitForSelector('.envelope', { state: 'visible' });
    await expect(page).toHaveScreenshot('factor-page-protocol.png', {
      fullPage: true,
    });
  });

  test('source list region', async ({ page }) => {
    await page.goto('/protocols/aave-v3/factors/RD-F-022/');
    // SourceList renders as <section class="source-list"><ul>...</ul></section>
    // post-D3 rebuild. Pre-rebuild this was `ol.srclist`.
    const sources = page.locator('section.source-list').first();
    await sources.waitFor({ state: 'visible' });
    await expect(sources).toHaveScreenshot('factor-page-protocol-sources.png');
  });
});
