/**
 * Playwright config for axe-core accessibility checks (E-22).
 *
 * Runs against a local Astro preview server on port 4321. The webServer
 * config auto-starts `npm run preview` before the test suite.
 *
 * Usage:
 *   npx playwright install chromium   # one-time browser install
 *   npm run build                      # produce dist/
 *   npm run test:a11y                  # run all a11y specs
 *
 * Failure threshold: zero serious or critical axe violations.
 * Warnings (minor, moderate) are logged but do not fail CI.
 */

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/a11y',
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [['list'], ['json', { outputFile: 'tests/a11y/results.json' }]]
    : [['list']],
  use: {
    baseURL: 'http://localhost:4321',
    viewport: { width: 1280, height: 800 },
  },
  webServer: process.env.PLAYWRIGHT_SKIP_WEBSERVER
    ? undefined
    : {
        command: 'node ./node_modules/astro/bin/astro.mjs preview --port 4321',
        url: 'http://localhost:4321',
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
