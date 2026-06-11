import { test, expect } from '@playwright/test';

/**
 * Visual baseline #2 — Aave v3 detail with active-incident banner.
 *
 * Reference: eng-review-2026-04-23.md §3F baseline 2; CEO condition 5C
 * (PD-033 banner mechanism). The baseline must show the IncidentBanner
 * rendering above the 13-cat grid.
 *
 * Pre-M3a status: SKIPPED. /protocols/aave-v3/ does not exist until M3a
 * fills the protocols table AND M3a/M3c populate active_incidents with
 * a row pointing at aave-v3 (so the banner has something to render).
 */
test.describe('Aave v3 detail with incident banner — /protocols/aave-v3/', () => {
  test('full-page snapshot', async ({ page }) => {
    await page.goto('/protocols/aave-v3/');
    await page.waitForSelector('.envelope', { state: 'visible' });
    await expect(page).toHaveScreenshot('aave-v3.png', { fullPage: true });
  });

  test('incident banner region', async ({ page }) => {
    await page.goto('/protocols/aave-v3/');
    const banner = page.getByRole('alert').or(page.getByRole('status')).first();
    await banner.waitFor({ state: 'visible' });
    await expect(banner).toHaveScreenshot('aave-v3-banner.png');
  });
});
