/**
 * Playwright config for visual regression baselines (E-16).
 *
 * Runs against a local Astro preview server on port 4321. The webServer
 * config below auto-starts `npm run preview` (which serves dist/ produced
 * by `npm run build`) before tests run.
 *
 * Usage:
 *   npx playwright install chromium       # one-time browser install
 *   npm run build                          # produces dist/
 *   npm run test:visual                    # runs all specs (fails on diff)
 *   npm run test:visual:update             # captures fresh baselines
 *
 * The 5 reference pages are listed in `eng-review-2026-04-23.md` §3F:
 *   1. Spark protocol detail (clean A+CLEAN)
 *   2. Aave v3 detail with active-incident banner
 *   3. Uniswap v4 multi-deployment tabs
 *   4. /protocols/aave-v3/factors/RD-F-022/ (Feature A protocol-contextual)
 *   5. /factors/RD-F-022/ (Feature A global)
 *
 * Pre-M3a, only #5 has a built page. The other 4 specs are scaffolded with
 * `test.skip(true, 'M3a-pending — protocol pages not yet generated')` and
 * will activate once M3a data lands. Update via `npm run test:visual:update`
 * to capture initial baselines once /protocols/<slug>/ pages exist.
 */

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/visual',
  testMatch: /.*\.spec\.ts$/,
  // 0.1% pixel diff threshold per ticket E-16 spec.
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.001, threshold: 0.2 },
  },
  // Snapshots stored per-spec under tests/visual/__snapshots__/
  snapshotPathTemplate:
    '{testDir}/__snapshots__/{testFilePath}/{arg}{-projectName}{-platform}{ext}',
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:4321',
    // Static + deterministic — disable animations, set a fixed viewport
    // so the 0.1% threshold isn't bumped by font rendering noise.
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
  },
  webServer: {
    command: 'npm run preview -- --port 4321',
    url: 'http://localhost:4321',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
