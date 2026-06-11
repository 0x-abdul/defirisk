/**
 * E-22 — a11y spec: methodology page (/methodology/)
 *
 * Checks zero serious/critical axe violations at 1280px and 375px.
 * Tags: wcag2a, wcag2aa, wcag21a, wcag21aa.
 * Excludes wcag2aaa (informational only).
 */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const A11Y_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] as const;

test.describe('Methodology page (/methodology/)', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try {
        localStorage.setItem('rd-prefer-contrast', '1');
      } catch (e) {
        /* ignore */
      }
    });
  });

  test('no serious/critical axe violations at 1280px', async ({ page }) => {
    await page.goto('/methodology/');
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
    await page.goto('/methodology/');
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
    await page.goto('/methodology/');
    const hasHorizontalScroll = await page.evaluate(
      () => document.body.scrollWidth > document.body.clientWidth,
    );
    expect(hasHorizontalScroll).toBe(false);
  });

  test('page has a level-one heading', async ({ page }) => {
    await page.goto('/methodology/');
    const h1 = page.locator('h1');
    await expect(h1).toHaveCount(1);
  });
});
