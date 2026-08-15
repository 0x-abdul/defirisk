/**
 * E-22 — a11y spec: homepage (/)
 *
 * Checks zero serious/critical axe violations at 1280px and 375px.
 * Tags: wcag2a, wcag2aa, wcag21a, wcag21aa.
 * Excludes wcag2aaa (informational only).
 */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const A11Y_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] as const;

test.describe('Homepage (/)', () => {
  test('no serious/critical axe violations at 1280px', async ({ page }) => {
    await page.goto('/');
    const results = await new AxeBuilder({ page })
      .withTags([...A11Y_TAGS])
      .analyze();
    const violations = results.violations.filter(
      (v) => v.impact === 'serious' || v.impact === 'critical',
    );
    expect(
      violations,
      violations.map((v) => `${v.id}: ${v.description}`).join('\n'),
    ).toEqual([]);
  });

  test('no serious/critical axe violations at 375px (mobile)', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');
    const results = await new AxeBuilder({ page })
      .withTags([...A11Y_TAGS])
      .analyze();
    const violations = results.violations.filter(
      (v) => v.impact === 'serious' || v.impact === 'critical',
    );
    expect(
      violations,
      violations.map((v) => `${v.id}: ${v.description}`).join('\n'),
    ).toEqual([]);
  });

  test('no horizontal scroll at 375px', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');
    const hasHorizontalScroll = await page.evaluate(
      () => document.body.scrollWidth > document.body.clientWidth,
    );
    expect(hasHorizontalScroll).toBe(false);
  });

  test('skip-to-content link is present and focusable', async ({ page }) => {
    await page.goto('/');
    // Tab once to focus the skip link.
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => document.activeElement?.getAttribute('href'));
    expect(focused).toBe('#main');
    await page.keyboard.press('Enter');
    await expect(page.locator('#main')).toBeFocused();
  });

  test('main landmark exists', async ({ page }) => {
    await page.goto('/');
    const main = page.locator('main#main');
    await expect(main).toHaveCount(1);
    await expect(page.locator('main')).toHaveCount(1);
  });

  for (const width of [320, 375, 640, 900]) {
    test(`mobile navigation controls work at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto('/');

      const menu = page.getByRole('button', { name: 'Menu' });
      const nav = page.getByRole('navigation', { name: 'Primary' });
      await expect(menu).toBeVisible();
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await expect(menu).toHaveAttribute('aria-controls', 'primary-navigation');
      await expect(nav).toBeHidden();
      await expect(page.getByRole('group', { name: 'Theme' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'AA' })).toBeVisible();

      await menu.click();
      await expect(menu).toHaveAttribute('aria-expanded', 'true');
      await expect(nav).toBeVisible();
      await expect(nav.getByRole('link', { name: 'Protocols' })).toHaveAttribute(
        'aria-current',
        'page',
      );

      await page.keyboard.press('Escape');
      await expect(nav).toBeHidden();
      await expect(menu).toHaveAttribute('aria-expanded', 'false');
      await expect(page.locator(':focus')).toHaveAttribute('aria-controls', 'primary-navigation');

      await menu.click();
      await nav.getByRole('link', { name: 'Factors' }).click();
      await expect(page).toHaveURL(/\/factors\//);
    });

    test(`document does not overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await page.goto('/');
      const overflow = await page.evaluate(() => ({
        document: document.documentElement.scrollWidth > window.innerWidth,
        body: document.body.scrollWidth > window.innerWidth,
      }));
      expect(overflow).toEqual({ document: false, body: false });
    });
  }

  test('desktop navigation remains visible at 1280px', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Menu' })).toBeHidden();
    await expect(page.getByRole('button', { name: 'AA' })).toBeVisible();
    await expect(
      page.getByRole('navigation').getByRole('link', { name: 'Protocols' }),
    ).toHaveAttribute('aria-current', 'page');
  });

  test('permalinks and code copy controls have contextual names', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: () => Promise.resolve() },
      });
    });
    await page.goto('/data/');
    const permalink = page.locator('h2#base a.alink');
    await expect(permalink).toHaveAccessibleName('Permalink to Versioned base URL');
    await permalink.focus();
    await expect(permalink).toHaveCSS('opacity', '1');
    const copyButton = page.getByRole('button', { name: 'Copy base URL example' });
    await expect(copyButton).toBeVisible();
    await copyButton.click();
    await expect(copyButton).toHaveText('Copied');
    await expect(page.locator('.copy-status').first()).toHaveText('Copied');
  });
});
