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
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
    // Title contains "DeFi Risk"
    await expect(page).toHaveTitle(/DeFi Risk/);
  });

  test('/protocols/ is a redirect stub to the homepage directory', async ({ request }) => {
    const res = await request.get('/protocols/');
    expect(res?.status()).toBe(200);
    await expect(res.text()).resolves.toContain('Redirecting');
  });

  test('/factors/ renders factor list page', async ({ page }) => {
    const res = await page.goto('/factors/');
    expect(res?.status()).toBe(200);
    await expect(page.locator('h1')).toBeVisible();
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
    await expect(page.getByText(FACTOR_ID).first()).toBeVisible();
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
    // Grade card present
    await expect(page.getByRole('img', { name: /Grade/ }).first()).toBeVisible();
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
    await expect(page.getByText(FACTOR).first()).toBeVisible();
  });
});

test.describe('Private review routes are absent', () => {
  const BOGUS_REVIEW = 'test-protocol-deadbeef';

  test(`/unpublished/${BOGUS_REVIEW}/ cannot render private review content`, async ({ page }) => {
    const res = await page.goto(`/unpublished/${BOGUS_REVIEW}/`);
    // Static hosts may return a 200 while serving the custom 404 document.
    expect([404, 200]).toContain(res?.status());
    await expect(page.locator('.review-banner')).toHaveCount(0);
    if (res?.status() === 200) {
      await expect(page.locator('main')).toBeVisible();
    }
  });
});

test.describe('Hacks detail page', () => {
  test('/hacks/<id>/ renders a hack detail (if any hacks present)', async ({ page }) => {
    // Fetch the hacks index first to get a real hack id
    const indexRes = await page.goto('/hacks/');
    if (indexRes?.status() === 404) {
      test.skip(true, 'Hacks pages are not generated in this public build');
      return;
    }
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
