import { expect, test } from '@playwright/test';

const supportsDirectoryRedirects = process.env.EXPECT_DIRECTORY_REDIRECTS === '1';

for (const [source, destination, requiresDirectoryRedirect] of [
  ['/api-docs', '/data/', true],
  ['/api-docs/', '/data/', false],
  ['/how-to-use', '/methodology/', true],
  ['/how-to-use/', '/methodology/', false],
] as const) {
  test(`${source} redirects to ${destination}`, async ({ page }) => {
    test.skip(
      requiresDirectoryRedirect && !supportsDirectoryRedirects,
      'Astro preview does not normalize directory URLs without a trailing slash'
    );
    const res = await page.goto(source);
    expect(res?.status()).toBe(200);
    await expect(page).toHaveURL(new RegExp(`${destination}$`));
  });
}

for (const [source, destination] of [
  ['/protocols/eigencloud/', '/protocols/eigenlayer/?surface=default'],
  ['/protocols/hyperliquid-bridge/', '/protocols/hyperliquid/?surface=arbitrum-bridge'],
] as const) {
  test(`${source} is a one-hop Task 10 alias for ${destination}`, async ({ request }) => {
    const res = await request.get(source, { maxRedirects: 0 });
    expect([200, 301, 302, 307, 308]).toContain(res.status());
    if (res.status() >= 300) {
      const location = res.headers().location;
      expect(location).toBeTruthy();
      const target = new URL(location!, 'https://defirisk.invalid');
      expect(`${target.pathname}${target.search}`).toBe(destination);
      return;
    }
    const html = await res.text();
    expect(html).toContain(`http-equiv="refresh" content="2;url=${destination}"`);
    expect(html).toContain('name="robots" content="noindex"');
    expect(html).toContain(`rel="canonical" href="https://defirisk.co${destination}"`);
  });
}
