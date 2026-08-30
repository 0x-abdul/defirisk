import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const A11Y_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] as const;

test.describe('/factors filter rail accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try {
        localStorage.setItem('rd-prefer-contrast', '1');
      } catch {
        /* ignore */
      }
    });
  });

  for (const width of [375, 1280] as const) {
    test(`has no serious or critical axe violations at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto('/factors/');
      const results = await new AxeBuilder({ page })
        .include('[data-filter-rail]')
        .withTags([...A11Y_TAGS])
        .analyze();
      const violations = results.violations.filter(
        (violation) => violation.impact === 'serious' || violation.impact === 'critical',
      );
      expect(
        violations,
        violations.map((violation) => `${violation.id}: ${violation.description}`).join('\n'),
      ).toEqual([]);
    });
  }

  test('category and critical controls expose pressed state', async ({ page }) => {
    await page.goto('/factors/');
    await expect(page.locator('[data-cat-filter]').first()).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    await expect(page.locator('[data-crit-only]')).toHaveAttribute('aria-pressed', 'false');
    await page.locator('[data-cat-filter]').first().click();
    await page.locator('[data-crit-only]').click();
    await expect(page.locator('[data-cat-filter]').first()).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('[data-crit-only]')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('[data-filter-announcement]')).toHaveAttribute('aria-live', 'polite');
  });
});
