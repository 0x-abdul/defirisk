/**
 * E-22 — a11y spec: protocol detail (/protocols/[slug]/)
 *
 * Checks zero serious/critical axe violations at 1280px and 375px.
 * Tags: wcag2a, wcag2aa, wcag21a, wcag21aa.
 * Excludes wcag2aaa (informational only).
 */
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const A11Y_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] as const;

// Protocol detail pages only exist once M3a data is imported.
// These tests skip gracefully when no protocol pages are built.
const PROTOCOL_SLUG = 'aave-v3';

test.describe(`Protocol detail (/protocols/${PROTOCOL_SLUG}/)`, () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      try {
        localStorage.setItem('rd-prefer-contrast', '1');
      } catch (e) {
        /* ignore */
      }
    });
    const res = await page.goto(`/protocols/${PROTOCOL_SLUG}/`, { waitUntil: 'domcontentloaded' });
    if (!res || res.status() === 404) {
      test.skip(true, `${PROTOCOL_SLUG} page not yet generated — M3a data pending`);
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

  test('LetterPill has aria-label', async ({ page }) => {
    // Letter pills should carry role="img" and an aria-label.
    const pill = page.locator('[class*="letter-pill"]').first();
    const count = await pill.count();
    if (count === 0) {
      test.skip(true, 'No LetterPill found on this page — skip');
    }
    const label = await pill.getAttribute('aria-label');
    expect(label).toBeTruthy();
  });

  test('CategoryGrid cells have aria-label', async ({ page }) => {
    const cells = page.locator('.category-cell');
    const count = await cells.count();
    if (count === 0) {
      test.skip(true, 'No category cells found — skip');
    }
    // Each category cell has an aria-label; spot-check the first one.
    const label = await cells.first().getAttribute('aria-label');
    expect(label).toBeTruthy();
  });
});
