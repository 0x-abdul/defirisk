import { expect, test } from '@playwright/test';

const FAMILY = '/protocols/fixture-family/';
const HEADER_FAMILY = '/protocols/fixture-header-family/';

async function requireFixture(page: import('@playwright/test').Page, path: string) {
  const response = await page.goto(path, { waitUntil: 'networkidle' });
  if (!response || response.status() === 404) {
    test.skip(true, 'Synthetic family fixture is not installed for this build');
  }
}

async function factorText(page: import('@playwright/test').Page) {
  return page.locator('details[id^="cat-"]').evaluateAll((cards) =>
    cards.map((card) => ({
      id: card.id,
      summary: card.querySelector('summary')?.textContent?.replace(/\s+/g, ' ').trim(),
      factors: [...card.querySelectorAll('[role="listitem"]')].map((row) => ({
        element: row.tagName.toLowerCase(),
        id: row.children[0]?.textContent?.trim(),
        status: row.children[1]?.textContent?.trim(),
        headline: row.children[2]?.firstElementChild?.textContent?.trim(),
        evidence: row.children[2]?.lastElementChild?.textContent?.trim(),
        linked: row instanceof HTMLAnchorElement,
      })),
    }))
  );
}

test.describe('Family factor alignment fixture', () => {
  test('queryless SSR and hydrated state select greatest-TVL ungraded surface', async ({
    page,
    request,
  }) => {
    const response = await request.get(FAMILY);
    if (response.status() === 404) test.skip(true, 'Synthetic family fixture is not installed');
    const html = await response.text();
    expect(html).toContain('Version 2');
    expect(html).toContain('Not yet scored');
    expect(html).toMatch(/data-family-cap[^>]*hidden/);

    await requireFixture(page, FAMILY);
    await expect(page.getByRole('tab', { name: 'Version 2' })).toHaveAttribute(
      'aria-selected',
      'true'
    );
    await expect(page.getByText('Surface grade', { exact: false })).toContainText('Version 2');
    await expect(page.getByText('Risk profile at a glance')).toBeVisible();
  });

  test('overview hides assessment factor module and has a shareable URL', async ({ page }) => {
    await requireFixture(page, `${FAMILY}?view=overview`);
    await expect(page).toHaveURL(/\?view=overview$/);
    await expect(page.getByRole('tab', { name: 'Overview' })).toHaveAttribute(
      'aria-selected',
      'true'
    );
    await expect(page.getByRole('heading', { name: 'Family overview' })).toBeVisible();
    await expect(page.getByText('Risk profile at a glance')).toHaveCount(0);
  });

  test('selected surface owns grade, cap, risk and reviewed provenance', async ({ page }) => {
    await requireFixture(page, HEADER_FAMILY);
    await expect(page.getByRole('tab', { name: 'Secure markets' })).toHaveAttribute(
      'aria-selected',
      'true'
    );
    await expect(page.locator('[data-family-grade-scored] .n')).toHaveText('42.7');
    await expect(page.getByText('Synthetic default-surface cap.', { exact: true })).toBeVisible();
    await expect(page.locator('[data-family-field="provenance-date"]')).toContainText('2026-06-15');

    await page.getByRole('tab', { name: 'Legacy markets' }).click();
    await expect(page).toHaveURL(/\?surface=legacy$/);
    await expect(page.locator('[data-family-cap]')).toBeHidden();
  });

  test('deployment selection applies full effective evidence and labels partial overrides', async ({
    page,
  }) => {
    await requireFixture(page, FAMILY);
    await page.getByRole('button', { name: /All deployments/ }).click();
    const dialog = page.getByRole('dialog', { name: 'Select deployment' });
    await dialog.getByRole('button').nth(2).click();

    await expect(page).toHaveURL(/surface=v2&deployment=v2-1&chain=/);
    await expect(page.getByText('Deployment overrides + surface fallback')).toHaveCount(2);
    const firstCategory = page.locator('#cat-1');
    await expect(firstCategory.locator('summary')).toContainText('88');
    await expect(firstCategory).toContainText('Synthetic partial deployment-scoped override.');
    await expect(firstCategory).toContainText('Audit-to-deploy gap');
    await expect(page.locator('#cat-13 summary')).toContainText('Gray');
    await expect(page.locator('#cat-13')).toContainText(
      'Synthetic deployment-unassessed category.'
    );
  });

  test('tabs retain unrelated query and hash, support keyboard, and restore history', async ({
    page,
  }) => {
    await requireFixture(page, `${FAMILY}?surface=core&campaign=qa#assessment`);
    const core = page.getByRole('tab', { name: 'Core markets' });
    const v2 = page.getByRole('tab', { name: 'Version 2' });
    await expect(core).toHaveAttribute('href', /campaign=qa/);
    await expect(core).toHaveAttribute('href', /#assessment$/);
    await expect(core).toHaveAttribute('aria-selected', 'true');

    const initialHistoryLength = await page.evaluate(() => window.history.length);
    await core.click();
    await core.click();
    expect(await page.evaluate(() => window.history.length)).toBe(initialHistoryLength);

    await core.focus();
    await page.keyboard.press('ArrowRight');
    await expect(v2).toBeFocused();
    await expect(v2).toHaveAttribute('aria-selected', 'true');
    await expect(page).toHaveURL(
      `${new URL(FAMILY, 'http://localhost').pathname}?surface=v2&campaign=qa#assessment`
    );
    expect(await page.evaluate(() => window.history.length)).toBe(initialHistoryLength + 1);

    await page.keyboard.press('Enter');
    expect(await page.evaluate(() => window.history.length)).toBe(initialHistoryLength + 1);

    await page.goBack();
    await expect(page).toHaveURL(
      `${new URL(FAMILY, 'http://localhost').pathname}?surface=core&campaign=qa#assessment`
    );
    await expect(core).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText('Surface grade', { exact: false })).toContainText('Core markets');

    await page.goForward();
    await expect(v2).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText('Surface grade', { exact: false })).toContainText('Version 2');
  });

  test('surface hrefs follow native category hash changes', async ({ page }) => {
    await requireFixture(page, FAMILY);
    await page.getByRole('link', { name: /Code & audits category:/ }).click();
    await expect(page).toHaveURL(/#cat-1$/);
    await expect(page.getByRole('tab', { name: 'Core markets' })).toHaveAttribute(
      'href',
      /#cat-1$/
    );
  });

  test('family and non-family share normalized factor-card output for the same model', async ({
    page,
  }) => {
    await requireFixture(page, `${FAMILY}?surface=core`);
    const familyFactors = await factorText(page);
    await page.goto('/protocols/aave-v3/', { waitUntil: 'networkidle' });
    const protocolFactors = await factorText(page);
    expect(familyFactors).toStrictEqual(protocolFactors);
  });

  // 320 CSS pixels is the WCAG reflow equivalent of a 640px viewport at
  // 200% browser zoom, while 375px covers the repository's mobile baseline.
  for (const width of [320, 375]) {
    test(`mobile factor layout does not clip horizontally at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await requireFixture(page, FAMILY);
      const overflows = await page.evaluate(() => ({
        document: document.documentElement.scrollWidth > window.innerWidth,
        body: document.body.scrollWidth > window.innerWidth,
      }));
      expect(overflows).toEqual({ document: false, body: false });
    });

    test(`mobile Overview is readable and locally scrollable at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 812 });
      await requireFixture(page, `${FAMILY}?view=overview`);
      const comparison = page.getByRole('region', { name: 'Surface comparison' });
      await expect(comparison).toBeVisible();
      expect(await page.getByRole('columnheader').count()).toBe(7);
      expect(await page.getByRole('row').count()).toBe(3);

      const measurements = await comparison.evaluate((element) => ({
        scrollWidth: element.scrollWidth,
        clientWidth: element.clientWidth,
        documentOverflow: document.documentElement.scrollWidth > window.innerWidth,
        bodyOverflow: document.body.scrollWidth > window.innerWidth,
      }));
      expect(measurements.scrollWidth).toBeGreaterThan(measurements.clientWidth);
      expect(measurements.documentOverflow).toBe(false);
      expect(measurements.bodyOverflow).toBe(false);

      await comparison.focus();
      await page.keyboard.press('ArrowRight');
      await expect
        .poll(() => comparison.evaluate((element) => element.scrollLeft))
        .toBeGreaterThan(0);
    });
  }

  test('mobile family controls meet the 44px touch-target minimum', async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 812 });
    await requireFixture(page, FAMILY);
    const categoryTargets = await page
      .getByRole('link', { name: /category:/ })
      .evaluateAll((links) =>
        links.map((link) => {
          const box = link.getBoundingClientRect();
          return { width: box.width, height: box.height };
        })
      );
    expect(categoryTargets).toHaveLength(13);
    expect(categoryTargets.every(({ width, height }) => width >= 44 && height >= 44)).toBe(true);

    await page.getByRole('button', { name: /All deployments/ }).click();
    const close = page.getByRole('button', { name: 'Close' });
    const closeBox = await close.evaluate((button) => {
      const box = button.getBoundingClientRect();
      return { width: box.width, height: box.height };
    });
    expect(closeBox.width).toBeGreaterThanOrEqual(44);
    expect(closeBox.height).toBeGreaterThanOrEqual(44);
  });
});
