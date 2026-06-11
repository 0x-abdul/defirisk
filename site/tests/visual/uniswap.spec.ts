import { test, expect } from '@playwright/test';

/**
 * Visual baseline #3 — Uniswap (v2 + v3) combined-slug multi-deployment tabs.
 *
 * Reference: eng-review-2026-04-23.md §3F baseline 3; CEO condition 5A
 * (per-deployment badging). The baseline must show DeploymentTabs
 * rendering above the 13-cat grid for a multi-deployment protocol.
 *
 * Per PD-040 (2026-05-12), uniswap-v3 was refactored into a combined `uniswap`
 * slug covering v2 + v3 (Balancer-style merge). URL changed from
 * /protocols/uniswap-v3/ to /protocols/uniswap/.
 */
test.describe('Uniswap combined v2+v3 multi-deployment — /protocols/uniswap/', () => {
  test('full-page snapshot', async ({ page }) => {
    await page.goto('/protocols/uniswap/');
    await page.waitForSelector('.envelope', { state: 'visible' });
    await expect(page).toHaveScreenshot('uniswap.png', { fullPage: true });
  });

  test('deployment tabs region', async ({ page }) => {
    await page.goto('/protocols/uniswap/');
    const tabs = page.getByRole('tablist').first();
    await tabs.waitFor({ state: 'visible' });
    await expect(tabs).toHaveScreenshot('uniswap-tabs.png');
  });
});
