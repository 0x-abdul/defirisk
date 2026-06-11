/**
 * Playwright config for smoke tests (E-26).
 *
 * Runs against the local Astro preview server (post-build). In CI the
 * smoke-staging job additionally runs against the Cloudflare Pages
 * staging URL via BASE_URL env override.
 *
 * Usage:
 *   npm run build && npm run test:smoke          # local
 *   BASE_URL=https://staging.example.pages.dev npm run test:smoke   # staging
 */

import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.BASE_URL ?? 'http://localhost:4321';

export default defineConfig({
  testDir: './tests/smoke',
  testMatch: /.*\.spec\.ts$/,
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI
    ? [['list'], ['json', { outputFile: 'tests/smoke/results.json' }]]
    : [['list']],
  use: {
    baseURL: BASE_URL,
    // Smoke tests don't need a full browser — use lighter API testing for JSON endpoints.
  },
  // Only spin up a local server when testing localhost; skip when BASE_URL points elsewhere.
  webServer: BASE_URL.startsWith('http://localhost')
    ? {
        command: 'npm run preview -- --port 4321',
        url: 'http://localhost:4321',
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      }
    : undefined,
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
