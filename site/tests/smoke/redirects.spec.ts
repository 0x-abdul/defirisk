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
      'Astro preview does not normalize directory URLs without a trailing slash',
    );
    const res = await page.goto(source);
    expect(res?.status()).toBe(200);
    await expect(page).toHaveURL(new RegExp(`${destination}$`));
  });
}
