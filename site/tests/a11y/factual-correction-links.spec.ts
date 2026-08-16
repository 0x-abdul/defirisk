import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const A11Y_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] as const;
const FACTUAL_CORRECTION_URL =
  'https://github.com/0x-abdul/defirisk/issues/new?template=factual-correction.md';
const PROTOCOL = 'polymarket';
const FACTOR = 'RD-F-001';

const actionPages = [
  { path: `/protocols/${PROTOCOL}/`, name: 'Correct a fact' },
  {
    path: `/protocols/${PROTOCOL}/factors/${FACTOR}/`,
    name: 'Open a factual correction',
  },
  {
    path: `/protocols/${PROTOCOL}/surfaces/default/factors/${FACTOR}/`,
    name: 'Open a factual correction',
  },
  { path: '/about/', name: 'Factual Correction' },
] as const;

async function enableHighContrast(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      localStorage.setItem('rd-prefer-contrast', '1');
    } catch {
      // Ignore storage-disabled browser contexts.
    }
  });
}

for (const actionPage of actionPages) {
  test.describe(`Factual-correction action (${actionPage.path})`, () => {
    test.beforeEach(async ({ page }) => {
      await enableHighContrast(page);
    });

    for (const viewport of [
      { name: 'desktop', width: 1280, height: 800 },
      { name: 'mobile', width: 375, height: 812 },
    ] as const) {
      test(`${viewport.name}: accessible, focusable, and contained`, async ({ page }) => {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        const response = await page.goto(actionPage.path, { waitUntil: 'domcontentloaded' });
        expect(response?.status()).toBe(200);

        const link = page
          .locator('main#main')
          .getByRole('link', { name: actionPage.name, exact: true });
        await expect(link).toHaveAttribute('href', FACTUAL_CORRECTION_URL);
        await link.focus();
        await expect(link).toBeFocused();

        const results = await new AxeBuilder({ page }).withTags([...A11Y_TAGS]).analyze();
        const violations = results.violations.filter(
          (violation) => violation.impact === 'serious' || violation.impact === 'critical',
        );
        expect(
          violations,
          violations.map((violation) => `${violation.id}: ${violation.description}`).join('\n'),
        ).toEqual([]);

        const overflow = await page.evaluate(() => ({
          document: document.documentElement.scrollWidth > window.innerWidth,
          body: document.body.scrollWidth > window.innerWidth,
        }));
        expect(overflow).toEqual({ document: false, body: false });
      });
    }
  });
}

test('footer link has an accessible name and receives keyboard focus', async ({ page }) => {
  await enableHighContrast(page);
  await page.setViewportSize({ width: 375, height: 812 });
  const response = await page.goto('/about/', { waitUntil: 'domcontentloaded' });
  expect(response?.status()).toBe(200);

  const link = page
    .locator('footer')
    .getByRole('link', { name: 'Factual correction', exact: true });
  await expect(link).toHaveAttribute('href', FACTUAL_CORRECTION_URL);
  await link.focus();
  await expect(link).toBeFocused();
});
