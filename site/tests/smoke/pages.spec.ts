/**
 * Smoke tests — page renders (E-26)
 *
 * Navigates to key pages and asserts they return 200 and contain expected
 * structural content. Fast (~2s per page). Does not test axe — that's E-22.
 */

import { test, expect } from '@playwright/test';

test.describe('Core pages — always present', () => {
  test('/ renders with dashboard title', async ({ page }) => {
    const res = await page.goto('/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('header')).toBeVisible();
    // Title contains "DeFi Risk"
    await expect(page).toHaveTitle(/DeFi Risk/);
  });

  test('/protocols/ renders protocol list page', async ({ page }) => {
    const res = await page.goto('/protocols/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
    await expect(page).toHaveTitle(/Protocol/i);
  });

  test('/factors/ renders factor list page', async ({ page }) => {
    const res = await page.goto('/factors/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
  });

  test('/hacks/ renders hacks ledger', async ({ page }) => {
    const res = await page.goto('/hacks/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
  });

  test('/incidents/ renders incidents page', async ({ page }) => {
    const res = await page.goto('/incidents/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('main')).toBeVisible();
  });

  test('/methodology/ renders methodology page', async ({ page }) => {
    const res = await page.goto('/methodology/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
  });

  test('/methodology/changelog/ renders changelog page', async ({ page }) => {
    const res = await page.goto('/methodology/changelog/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
  });

  test('/about/ renders about page', async ({ page }) => {
    const res = await page.goto('/about/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
  });

  test('/data/ renders data/API page', async ({ page }) => {
    const res = await page.goto('/data/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
  });

  test('/status/ renders status page', async ({ page }) => {
    const res = await page.goto('/status/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('main')).toBeVisible();
  });

  test('/api-docs/ renders API documentation page', async ({ page }) => {
    const res = await page.goto('/api-docs/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
  });

  test('404 page renders for unknown path', async ({ page }) => {
    const res = await page.goto('/this-does-not-exist-xyz/');
    expect([404, 200]).toContain(res?.status()); // Cloudflare returns 200 for custom 404
    await expect(page.locator('main')).toBeVisible();
  });
});

test.describe('Factor detail page', () => {
  const FACTOR_ID = 'RD-F-001';

  test(`/factors/${FACTOR_ID}/ renders factor detail`, async ({ page }) => {
    const res = await page.goto(`/factors/${FACTOR_ID}/`);
    if (res?.status() === 404) {
      test.skip(true, `${FACTOR_ID} page not generated — factor data pending`);
      return;
    }
    expect(res?.status()).toBe(200);
    // Factor ID visible somewhere on page
    await expect(page.getByText(FACTOR_ID)).toBeVisible();
  });
});

test.describe('Protocol detail page (M3a)', () => {
  const SLUG = 'aave-v3';

  test(`/protocols/${SLUG}/ renders protocol detail`, async ({ page }) => {
    const res = await page.goto(`/protocols/${SLUG}/`);
    if (res?.status() === 404) {
      test.skip(true, `${SLUG} page not generated — M3a data pending`);
      return;
    }
    expect(res?.status()).toBe(200);
    // Protocol name visible
    await expect(page.locator('h1')).toBeVisible();
    // LetterPill present (grade rendered)
    await expect(page.locator('[class*="letter-pill"]').first()).toBeVisible();
  });
});

test.describe('Protocol-level factor detail page (M3a)', () => {
  const SLUG = 'aave-v3';
  // RD-F-028 is a ★ governance factor — known red/yellow for aave-v3
  const FACTOR = 'RD-F-028';

  test(`/protocols/${SLUG}/factors/${FACTOR}/ renders per-protocol factor page`, async ({ page }) => {
    const res = await page.goto(`/protocols/${SLUG}/factors/${FACTOR}/`);
    if (res?.status() === 404) {
      test.skip(true, `${SLUG}/${FACTOR} page not generated — M3a data pending`);
      return;
    }
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
    // Factor ID appears somewhere on the page
    await expect(page.getByText(FACTOR)).toBeVisible();
  });
});

test.describe('Unpublished review page', () => {
  // No unpublished fixtures exist in data/api/v1.7.0/unpublished/ at time of writing.
  // This test asserts that a well-formed but non-existent token returns 404 (or
  // the site's custom 404 page), proving the route does not 500 on bad tokens.
  // When a real unpublished fixture is added, extend this suite with a 200-assert.
  const BOGUS_REVIEW = 'test-protocol-deadbeef';

  test(`/unpublished/${BOGUS_REVIEW}/ returns 404 for unknown token`, async ({ page }) => {
    const res = await page.goto(`/unpublished/${BOGUS_REVIEW}/`);
    // Cloudflare Pages may serve a 200 with a custom 404 page; both are acceptable.
    // What must NOT happen: a 500 server error.
    expect([404, 200]).toContain(res?.status());
    if (res?.status() === 200) {
      // The custom 404 page should still render a <main> element.
      await expect(page.locator('main')).toBeVisible();
    }
  });
});

test.describe('Hacks detail page', () => {
  test('/hacks/<id>/ renders a hack detail (if any hacks present)', async ({ page }) => {
    // Fetch the hacks index first to get a real hack id
    const indexRes = await page.goto('/hacks/');
    expect(indexRes?.status()).toBe(200);

    // Look for any hack link
    const hackLink = page.locator('a[href^="/hacks/"]').first();
    const href = await hackLink.getAttribute('href').catch(() => null);
    if (!href || href === '/hacks/') {
      test.skip(true, 'No hack detail pages generated yet');
      return;
    }

    const res = await page.goto(href);
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
  });
});
