import { test, expect } from '@playwright/test';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * D2 supplemental screenshots — live build of the 5 reference pages at
 * 375 / 768 / 1280 viewports, written to
 * risk-dashboard/design/screenshots/d2-live-2026-04-26/.
 *
 * Captured 2026-04-26 to back-fill the D2 review's "fresh screenshots of
 * the live site for diff context" requirement after WebFetch blocked
 * localhost in the original sub-agent fan-out. See
 * risk-dashboard/design/d2-review-2026-04-26.md §"What this audit did NOT
 * cover" + §"Supplemental screenshots".
 *
 * This is a one-shot capture, not a baseline. It does not assert pixel
 * fidelity — it only writes PNGs for the review evidence pack. It re-runs
 * idempotently (overwrites the same paths).
 */

const OUT_DIR = path.resolve(
  __dirname,
  '../../../risk-dashboard/design/screenshots/d2-live-2026-04-26',
);

const PAGES = [
  { slug: 'home', url: '/' },
  { slug: 'protocols', url: '/protocols/' },
  { slug: 'methodology', url: '/methodology/' },
  { slug: 'factor-rd-f-022', url: '/factors/RD-F-022/' },
  { slug: 'dev-components', url: '/dev/components/' },
];

const VIEWPORTS = [
  { name: '1280', width: 1280, height: 800 },
  { name: '768', width: 768, height: 1024 },
  { name: '375', width: 375, height: 812 },
];

test.describe('D2 supplemental — live captures', () => {
  for (const page of PAGES) {
    for (const vp of VIEWPORTS) {
      test(`${page.slug} @ ${vp.name}`, async ({ page: pw }) => {
        await pw.setViewportSize({ width: vp.width, height: vp.height });
        await pw.goto(page.url, { waitUntil: 'networkidle' });
        await pw.screenshot({
          path: path.join(OUT_DIR, `${page.slug}-${vp.name}.png`),
          fullPage: true,
        });
        expect(true).toBe(true);
      });
    }
  }
});
