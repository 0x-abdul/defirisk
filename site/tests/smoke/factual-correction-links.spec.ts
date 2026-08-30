import { test, expect } from '@playwright/test';

const FACTUAL_CORRECTION_URL =
  'https://github.com/0x-abdul/defirisk/issues/new?template=factual-correction.md';
const PROTOCOL = 'polymarket';
const FACTOR = 'RD-F-001';

test.describe('Factual-correction links', () => {
  test('protocol detail keeps its contextual action', async ({ page }) => {
    const response = await page.goto(`/protocols/${PROTOCOL}/`);
    expect(response?.status()).toBe(200);

    await expect(page.getByRole('link', { name: 'Correct a fact', exact: true })).toHaveAttribute(
      'href',
      FACTUAL_CORRECTION_URL,
    );
  });

  test('protocol factor assessment links to the existing template', async ({ page }) => {
    const response = await page.goto(`/protocols/${PROTOCOL}/factors/${FACTOR}/`);
    expect(response?.status()).toBe(200);

    await expect(
      page.getByRole('link', { name: 'Open a factual correction', exact: true }),
    ).toHaveAttribute('href', FACTUAL_CORRECTION_URL);
  });

  test('surface factor assessment links to the existing template', async ({ page }) => {
    const response = await page.goto(
      `/protocols/${PROTOCOL}/surfaces/default/factors/${FACTOR}/`,
    );
    expect(response?.status()).toBe(200);

    await expect(
      page.getByRole('link', { name: 'Open a factual correction', exact: true }),
    ).toHaveAttribute('href', FACTUAL_CORRECTION_URL);
  });

  test('About and footer provide stable template links', async ({ page }) => {
    const response = await page.goto('/about/');
    expect(response?.status()).toBe(200);

    await expect(
      page.locator('main#main').getByRole('link', { name: 'Factual Correction', exact: true }),
    ).toHaveAttribute('href', FACTUAL_CORRECTION_URL);
    await expect(
      page.locator('footer').getByRole('link', { name: 'Factual correction', exact: true }),
    ).toHaveAttribute('href', FACTUAL_CORRECTION_URL);
  });
});
