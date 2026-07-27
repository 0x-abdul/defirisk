import { expect, test } from '@playwright/test';

const FAMILY = '/protocols/fixture-family/';
const HEADER_FAMILY = '/protocols/fixture-header-family/';

async function requireFixture(page: import('@playwright/test').Page, path: string) {
  const response = await page.goto(path, { waitUntil: 'networkidle' });
  if (!response || response.status() === 404) {
    test.skip(true, 'Synthetic family fixture is not installed for this build');
  }
  await page.locator('#family-surface-panel').waitFor();
}

test.describe('Family factor design alignment', () => {
  test('queryless greatest-TVL surface at desktop', async ({ page }) => {
    await requireFixture(page, FAMILY);
    await expect(page).toHaveScreenshot('family-queryless-desktop.png');
  });

  test('graded and capped surface at desktop', async ({ page }) => {
    await requireFixture(page, HEADER_FAMILY);
    await expect(page).toHaveScreenshot('family-graded-desktop.png');
  });

  for (const width of [320, 375]) {
    test(`queryless category header at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await requireFixture(page, FAMILY);
      await expect(page.locator('#cat-1 summary')).toHaveScreenshot(`family-category-${width}.png`);
    });

    test(`Overview comparison at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await requireFixture(page, `${FAMILY}?view=overview`);
      await expect(page.locator('#family-surface-panel')).toHaveScreenshot(
        `family-overview-${width}.png`
      );
    });

    test(`complete category strip at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await requireFixture(page, FAMILY);
      const categoryStrip = page.getByRole('link', { name: /category:/ }).first().locator('..');
      await expect(categoryStrip).toHaveScreenshot(`family-category-strip-${width}.png`);
    });
  }

  test('deployment picker at 320px', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 812 });
    await requireFixture(page, FAMILY);
    await page.getByRole('button', { name: /All deployments/ }).click();
    await expect(page.getByRole('dialog', { name: 'Select deployment' })).toHaveScreenshot(
      'family-deployment-picker-320.png'
    );
  });
});
