import { test, expect } from '@playwright/test';

const VIEWPORTS = [320, 375, 640, 900, 1280] as const;

test.describe('/factors filter controls', () => {
  for (const width of VIEWPORTS) {
    test(`stays usable at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto('/factors/');

      const search = page.locator('[data-search-input]');
      const clear = page.getByRole('button', { name: 'Clear' });
      const announcement = page.locator('[data-filter-announcement]');
      await expect(search).toBeVisible();
      await expect(clear).toBeVisible();
      await expect(announcement).toHaveText('Showing 184 of 184 factors');

      const overflow = await page.evaluate(() => ({
        document: document.documentElement.scrollWidth > window.innerWidth,
        body: document.body.scrollWidth > window.innerWidth,
      }));
      expect(overflow).toEqual({ document: false, body: false });

      if (width <= 900) {
        await expect(page.locator('.scroll-affordance')).toBeVisible();
      }
      if (width <= 640) {
        const searchWidth = await page
          .locator('.search')
          .evaluate((label) => label.getBoundingClientRect().width);
        const controlsWidth = await page
          .locator('.control-row')
          .evaluate((row) => row.getBoundingClientRect().width);
        expect(Math.abs(searchWidth - controlsWidth)).toBeLessThanOrEqual(2);
      }

      const category = page.locator('[data-cat-filter]').first();
      const categoryCount = Number(await category.locator('.ct').textContent());
      await expect(category).toHaveAttribute('aria-pressed', 'false');
      await category.click();
      await expect(category).toHaveAttribute('aria-pressed', 'true');
      await expect(announcement).toHaveText(`Showing ${categoryCount} of 184 factors`);

      const critical = page.locator('[data-crit-only]');
      const criticalCount = await page.locator('a.tbl-row[data-crit="1"]').count();
      await critical.click();
      await expect(critical).toHaveAttribute('aria-pressed', 'true');
      await expect(announcement).toHaveText(/Showing \d+ of 184 factors/);
      expect(criticalCount).toBeGreaterThan(0);

      await search.fill('no-factor-matches-this-query');
      await expect(announcement).toHaveText('Showing 0 of 184 factors');

      await search.focus();
      await expect(search).toBeFocused();
      const focusStyle = await search.evaluate((input) => {
        const style = getComputedStyle(input);
        const wrapper = input.parentElement ? getComputedStyle(input.parentElement) : null;
        return {
          outlineWidth: style.outlineWidth,
          wrapperShadow: wrapper?.boxShadow ?? 'none',
        };
      });
      expect(focusStyle.outlineWidth !== '0px' || focusStyle.wrapperShadow !== 'none').toBe(true);

      await clear.click();
      await expect(search).toHaveValue('');
      await expect(category).toHaveAttribute('aria-pressed', 'false');
      await expect(critical).toHaveAttribute('aria-pressed', 'false');
      await expect(announcement).toHaveText('Showing 184 of 184 factors');
    });
  }
});
