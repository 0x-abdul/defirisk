import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const A11Y_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] as const;

test.describe('Status page (/status/)', () => {
  test('uses the shared shell and exposes a keyboard-scrollable cadence table', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/status/');

    await expect(page).toHaveTitle('System status · DeFi Risk');
    const menu = page.getByRole('button', { name: 'Menu' });
    await expect(menu).toBeVisible();
    await menu.click();
    await expect(menu).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
    await expect(page.getByRole('contentinfo')).toBeVisible();

    const cadenceRegion = page.getByRole('region', { name: 'Cadence bucket table' });
    await expect(cadenceRegion).toHaveAttribute('tabindex', '0');
    await expect(cadenceRegion).toContainText('Continuous');
    await expect(cadenceRegion).toContainText('36');
    const overflow = await cadenceRegion.evaluate((region) => ({
      clientWidth: region.clientWidth,
      scrollWidth: region.scrollWidth,
    }));
    expect(overflow.scrollWidth).toBeGreaterThan(overflow.clientWidth);
    await cadenceRegion.focus();
    await page.keyboard.press('ArrowRight');
    await expect
      .poll(() => cadenceRegion.evaluate((region) => region.scrollLeft))
      .toBeGreaterThan(0);
    const pageOverflow = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth > window.innerWidth,
      body: document.body.scrollWidth > window.innerWidth,
    }));
    expect(pageOverflow).toEqual({ document: false, body: false });
    await expect(page.getByText('Pipeline run history')).toHaveCount(0);
    await expect(page.getByText('Per-protocol freshness')).toHaveCount(0);
  });

  test('has no serious or critical axe violations', async ({ page }) => {
    await page.goto('/status/');
    const results = await new AxeBuilder({ page }).withTags([...A11Y_TAGS]).analyze();
    const violations = results.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical'
    );
    expect(
      violations,
      violations.map((violation) => `${violation.id}: ${violation.description}`).join('\n')
    ).toEqual([]);
  });
});
