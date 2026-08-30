/** Focused copy checks for the Data & API page. */
import { test, expect } from '@playwright/test';

test.describe('Data & API page (/data/)', () => {
  test('does not advertise unpublished CSV endpoints', async ({ page }) => {
    await page.goto('/data/');
    await expect(page.getByText('Planned; no CSV files are published yet.')).toBeVisible();
    await expect(page.locator('body')).not.toContainText('/protocols.csv');
    await expect(page.locator('body')).not.toContainText('/factors.csv');
  });

  test('serves the canonical license label in the default OG image', async ({ request }) => {
    const response = await request.get('/og/default.svg');
    expect(response.ok()).toBe(true);
    const svg = await response.text();
    expect(svg).toContain('CC BY 4.0 · MIT');
    expect(svg).not.toContain('CC-BY 4.0');
  });
});
