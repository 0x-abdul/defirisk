/**
 * E-22 — a11y spec: factor detail, global view (/factors/[id]/)
 *
 * Checks zero serious/critical axe violations at 1280px and 375px.
 * Tags: wcag2a, wcag2aa, wcag21a, wcag21aa.
 * Excludes wcag2aaa (informational only).
 */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const A11Y_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] as const;

// Factor detail (global view) — exists when factors.json is loaded.
const FACTOR_ID = 'RD-F-001';

test.describe(`Factor detail global (/factors/${FACTOR_ID}/)`, () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try {
        localStorage.setItem('rd-prefer-contrast', '1');
      } catch (e) {
        /* ignore */
      }
    });
    const res = await page.goto(`/factors/${FACTOR_ID}/`, { waitUntil: 'domcontentloaded' });
    if (!res || res.status() === 404) {
      test.skip(true, `${FACTOR_ID} factor page not found — factors data pending`);
    }
  });

  test('no serious/critical axe violations at 1280px', async ({ page }) => {
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
    const hasHorizontalScroll = await page.evaluate(
      () => document.body.scrollWidth > document.body.clientWidth,
    );
    expect(hasHorizontalScroll).toBe(false);
  });
});
